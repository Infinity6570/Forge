from __future__ import annotations

import asyncio
import json
import unittest
from unittest.mock import AsyncMock, patch

import httpx

import main
from tools.academic_search import academic_search, pubmed_search, reconstruct_abstract
from tools.web_search import SearchError, routed_search


def openalex_response():
    return {"results": [{
        "id": "https://openalex.org/W1", "display_name": "Periodontal trial", "publication_year": 2022,
        "doi": "https://doi.org/10.123/trial",
        "abstract_inverted_index": {"trial": [2], "A": [0], "clinical": [1]},
        "authorships": [{"author": {"display_name": "Researcher"}}],
        "primary_location": {"source": {"display_name": "JISP"}, "pdf_url": "https://example.org/trial.pdf"},
        "open_access": {"is_oa": True},
    }]}


def pmc_response(doi="10.123/other"):
    return {"resultList": {"result": [{
        "id": "123", "source": "MED", "title": "Regional dental trial", "pubYear": "2021",
        "doi": doi, "pmcid": "PMC123", "abstractText": "<p>Clinical <b>results</b>.</p>",
        "authorList": {"author": [{"fullName": "Trial Author"}]},
        "journalInfo": {"journal": {"title": "IJDR"}}, "isOpenAccess": "Y",
        "fullTextUrlList": {"fullTextUrl": [{"url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC123/"}]},
    }]}}


