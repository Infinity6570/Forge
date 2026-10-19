"""Portable, keyless literature discovery; neither source certifies Scopus indexing."""
from __future__ import annotations

import asyncio
import random
import re
import threading
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any

import httpx
from bs4 import BeautifulSoup

JOURNAL_DOMAINS = ("jisponline.com", "jcdr.net", "ijdr.in", "pmc.ncbi.nlm.nih.gov")
HEADERS = {"User-Agent": "Forge-AcademicSearch/1.0 (personal academic literature discovery)",
           "Accept": "application/json"}
NCBI_HEADERS = {
    "User-Agent": "Forge-PubMedSearch/1.0 (personal academic literature discovery)",
    "Accept": "application/xml",
}
_NCBI_REQUEST_INTERVAL = 1 / 3
_ncbi_rate_lock = threading.Lock()
_ncbi_next_request_at = 0.0


def reconstruct_abstract(index: dict[str, list[int]] | None) -> str:
    """Sort indexed words without allocating an array from untrusted offsets."""
    if not isinstance(index, dict):
        return ""
    positions = {
        position: word for word, offsets in index.items() if isinstance(offsets, list)
        for position in offsets if isinstance(position, int) and not isinstance(position, bool) and position >= 0
    }
    return " ".join(positions[position] for position in sorted(positions))


def _openalex_work(work: dict[str, Any]) -> dict[str, Any]:
    location = work.get("primary_location") or {}
    source = location.get("source") or {}
    doi = work.get("doi") or ""
    abstract = reconstruct_abstract(work.get("abstract_inverted_index"))
    return {
        "id": work.get("id"), "title": work.get("display_name") or work.get("title") or "",
        "authors": [(a.get("author") or {}).get("display_name", "") for a in work.get("authorships", [])],
        "year": work.get("publication_year"), "journal": source.get("display_name") or "",
        "doi": doi, "url": doi or location.get("landing_page_url") or work.get("id") or "",
        "abstract": abstract, "text": abstract,
        "is_open_access": (work.get("open_access") or {}).get("is_oa", False),
        "full_text_urls": [location["pdf_url"]] if location.get("pdf_url") else [],
        "sources": ["openalex"],
    }


def _europepmc_work(work: dict[str, Any]) -> dict[str, Any]:
    doi, pmcid = work.get("doi") or "", work.get("pmcid") or ""
    abstract = BeautifulSoup(work.get("abstractText") or "", "html.parser").get_text(" ", strip=True)
    return {
        "id": f"europepmc:{work.get('source', 'MED')}:{work.get('id', '')}",
        "title": work.get("title") or "",
        "authors": [a.get("fullName") or a.get("collectiveName") or "" for a in
                    (work.get("authorList") or {}).get("author", [])] or
                   [name.strip() for name in (work.get("authorString") or "").split(",") if name.strip()],
        "year": int(work["pubYear"]) if str(work.get("pubYear", "")).isdigit() else None,
        "journal": ((work.get("journalInfo") or {}).get("journal") or {}).get("title") or "",
        "doi": f"https://doi.org/{doi}" if doi and not doi.startswith("http") else doi,
        "url": f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/" if pmcid else
               f"https://doi.org/{doi}" if doi else
               f"https://europepmc.org/article/{work.get('source', 'MED')}/{work.get('id', '')}",
        "abstract": abstract, "text": abstract, "pmcid": pmcid,
        "is_open_access": work.get("isOpenAccess") == "Y",
        "full_text_urls": [link["url"] for link in
                           (work.get("fullTextUrlList") or {}).get("fullTextUrl", []) if link.get("url")],
        "sources": ["europepmc"],
    }


async def _source_search(client: httpx.AsyncClient, source: str, query: str,
                         year_from: int, max_results: int) -> tuple[list[dict], dict]:
    if source == "openalex":
        url = "https://api.openalex.org/works"
        params = {"search": query, "filter": f"from_publication_date:{year_from}-01-01",
                  "per-page": max_results}
    else:
        url = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
        params = {"query": f"({query}) AND FIRST_PDATE:[{year_from}-01-01 TO 3000-12-31]",
                  "resultType": "core", "format": "json", "pageSize": max_results}
    try:
        for attempt in range(2):
            response = await client.get(url, params=params)
            if response.status_code in {429, 502, 503, 504} and attempt == 0:
                await asyncio.sleep(1.5 + random.uniform(0, 0.3))
                continue
            response.raise_for_status()
            payload = response.json()
            items = payload["results"] if source == "openalex" else payload["resultList"]["result"]
            if not isinstance(items, list):
                raise ValueError("Invalid results list")
            parse = _openalex_work if source == "openalex" else _europepmc_work
            results = [parse(item) for item in items if isinstance(item, dict)]
            return results, {"status": "ok" if results else "empty", "count": len(results)}
    except httpx.HTTPStatusError as error:
        reason = f"HTTP {error.response.status_code}"
    except httpx.TimeoutException:
        reason = "Timeout"
    except httpx.RequestError:
        reason = "Network error"
    except (ValueError, TypeError, KeyError, AttributeError):
        reason = "Malformed response"
    return [], {"status": "error", "count": 0, "error": reason}


