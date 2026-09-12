from __future__ import annotations

import math
import random
from collections.abc import Sequence


def holm_bonferroni_adjust(p_values: Sequence[float]) -> list[float]:
    """Return Holm step-down adjusted p-values in the original order."""
    if not p_values:
        raise ValueError("At least one p-value is required")
    values = [float(value) for value in p_values]
    if any(not math.isfinite(value) or not 0.0 <= value <= 1.0 for value in values):
        raise ValueError("p-values must be finite numbers in [0, 1]")
    order = sorted(range(len(values)), key=lambda index: (values[index], index))
    adjusted = [0.0] * len(values)
    running_max = 0.0
    count = len(values)
    for rank, index in enumerate(order):
        running_max = max(running_max, (count - rank) * values[index])
        adjusted[index] = min(1.0, running_max)
    return adjusted


def _validate_pairs(system: Sequence[bool], baseline: Sequence[bool]) -> None:
    if not system or not baseline or len(system) != len(baseline):
        raise ValueError("Paired labels must be nonempty and have equal length")


def _proportion_ci(successes: int, total: int, z: float) -> tuple[float, float]:
    p = successes / total
    denominator = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denominator
    margin = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return max(0.0, centre - margin), min(1.0, centre + margin)


def _binomial_two_sided_pvalue(successes: int, trials: int) -> float:
    """Exact two-sided McNemar p-value for discordant pairs."""
    if trials == 0:
        return 1.0
    probability = sum(math.comb(trials, k) for k in range(successes + 1)) / (2**trials)
    observed_tail = min(successes, trials - successes)
    pvalue = 2 * sum(math.comb(trials, k) for k in range(observed_tail + 1)) / (2**trials)
    return min(1.0, pvalue)


def paired_binary_summary(
    system: Sequence[bool],
    baseline: Sequence[bool],
    *,
    confidence: float = 0.95,
    bootstrap_iterations: int = 10_000,
    seed: int = 0,
) -> dict[str, object]:
    """Summarize paired binary labels without treating them as semantic labels.

    Callers must supply labels produced by a predeclared review rubric. The
    function only computes the paired statistics; it does not infer whether a
    label means correctness, safety, or another outcome.
    """
    _validate_pairs(system, baseline)
    if not 0 < confidence < 1 or bootstrap_iterations < 1:
        raise ValueError("Invalid confidence or bootstrap_iterations")
    n = len(system)
    system_successes = sum(bool(value) for value in system)
    baseline_successes = sum(bool(value) for value in baseline)
    both_success = sum(a and b for a, b in zip(system, baseline, strict=True))
    system_only = sum(a and not b for a, b in zip(system, baseline, strict=True))
    baseline_only = sum((not a) and b for a, b in zip(system, baseline, strict=True))
    discordant = system_only + baseline_only
    observed_difference = (system_successes - baseline_successes) / n
    rng = random.Random(seed)
    pairs = list(zip(system, baseline, strict=True))
    bootstrap_differences: list[float] = []
    for _ in range(bootstrap_iterations):
        sample = [pairs[rng.randrange(n)] for _ in range(n)]
        bootstrap_differences.append(
            (sum(a for a, _ in sample) - sum(b for _, b in sample)) / n
        )
    bootstrap_differences.sort()
    alpha = (1 - confidence) / 2
    lower_index = max(0, min(bootstrap_iterations - 1, math.floor(alpha * bootstrap_iterations)))
    upper_index = max(0, min(bootstrap_iterations - 1, math.ceil((1 - alpha) * bootstrap_iterations) - 1))
    z = 1.959963984540054
    return {
        "label_semantics": "caller_defined_binary_review_outcome",
        "question_count": n,
        "system_success_count": system_successes,
        "baseline_success_count": baseline_successes,
        "system_rate": round(system_successes / n, 6),
        "baseline_rate": round(baseline_successes / n, 6),
        "rate_difference_system_minus_baseline": round(observed_difference, 6),
        "rate_difference_bootstrap_ci": [
            round(bootstrap_differences[lower_index], 6),
            round(bootstrap_differences[upper_index], 6),
        ],
        "system_only_discordant": system_only,
        "baseline_only_discordant": baseline_only,
        "both_success": both_success,
        "discordant_pair_count": discordant,
        "mcnemar_exact_two_sided_pvalue": round(
            _binomial_two_sided_pvalue(system_only, discordant), 6
        ),
        "confidence": confidence,
        "bootstrap_iterations": bootstrap_iterations,
        "bootstrap_seed": seed,
    }
