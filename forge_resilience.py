"""Transient-error classification and jittered backoff for provider calls.

Only failures that are likely to clear on their own are retried: HTTP 408/429/5xx,
gRPC-style UNAVAILABLE/RESOURCE_EXHAUSTED codes, and connection or timeout errors.
Client errors such as 400, 401, 403, 404, and 422 are never retried, because
repeating them cannot succeed and could repeat a bad request or leak cost.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

T = TypeVar("T")

TRANSIENT_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504, 529})
GRPC_STATUS_CODES = {
    "RESOURCE_EXHAUSTED": 429,
    "UNAVAILABLE": 503,
    "DEADLINE_EXCEEDED": 504,
    "INTERNAL": 500,
}
TRANSIENT_ERROR_CLASS_NAMES = frozenset({
    "APIConnectionError",
    "APITimeoutError",
    "RateLimitError",
    "InternalServerError",
    "ConnectError",
    "ConnectTimeout",
    "ReadTimeout",
    "WriteTimeout",
    "PoolTimeout",
    "RemoteProtocolError",
    "ServiceUnavailable",
    "ResourceExhausted",
})


def status_code_of(error: BaseException) -> int | None:
    """Return the HTTP-style status code carried by an SDK error, if any."""
    raw = (
        getattr(error, "status_code", None)
        or getattr(getattr(error, "response", None), "status_code", None)
        or getattr(error, "code", None)
    )
    if isinstance(raw, str):
        raw = GRPC_STATUS_CODES.get(raw.upper(), raw)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def is_transient_error(error: BaseException) -> bool:
    """True when retrying the same request later is reasonable."""
    status = status_code_of(error)
    if status is not None:
        return status in TRANSIENT_STATUS_CODES
    class_names = {cls.__name__ for cls in type(error).__mro__}
    if class_names & TRANSIENT_ERROR_CLASS_NAMES:
        return True
    return isinstance(error, (ConnectionError, TimeoutError))


def backoff_delay(
    attempt: int,
    *,
    base: float = 2.0,
    cap: float = 30.0,
    rng: Callable[[], float] = random.random,
) -> float:
    """Exponential backoff with jitter in [50%, 100%) of the capped delay.

    Jitter keeps many retrying clients from hitting a busy provider in lockstep.
    """
    exponential = min(cap, base * (2 ** max(0, attempt)))
    return exponential * (0.5 + rng() / 2)


async def call_with_transient_retry(
    make_call: Callable[[], Awaitable[T]],
    *,
    attempts: int = 5,
    on_retry: Callable[[str], None] | None = None,
    sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
    base: float = 2.0,
    cap: float = 30.0,
) -> T:
    """Run an async provider call, retrying only transient failures.

    The final failure is re-raised unchanged so existing error handling still applies.
    """
    if attempts < 1:
        raise ValueError("attempts must be at least 1")
    for attempt in range(attempts):
        try:
            return await make_call()
        except Exception as error:  # noqa: BLE001 - classified below
            if not is_transient_error(error) or attempt >= attempts - 1:
                raise
            delay = backoff_delay(attempt, base=base, cap=cap)
            if on_retry is not None:
                status = status_code_of(error)
                label = f"HTTP {status}" if status is not None else type(error).__name__
                on_retry(
                    f"Provider call failed ({label}); retrying attempt {attempt + 2}/{attempts} "
                    f"in {delay:.1f}s."
                )
            await sleep(delay)
    raise RuntimeError("Retry loop ended unexpectedly.")