class AcademicSearchTests(unittest.IsolatedAsyncioTestCase):
    def transport(self, handler):
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler), headers={
            "User-Agent": "Forge-AcademicSearch/1.0",
        })
        return patch("tools.academic_search.httpx.AsyncClient", return_value=client)

    def test_abstract_positions_and_missing_abstract(self):
        self.assertEqual(reconstruct_abstract({"word": [2, 0], "another": [1]}), "word another word")
        self.assertEqual(reconstruct_abstract(None), "")
        self.assertEqual(reconstruct_abstract({"word": [-1, "bad", True]}), "")

    async def test_parallel_sources_params_full_abstracts_and_metadata(self):
        started = set()
        both_started = asyncio.Event()

        async def handler(request):
            started.add(request.url.host)
            if len(started) == 2:
                both_started.set()
            await asyncio.wait_for(both_started.wait(), 1)
            self.assertIn("Forge", request.headers["User-Agent"])
            self.assertNotIn("Authorization", request.headers)
            self.assertNotIn("api_key", request.url.params)
            if request.url.host == "api.openalex.org":
                self.assertEqual(request.url.params["search"], "periodontitis & therapy")
                self.assertEqual(request.url.params["filter"], "from_publication_date:2016-01-01")
                self.assertEqual(request.url.params["per-page"], "15")
                return httpx.Response(200, json=openalex_response())
            self.assertEqual(request.url.params["resultType"], "core")
            self.assertEqual(request.url.params["pageSize"], "15")
            self.assertIn("FIRST_PDATE:[2016-01-01", request.url.params["query"])
            return httpx.Response(200, json=pmc_response())

        with self.transport(handler):
            result = await academic_search("periodontitis & therapy")
        self.assertEqual(len(result["results"]), 2)
        first, second = result["results"]
        self.assertEqual(first["abstract"], "A clinical trial")
        self.assertEqual(first["authors"], ["Researcher"])
        self.assertEqual(first["journal"], "JISP")
        self.assertEqual(second["abstract"], "Clinical results .")
        self.assertEqual(second["authors"], ["Trial Author"])
        self.assertEqual(second["year"], 2021)
        self.assertEqual(second["journal"], "IJDR")
        self.assertIn("/PMC123/", second["url"])
        self.assertFalse(result["partial"])

    async def test_deduplication_preserves_both_sources_and_pmc_link(self):
        def handler(request):
            payload = openalex_response() if request.url.host == "api.openalex.org" else pmc_response("10.123/TRIAL")
            return httpx.Response(200, json=payload)
        with self.transport(handler):
            result = await academic_search("trial", max_results=1)
        self.assertEqual(len(result["results"]), 1)
        self.assertEqual(result["results"][0]["sources"], ["openalex", "europepmc"])
        self.assertEqual(result["results"][0]["pmcid"], "PMC123")
        self.assertEqual(len(result["results"][0]["full_text_urls"]), 2)

    async def test_one_source_failure_keeps_other_results(self):
        def handler(request):
            if request.url.host == "api.openalex.org":
                return httpx.Response(401, json={"error": "Unavailable without a key"})
            return httpx.Response(200, json=pmc_response())
        with self.transport(handler):
            result = await academic_search("trial")
        self.assertTrue(result["partial"])
        self.assertEqual(result["sources"]["openalex"]["error"], "HTTP 401")
        self.assertEqual(len(result["results"]), 1)
        self.assertNotIn("error", result)

    async def test_transient_rate_limit_retries_once(self):
        attempts = 0
        def handler(request):
            nonlocal attempts
            if request.url.host == "api.openalex.org":
                attempts += 1
                return httpx.Response(429) if attempts == 1 else httpx.Response(200, json=openalex_response())
            return httpx.Response(200, json=pmc_response())
        with self.transport(handler), patch("tools.academic_search.asyncio.sleep", new_callable=AsyncMock) as sleep:
            result = await academic_search("trial")
        self.assertEqual(attempts, 2)
        sleep.assert_awaited_once()
        self.assertFalse(result["partial"])

    async def test_total_outage_or_malformed_payload_suggests_journal_queries(self):
        def handler(request):
            if request.url.host == "api.openalex.org":
                raise httpx.ReadTimeout("Timeout", request=request)
            return httpx.Response(200, json={"invalid": "payload"})
        with self.transport(handler):
            result = await academic_search("trial")
        self.assertEqual(result["results"], [])
        self.assertIn("error", result)
        self.assertEqual(result["sources"]["openalex"]["error"], "Timeout")
        self.assertEqual(result["sources"]["europepmc"]["error"], "Malformed response")
        self.assertIn("trial site:jcdr.net", result["suggested_web_queries"])

    async def test_empty_results_are_explicit_and_invalid_inputs_do_not_send_requests(self):
        def handler(request):
            return httpx.Response(200, json={"results": []} if request.url.host == "api.openalex.org"
                                  else {"resultList": {"result": []}})
        with self.transport(handler):
            result = await academic_search("rare trial")
        self.assertEqual(result["sources"]["openalex"]["status"], "empty")
        self.assertIn("error", result)
        for kwargs in ({"query": ""}, {"query": "x", "year_from": 9999},
                       {"query": "x", "max_results": 0}, {"query": "x", "max_results": True}):
            with self.assertRaises(ValueError):
                await academic_search(**kwargs)

    async def test_tool_registration_and_dispatch(self):
        self.assertIn("academic_search", {tool["function"]["name"] for tool in main.TOOLS})
        result = {"engine": "academic-search", "results": [{"title": "Trial"}]}
        with patch.object(main, "academic_search", new=AsyncMock(return_value=result)) as search:
            output = await main.execute_tool("academic_search", {"query": "trial"}, "gemini",
                                             {"model": "test"}, "", "test")
        search.assert_awaited_once_with("trial", 2016, 15)
        self.assertEqual(json.loads(output), result)

    async def test_pubmed_esearch_efetch_records_and_citations(self):
        esearch = """<eSearchResult><Count>1</Count><IdList><Id>123456</Id></IdList></eSearchResult>"""
        efetch = """<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>123456</PMID><Article>
          <ArticleTitle>Dental &amp; clinical trial</ArticleTitle>
          <Journal><ISSN>1234-5678</ISSN><JournalIssue><Volume>50</Volume><Issue>3</Issue>
          <PubDate><Year>2024</Year></PubDate></JournalIssue><Title>Journal of Dental Research</Title>
          <ISOAbbreviation>J Dent Res</ISOAbbreviation></Journal>
          <AuthorList><Author><LastName>Smith</LastName><ForeName>Alice B</ForeName><Initials>AB</Initials></Author>
          <Author><CollectiveName>Dental Research Group</CollectiveName></Author></AuthorList>
          <Abstract><AbstractText Label="BACKGROUND">Clinical evidence.</AbstractText>
          <AbstractText Label="RESULTS">Improvement was observed.</AbstractText></Abstract>
          <ELocationID EIdType="doi">10.1000/dental</ELocationID></Article>
          <MeshHeadingList><MeshHeading><DescriptorName>Dental Research</DescriptorName></MeshHeading></MeshHeadingList>
          </MedlineCitation><PubmedData><ArticleIdList><ArticleId IdType="pubmed">123456</ArticleId>
          <ArticleId IdType="pmc">PMC9876</ArticleId><ArticleId IdType="doi">10.1000/dental</ArticleId>
          </ArticleIdList></PubmedData></PubmedArticle></PubmedArticleSet>"""
        requests = []

        async def handler(request):
            requests.append(request)
            self.assertEqual(request.headers["User-Agent"], "Forge-PubMedSearch/1.0 (personal academic literature discovery)")
            self.assertEqual(request.url.host, "eutils.ncbi.nlm.nih.gov")
            if request.url.path.endswith("/esearch.fcgi"):
                self.assertEqual(request.url.params["db"], "pubmed")
                self.assertEqual(request.url.params["term"], "dental trial")
                self.assertEqual(request.url.params["mindate"], "2016")
                self.assertEqual(request.url.params["maxdate"], str(main.datetime.now(main.timezone.utc).year))
                self.assertEqual(request.url.params["retmax"], "15")
                return httpx.Response(200, text=esearch)
            self.assertEqual(request.url.path.endswith("/efetch.fcgi"), True)
            self.assertEqual(request.url.params["id"], "123456")
            self.assertEqual(request.url.params["retmode"], "xml")
            return httpx.Response(200, text=efetch)

        client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            headers={"User-Agent": "Forge-PubMedSearch/1.0 (personal academic literature discovery)"},
        )
        with patch("tools.academic_search.httpx.AsyncClient", return_value=client):
            result = await pubmed_search("dental trial")

        self.assertEqual(len(requests), 2)
        self.assertEqual(result["total_available"], 1)
        record = result["results"][0]
        self.assertEqual(record["pmid"], "123456")
        self.assertEqual(record["pmcid"], "PMC9876")
        self.assertEqual(record["year"], 2024)
        self.assertEqual(record["authors"], ["Smith AB", "Dental Research Group"])
        self.assertEqual(record["mesh_terms"], ["Dental Research"])
        self.assertIn("BACKGROUND: Clinical evidence.", record["abstract"])
        self.assertIn("J Dent Res. 2024;50(3)", record["vancouver_citation"])
        self.assertIn("PMID:123456", record["vancouver_citation"])
        self.assertIn("@article{Smith2024123456", record["bibtex"])
        self.assertIn(r"Dental \& clinical trial", record["bibtex"])

    async def test_pubmed_empty_and_invalid_queries_are_handled(self):
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(
                    200,
                    text="<eSearchResult><Count>0</Count><IdList /></eSearchResult>",
                )
            ),
            headers={"User-Agent": "Forge-PubMedSearch/1.0 (personal academic literature discovery)"},
        )
        with patch("tools.academic_search.httpx.AsyncClient", return_value=client):
            empty = await pubmed_search("rare dental disease")
        self.assertEqual(empty["results"], [])
        self.assertEqual(empty["sources"]["pubmed"]["status"], "empty")
        for kwargs in ({"query": ""}, {"query": "x", "max_results": 0},
                       {"query": "x", "year_from": 9999}, {"query": "x", "max_results": True}):
            with self.assertRaises(ValueError):
                await pubmed_search(**kwargs)

    async def test_pubmed_tool_is_registered_and_dispatches(self):
        self.assertIn("pubmed_search", {tool["function"]["name"] for tool in main.TOOLS})
        result = {"engine": "pubmed", "results": []}
        with patch.object(main, "pubmed_search", new=AsyncMock(return_value=result)) as search:
            output = await main.execute_tool(
                "pubmed_search", {"query": "clinical trial"}, "gemini",
                {"model": "gemini-3.8-flash"}, "", "pubmed-tool-test",
            )
        search.assert_awaited_once_with("clinical trial", 2016, 15)
        self.assertEqual(json.loads(output), result)

    async def test_targeted_domains_and_existing_site_operators_reach_search(self):
        with patch("tools.web_search.search_settings", return_value={"searchMode": "chromium",
                    "searchApiProvider": "tavily"}), patch("tools.web_search.BrowserRunner.search",
                    new_callable=AsyncMock, return_value={"results": []}) as search:
            await routed_search("periodontitis", "gemini", "model", lambda url: url,
                                domains=["jisponline.com", "jcdr.net", "ijdr.in", "pmc.ncbi.nlm.nih.gov"])
            query = search.await_args.args[0]
            for domain in ("jisponline.com", "jcdr.net", "ijdr.in", "pmc.ncbi.nlm.nih.gov"):
                self.assertIn(f"site:{domain}", query)
            await routed_search("trial site:ijdr.in", "gemini", "model", lambda url: url)
            search.assert_awaited_with("trial site:ijdr.in")
        with self.assertRaises(SearchError):
            await routed_search("trial", "gemini", "model", lambda url: url, domains=["https://ijdr.in/"])


if __name__ == "__main__":
    unittest.main()
