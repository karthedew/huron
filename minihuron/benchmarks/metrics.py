"""Serializable upload timings and capacity decisions for benchmark scenarios."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class UploadResult:
    """One complete upload attempt; latency includes service queueing."""

    user: int
    upload: int
    size_bytes: int
    seconds: float
    stage_seconds: float
    write_seconds: float
    commit_seconds: float
    error: str | None


def percentile(values: list[float], fraction: float) -> float | None:
    """Return a nearest-rank percentile, or no value for no observations.

    Args:
        values: Observed timings.
        fraction: Quantile between zero and one.

    Returns:
        The nearest-rank quantile or None.
    """
    if not values:
        return None
    return sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)]


def summarize(
    results: list[UploadResult], elapsed: float, max_p95: float, max_error_rate: float
) -> dict[str, int | float | bool | None]:
    """Aggregate successful payload throughput and all-attempt latency.

    Args:
        results: All attempted uploads in a scenario.
        elapsed: Wall time from user release until all users finish.
        max_p95: Maximum acceptable p95 end-to-end seconds.
        max_error_rate: Maximum acceptable failed fraction.

    Returns:
        Metrics and the explicit capacity acceptance decision.
    """
    successes = [result for result in results if result.error is None]
    errors = len(results) - len(successes)
    error_rate = errors / len(results) if results else 1.0
    p95 = percentile([result.seconds for result in results], 0.95)
    return {
        "attempts": len(results),
        "successes": len(successes),
        "errors": errors,
        "error_rate": error_rate,
        "elapsed_seconds": elapsed,
        "committed_bytes": sum(result.size_bytes for result in successes),
        "committed_MB_per_second": sum(result.size_bytes for result in successes) / elapsed / 1e6,
        "uploads_per_second": len(successes) / elapsed,
        "latency_p50_seconds": percentile([result.seconds for result in results], 0.50),
        "latency_p95_seconds": p95,
        "latency_p99_seconds": percentile([result.seconds for result in results], 0.99),
        "success_latency_p95_seconds": percentile([result.seconds for result in successes], 0.95),
        "passed": bool(successes)
        and error_rate <= max_error_rate
        and p95 is not None
        and p95 <= max_p95,
    }
