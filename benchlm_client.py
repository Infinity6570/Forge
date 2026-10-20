"""Small, local-first client for BenchLM's current rankings REST API."""

from __future__ import annotations

import copy
import math
import os
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

import httpx


DEFAULT_BENCHLM_ENDPOINT = "https://data.benchlm.ai/v1/rankings/current"
BENCHLM_CACHE_SECONDS = 6 * 60 * 60
BENCHLM_TIMEOUT_SECONDS = 8.0
_CACHE: dict[str, dict[str, Any]] = {}


def _number(record: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = record.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            try:
                numeric = float(value)
            except OverflowError:
                continue
            if math.isfinite(numeric):
                return numeric
        if isinstance(value, str):
            try:
                numeric = float(value.strip().replace(",", ""))
            except ValueError:
                continue
            if math.isfinite(numeric):
                return numeric
    return None


def _records(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("rankings", "results", "models", "items", "data"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            nested = _records(value)
            if nested:
                return nested
    return []


def normalize_rankings(
    payload: Any,
    *,
    surface: str,
    model_catalog: list[dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    catalog = {
        entry["modelId"]: entry
        for entry in (model_catalog or [])
        if isinstance(entry.get("modelId"), str)
    }
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in _records(payload):
        model_value = raw.get("modelId") or raw.get("model_id") or raw.get("identifier") or raw.get("id")
        model = raw.get("model")
        if not model_value and isinstance(model, str):
            model_value = model
        elif not model_value and isinstance(model, dict):
            model_value = model.get("modelId") or model.get("model_id") or model.get("identifier") or model.get("id")
        if not isinstance(model_value, str) or not model_value.strip():
            continue
        model_id = model_value.strip()
        if model_id in seen:
            continue
        seen.add(model_id)

        nested_scores = raw.get("scores") if isinstance(raw.get("scores"), dict) else {}
        nested_metrics = raw.get("metrics") if isinstance(raw.get("metrics"), dict) else {}
        score_source = {**nested_metrics, **nested_scores, **raw}
        model_details = model if isinstance(model, dict) else {}
        catalog_entry = catalog.get(model_id, {})
        rating = _number(score_source, ("rating", "score", "finalScore", "final_score", "benchAlignScore", "benchalign_score", "overallScore", "overall_score"))
        coding = _number(score_source, ("codingScore", "coding_score", "coding", "codeScore", "code_score"))
        reasoning = _number(score_source, ("reasoningScore", "reasoning_score", "reasoning"))
        knowledge = _number(score_source, ("knowledgeScore", "knowledge_score", "knowledge"))
        if surface == "coding" and coding is None:
            coding = rating
        if surface in {"knowledge", "reasoning"} and reasoning is None:
            reasoning = rating if surface == "reasoning" else None
            knowledge = rating if surface == "knowledge" else knowledge
        rank_value = raw.get("rank") or raw.get("publishedRank") or raw.get("published_rank") or raw.get("position")
        try:
            rank = int(rank_value) if rank_value is not None else None
        except (TypeError, ValueError):
            rank = None
        provider = raw.get("provider") or model_details.get("provider") or catalog_entry.get("provider")
        name = raw.get("name") or raw.get("modelName") or raw.get("model_name") or model_details.get("name") or catalog_entry.get("name") or model_id
        row: dict[str, Any] = {
            "modelId": model_id,
            "provider": provider if isinstance(provider, str) else None,
            "name": name if isinstance(name, str) else model_id,
            "surface": str(raw.get("surface") or surface),
            "rating": rating,
            "rank": rank,
            "codingScore": coding,
            "reasoningScore": reasoning,
            "knowledgeScore": knowledge,
            "costIndex": _number(score_source, ("costIndex", "cost_index", "priceIndex", "price_index", "costScore", "cost_score")),
            "latencyMs": _number(score_source, ("latencyMs", "latency_ms", "latency")),
            "tier": raw.get("tier") if isinstance(raw.get("tier"), str) else None,
        }
        output.append(row)
    return output


def _build_url(endpoint: str, surface: str) -> str:
    parts = urlsplit(endpoint)
    query = parse_qs(parts.query, keep_blank_values=True)
    query["surface"] = [surface]
    query.setdefault("limit", ["100"])
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query, doseq=True), parts.fragment))


def _fallback(
    *,
    surface: str,
    model_catalog: list[dict[str, str]] | None,
    message: str,
) -> dict[str, Any]:
    models = [
        {
            "modelId": item["modelId"],
            "provider": item.get("provider"),
            "name": item.get("name", item["modelId"]),
            "surface": surface,
            "rating": None,
            "rank": None,
            "codingScore": None,
            "reasoningScore": None,
            "knowledgeScore": None,
            "costIndex": None,
            "latencyMs": None,
            "tier": None,
        }
        for item in (model_catalog or [])
        if isinstance(item.get("modelId"), str)
    ]
    return {
        "surface": surface,
        "source": "catalog-fallback",
        "stale": False,
        "updatedAt": None,
        "message": message,
        "models": models,
    }


async def fetch_benchlm_rankings(
    *,
    surface: str = "overall",
    api_key: str | None,
    endpoint: str | None = None,
    model_catalog: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Fetch and normalize one ranking surface, retaining last-good data on outages."""
    if surface not in {"overall", "coding", "agentic", "knowledge"}:
        raise ValueError("Unsupported BenchLM ranking surface.")
    now = time.monotonic()
    cached = _CACHE.get(surface)
    if not api_key or not api_key.strip():
        if cached:
            response = copy.deepcopy(cached["response"])
            response["stale"] = True
            response["message"] = "No BenchLM key is configured; showing the last cached rankings."
            return response
        return _fallback(
            surface=surface,
            model_catalog=model_catalog,
            message="Add a BenchLM key in Preferences to load current rankings. Catalog models are shown without invented scores.",
        )
    if cached and now < cached["expiresAt"]:
        return copy.deepcopy(cached["response"])

    url = _build_url(
        (endpoint or os.getenv("BENCHLM_API_URL", DEFAULT_BENCHLM_ENDPOINT)).strip(),
        surface,
    )
    try:
        async with httpx.AsyncClient(timeout=BENCHLM_TIMEOUT_SECONDS) as client:
            response = await client.get(url, headers={"Authorization": f"Bearer {api_key.strip()}", "Accept": "application/json"})
            response.raise_for_status()
            payload = response.json()
        models = normalize_rankings(payload, surface=surface, model_catalog=model_catalog)
        if not models:
            raise ValueError("BenchLM returned no recognizable ranking rows.")
        normalized = {
            "surface": surface,
            "source": "benchlm",
            "stale": False,
            "updatedAt": datetime.now(timezone.utc).isoformat(),
            "message": None,
            "models": models,
        }
        _CACHE[surface] = {
            "expiresAt": now + BENCHLM_CACHE_SECONDS,
            "response": copy.deepcopy(normalized),
        }
        return normalized
    except (httpx.HTTPError, ValueError, TypeError):
        if cached:
            fallback_response = copy.deepcopy(cached["response"])
            fallback_response["stale"] = True
            fallback_response["message"] = "BenchLM could not be reached; showing the last successful rankings."
            return fallback_response
        return _fallback(
            surface=surface,
            model_catalog=model_catalog,
            message="BenchLM rankings are unavailable. Catalog models are shown without invented scores.",
        )


def cached_rankings(surface: str) -> dict[str, Any] | None:
    cached = _CACHE.get(surface)
    return copy.deepcopy(cached["response"]) if cached else None


def clear_benchlm_cache() -> None:
    _CACHE.clear()

