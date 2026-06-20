"""In-process runtime metrics for the MCP tool surface (observability).

``run_mcp_tool`` records each call's latency and outcome here; ``get_diagnostics``
surfaces a compact snapshot (request/error counts + latency percentiles) alongside
the build/data provenance. The latency window is bounded so memory stays constant,
and the collector is process-local (reset on restart, and in tests).
"""

from __future__ import annotations

import math
import threading
from collections import deque
from typing import Any

#: Rolling latency window. Percentiles are computed over the most recent calls;
#: counters (requests/errors) are cumulative for the process lifetime.
_MAX_SAMPLES = 1024

#: Minimum request count before ``error_rate`` is reported. Below this the ratio is
#: withheld (``None``): an error or two over a handful of calls reads as alarming
#: noise rather than signal. Raw ``requests``/``errors`` counts are always reported.
_ERROR_RATE_MIN_SAMPLE = 20


def _percentile(sorted_vals: list[int], q: float) -> int:
    """Nearest-rank percentile of a pre-sorted list (0 for an empty window)."""
    if not sorted_vals:
        return 0
    rank = max(0, math.ceil(q / 100 * len(sorted_vals)) - 1)
    return sorted_vals[min(rank, len(sorted_vals) - 1)]


class _Metrics:
    """Thread-safe counters + a bounded latency window."""

    def __init__(self) -> None:
        """Initialise empty counters, latency window, and per-tool tallies."""
        self._lock = threading.Lock()
        self._latencies: deque[int] = deque(maxlen=_MAX_SAMPLES)
        self._requests = 0
        self._errors = 0
        self._per_tool: dict[str, dict[str, Any]] = {}
        #: Global response_mode histogram (surfaces over-fetch: are agents asking for
        #: standard/full when compact would do?). Per-tool counts live in ``_per_tool``.
        self._response_modes: dict[str, int] = {}
        #: Version-hash cache (capabilities_version / data_version) hit/miss tallies,
        #: global and per cache name.
        self._cache_hits = 0
        self._cache_misses = 0
        self._cache_by_name: dict[str, dict[str, int]] = {}

    def record(
        self, tool: str, elapsed_ms: int, *, ok: bool, response_mode: str | None = None
    ) -> None:
        """Record one tool call's latency, outcome, and (optional) response_mode."""
        with self._lock:
            self._requests += 1
            self._latencies.append(max(0, int(elapsed_ms)))
            tally = self._per_tool.setdefault(tool, {"requests": 0, "errors": 0, "modes": {}})
            tally["requests"] += 1
            if not ok:
                self._errors += 1
                tally["errors"] += 1
            if response_mode:
                self._response_modes[response_mode] = self._response_modes.get(response_mode, 0) + 1
                modes: dict[str, int] = tally["modes"]
                modes[response_mode] = modes.get(response_mode, 0) + 1

    def record_cache(self, name: str, *, hit: bool) -> None:
        """Record one cache lookup outcome (hit/miss), globally and for ``name``."""
        with self._lock:
            by_name = self._cache_by_name.setdefault(name, {"hits": 0, "misses": 0})
            if hit:
                self._cache_hits += 1
                by_name["hits"] += 1
            else:
                self._cache_misses += 1
                by_name["misses"] += 1

    def snapshot(self) -> dict[str, Any]:
        """Return a compact, JSON-safe view of current runtime behaviour."""
        with self._lock:
            requests = self._requests
            errors = self._errors
            samples = sorted(self._latencies)
            per_tool = {
                k: {**v, "modes": dict(v["modes"])} for k, v in sorted(self._per_tool.items())
            }
            response_modes = dict(sorted(self._response_modes.items()))
            cache_hits = self._cache_hits
            cache_misses = self._cache_misses
            cache_by_name = {k: dict(v) for k, v in sorted(self._cache_by_name.items())}
        report_rate = requests >= _ERROR_RATE_MIN_SAMPLE
        cache_total = cache_hits + cache_misses
        return {
            "requests": requests,
            "errors": errors,
            "error_rate": round(errors / requests, 4) if report_rate else None,
            "latency_ms": {
                "p50": _percentile(samples, 50),
                "p95": _percentile(samples, 95),
                "p99": _percentile(samples, 99),
                "max": samples[-1] if samples else 0,
                "sampled": len(samples),
            },
            "response_modes": response_modes,
            "cache": {
                "hits": cache_hits,
                "misses": cache_misses,
                "hit_ratio": round(cache_hits / cache_total, 4) if cache_total else None,
                "by_name": cache_by_name,
            },
            "per_tool": per_tool,
        }

    def reset(self) -> None:
        """Clear all counters and the latency window (test/process boundary)."""
        with self._lock:
            self._latencies.clear()
            self._requests = 0
            self._errors = 0
            self._per_tool.clear()
            self._response_modes.clear()
            self._cache_hits = 0
            self._cache_misses = 0
            self._cache_by_name.clear()


_METRICS = _Metrics()


def record(tool: str, elapsed_ms: int, *, ok: bool, response_mode: str | None = None) -> None:
    """Record one tool call into the process-wide collector."""
    _METRICS.record(tool, elapsed_ms, ok=ok, response_mode=response_mode)


def record_cache(name: str, *, hit: bool) -> None:
    """Record one version-hash cache lookup into the process-wide collector."""
    _METRICS.record_cache(name, hit=hit)


def snapshot() -> dict[str, Any]:
    """Return the process-wide runtime snapshot."""
    return _METRICS.snapshot()


def reset() -> None:
    """Reset the process-wide collector."""
    _METRICS.reset()