async def academic_search(query: str, year_from: int = 2016, max_results: int = 15) -> dict[str, Any]:
    query = query.strip()
    if not query or len(query) > 2000:
        raise ValueError("Academic query must contain 1–2000 characters.")
    current_year = datetime.now(timezone.utc).year
    if isinstance(year_from, bool) or not isinstance(year_from, int) or not 1000 <= year_from <= current_year:
        raise ValueError("year_from must be an integer between 1000 and the current year.")
    if isinstance(max_results, bool) or not isinstance(max_results, int) or not 1 <= max_results <= 50:
        raise ValueError("max_results must be an integer between 1 and 50.")
    names = ("openalex", "europepmc")
    async with httpx.AsyncClient(timeout=httpx.Timeout(20), headers=HEADERS, follow_redirects=False) as client:
        responses = await asyncio.gather(*(
            _source_search(client, name, query, year_from, max_results) for name in names
        ))
    # Interleave providers so one source cannot crowd the other out.
    merged: dict[str, dict] = {}
    for index in range(max(len(response[0]) for response in responses)):
        for items, _ in responses:
            if index >= len(items):
                continue
            work = items[index]
            doi = work["doi"].lower().removeprefix("https://doi.org/").removeprefix("http://doi.org/")
            key = doi or (f"{work['title'].casefold().strip()}:{work['year']}" if work["title"] else work["id"])
            if key in merged:
                previous = merged[key]
                previous["sources"] = list(dict.fromkeys(previous["sources"] + work["sources"]))
                previous["full_text_urls"] = list(dict.fromkeys(previous["full_text_urls"] + work["full_text_urls"]))
                previous["is_open_access"] = previous["is_open_access"] or work["is_open_access"]
                for field in ("abstract", "text", "authors", "journal", "doi"):
                    if not previous[field]:
                        previous[field] = work[field]
                if work.get("pmcid"):
                    previous["pmcid"], previous["url"] = work["pmcid"], work["url"]
            else:
                merged[key] = work
    sources = {name: response[1] for name, response in zip(names, responses)}
    results = list(merged.values())[:max_results]
    return {
        "engine": "academic-search", "query": query, "year_from": year_from, "results": results,
        "sources": sources, "partial": any(s["status"] == "error" for s in sources.values()),
        "warning": ("Coverage is not exhaustive. These APIs are not Google Scholar or Scopus searches; "
                    "a returned paper is not proof of Scopus indexing. Abstracts and full text may be unavailable."),
        **({"error": "No academic results were available. Try targeted journal web searches.",
            "suggested_web_queries": [f"{query} site:{domain}" for domain in JOURNAL_DOMAINS]} if not results else {}),
    }


async def _ncbi_get(
    client: httpx.AsyncClient,
    endpoint: str,
    params: dict[str, str | int],
) -> httpx.Response:
    """Reserve a request slot shared across concurrent PubMed tool calls."""
    global _ncbi_next_request_at
    with _ncbi_rate_lock:
        now = time.monotonic()
        wait = max(0.0, _ncbi_next_request_at - now)
        _ncbi_next_request_at = max(now, _ncbi_next_request_at) + _NCBI_REQUEST_INTERVAL
    if wait:
        await asyncio.sleep(wait)
    response = await client.get(endpoint, params=params)
    response.raise_for_status()
    return response


def _xml_text(element: ET.Element | None) -> str:
    if element is None:
        return ""
    return " ".join(" ".join(element.itertext()).split())


def _bibtex_escape(value: str) -> str:
    replacements = {
        "\\": r"\textbackslash{}",
        "{": r"\{",
        "}": r"\}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
    }
    return "".join(replacements.get(char, char) for char in value)


