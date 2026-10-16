"""Portable, keyless literature discovery; neither source certifies Scopus indexing."""
from __future__ import annotations

import asyncio
import random
from datetime import datetime, timezone
from typing import Any

import httpx
from bs4 import BeautifulSoup

JOURNAL_DOMAINS = ("jisponline.com", "jcdr.net", "ijdr.in", "pmc.ncbi.nlm.nih.gov")
HEADERS = {"User-Agent": "Forge-AcademicSearch/1.0 (personal academic literature discovery)",
           "Accept": "application/json"}


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