def _pubmed_article(article: ET.Element) -> dict[str, Any]:
    medline = article.find("./MedlineCitation")
    article_data = medline.find("./Article") if medline is not None else None
    if article_data is None:
        return {}

    pmid = _xml_text(medline.find("./PMID")) if medline is not None else ""
    title = _xml_text(article_data.find("./ArticleTitle"))
    journal_data = article_data.find("./Journal")
    journal = _xml_text(journal_data.find("./Title")) if journal_data is not None else ""
    journal_abbreviation = (
        _xml_text(journal_data.find("./ISOAbbreviation")) if journal_data is not None else ""
    )
    issue_data = journal_data.find("./JournalIssue") if journal_data is not None else None
    volume = _xml_text(issue_data.find("./Volume")) if issue_data is not None else ""
    issue = _xml_text(issue_data.find("./Issue")) if issue_data is not None else ""
    pagination = article_data.find("./Pagination")
    pages = _xml_text(pagination.find("./MedlinePgn")) if pagination is not None else ""

    author_names: list[str] = []
    author_list = article_data.find("./AuthorList")
    if author_list is not None:
        for author in author_list.findall("./Author"):
            collective = _xml_text(author.find("./CollectiveName"))
            if collective:
                author_names.append(collective)
                continue
            last_name = _xml_text(author.find("./LastName"))
            initials = _xml_text(author.find("./Initials"))
            if not initials:
                initials = "".join(
                    word[0].upper() for word in _xml_text(author.find("./ForeName")).split() if word
                )
            if last_name:
                author_names.append(f"{last_name} {initials}".strip())

    pub_year = ""
    article_date = article_data.find("./ArticleDate/Year")
    pub_date = issue_data.find("./PubDate") if issue_data is not None else None
    for candidate in (
        _xml_text(article_date),
        _xml_text(pub_date.find("./Year")) if pub_date is not None else "",
        _xml_text(pub_date.find("./MedlineDate")) if pub_date is not None else "",
    ):
        year_match = re.search(r"\b(19|20|21)\d{2}\b", candidate)
        if year_match:
            pub_year = year_match.group(0)
            break

    abstract_sections: list[dict[str, str]] = []
    abstract_data = article_data.find("./Abstract")
    if abstract_data is not None:
        for abstract_text in abstract_data.findall("./AbstractText"):
            section_text = _xml_text(abstract_text)
            if section_text:
                abstract_sections.append({
                    "label": abstract_text.attrib.get("Label", "").strip(),
                    "text": section_text,
                })
    abstract = "\n".join(
        f"{section['label']}: {section['text']}" if section["label"] else section["text"]
        for section in abstract_sections
    )

    article_ids = article.find("./PubmedData/ArticleIdList")
    doi = pmcid = ""
    if article_ids is not None:
        for item in article_ids.findall("./ArticleId"):
            kind, value = item.attrib.get("IdType", "").lower(), _xml_text(item)
            if kind == "doi":
                doi = value
            elif kind == "pmc":
                pmcid = value if value.startswith("PMC") else f"PMC{value}"
    if not doi:
        for item in article_data.findall("./ELocationID"):
            if item.attrib.get("EIdType", "").lower() == "doi":
                doi = _xml_text(item)
                break

    mesh_terms = []
    if medline is not None:
        mesh_heading_list = medline.find("./MeshHeadingList")
        if mesh_heading_list is not None:
            for descriptor in mesh_heading_list.findall("./MeshHeading/DescriptorName"):
                value = _xml_text(descriptor)
                if value:
                    mesh_terms.append(value)

    authors_for_citation = author_names[:6]
    if len(author_names) > 6:
        authors_for_citation.append("et al.")
    citation_authors = ", ".join(authors_for_citation)
    citation_journal = journal_abbreviation or journal
    citation = f"{citation_authors}. " if citation_authors else ""
    citation += f"{title}."
    if citation_journal:
        citation += f" {citation_journal}."
    if pub_year:
        citation += f" {pub_year}"
    if volume:
        citation += f";{volume}"
        if issue:
            citation += f"({issue})"
    elif issue:
        citation += f";({issue})"
    if pages:
        citation += f":{pages}"
    if pub_year or volume or issue or pages:
        citation += "."
    if doi:
        citation += f" doi:{doi}."
    if pmid:
        citation += f" PMID:{pmid}."

    first_author = re.sub(r"[^A-Za-z0-9]+", "", author_names[0].split()[0]) if author_names else "pubmed"
    cite_key = f"{first_author}{pub_year or 'nd'}{pmid or 'record'}"
    bibtex_fields = {
        "author": " and ".join(author_names),
        "title": title,
        "journal": journal,
        "year": pub_year,
        "volume": volume,
        "number": issue,
        "pages": pages,
        "doi": doi,
        "pmid": pmid,
    }
    bibtex = "@article{" + cite_key + ",\n" + ",\n".join(
        f"  {key} = {{{_bibtex_escape(value)}}}"
        for key, value in bibtex_fields.items() if value
    ) + "\n}"
    url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else ""
    return {
        "pmid": pmid,
        "pmcid": pmcid,
        "title": title,
        "authors": author_names,
        "year": int(pub_year) if pub_year else None,
        "journal": journal,
        "journal_abbreviation": journal_abbreviation,
        "volume": volume,
        "issue": issue,
        "pages": pages,
        "doi": doi,
        "url": url,
        "abstract_sections": abstract_sections,
        "abstract": abstract,
        "mesh_terms": mesh_terms,
        "vancouver_citation": citation,
        "bibtex": bibtex,
        "sources": ["pubmed"],
    }


async def pubmed_search(
    query: str,
    year_from: int = 2016,
    max_results: int = 15,
) -> dict[str, Any]:
    """Search NCBI PubMed and return parsed records plus Vancouver/BibTeX citations."""
    query = query.strip() if isinstance(query, str) else ""
    if not query or len(query) > 2_000:
        raise ValueError("PubMed query must contain 1–2,000 characters.")
    current_year = datetime.now(timezone.utc).year
    if isinstance(year_from, bool) or not isinstance(year_from, int) or not 1000 <= year_from <= current_year:
        raise ValueError(f"year_from must be an integer between 1000 and {current_year}.")
    if isinstance(max_results, bool) or not isinstance(max_results, int) or not 1 <= max_results <= 50:
        raise ValueError("max_results must be an integer between 1 and 50.")

    base_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(20), headers=NCBI_HEADERS) as client:
            search_response = await _ncbi_get(
                client,
                f"{base_url}/esearch.fcgi",
                {
                    "db": "pubmed",
                    "term": query,
                    "retmax": max_results,
                    "retmode": "xml",
                    "datetype": "pdat",
                    "mindate": year_from,
                    "maxdate": current_year,
                    "tool": "Forge",
                },
            )
            search_root = ET.fromstring(search_response.content)
            count_text = _xml_text(search_root.find("./Count"))
            total_count = int(count_text) if count_text.isdigit() else 0
            pmids = [
                _xml_text(item) for item in search_root.findall("./IdList/Id")
                if _xml_text(item).isdigit()
            ][:max_results]
            if not pmids:
                return {
                    "engine": "pubmed",
                    "query": query,
                    "year_from": year_from,
                    "total_available": total_count,
                    "results": [],
                    "sources": {"pubmed": {"status": "empty", "count": 0}},
                }
            fetch_response = await _ncbi_get(
                client,
                f"{base_url}/efetch.fcgi",
                {"db": "pubmed", "id": ",".join(pmids), "retmode": "xml", "tool": "Forge"},
            )
            fetch_root = ET.fromstring(fetch_response.content)
            articles = [
                parsed for article in fetch_root.findall("./PubmedArticle")
                if (parsed := _pubmed_article(article))
            ]
    except httpx.HTTPStatusError as error:
        return {
            "engine": "pubmed",
            "query": query,
            "year_from": year_from,
            "results": [],
            "error": f"NCBI PubMed returned HTTP {error.response.status_code}.",
        }
    except httpx.TimeoutException:
        return {"engine": "pubmed", "query": query, "year_from": year_from, "results": [], "error": "NCBI PubMed timed out."}
    except (httpx.RequestError, ET.ParseError, ValueError):
        return {"engine": "pubmed", "query": query, "year_from": year_from, "results": [], "error": "NCBI PubMed returned an unavailable or malformed response."}

    return {
        "engine": "pubmed",
        "query": query,
        "year_from": year_from,
        "total_available": total_count,
        "returned": len(articles),
        "results": articles,
        "sources": {"pubmed": {"status": "ok" if articles else "empty", "count": len(articles)}},
        "citation_note": "Vancouver and BibTeX strings are generated from returned PubMed metadata; verify them against the journal’s instructions before submission.",
    }
