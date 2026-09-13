"""Validation and deterministic scoring for the public ADC benchmark format."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Iterable
from pathlib import Path

from adc_evidence.evaluation.statistics import paired_binary_summary


PUBLIC_BENCHMARK_SCHEMA_VERSION = "public-adc-benchmark-v1"
VALID_CATEGORIES = {
    "structured_fact",
    "comparison",
    "trial_lookup",
    "literature_evidence",
    "safety_refusal",
}
VALID_SPLITS = {"dev", "public_smoke"}
VALID_REVIEW_STATUSES = {"pending", "complete"}


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def load_public_benchmark(path: Path) -> list[dict[str, object]]:
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip()
    ]
    if not rows:
        raise ValueError("Public benchmark must not be empty")
    ids = [str(row.get("question_id", "")).strip() for row in rows]
    if any(not item for item in ids) or len(ids) != len(set(ids)):
        raise ValueError("Public benchmark needs unique nonempty question_id values")
    for row in rows:
        required = {
            "question_id", "split", "category", "question", "expected_route",
            "expected_status", "standard_answer", "allowed_answers",
            "evidence_sources", "allow_partial", "should_refuse",
            "human_scoring", "scoring",
        }
        missing = sorted(required - set(row))
        if missing:
            raise ValueError(f"{row.get('question_id')}: missing fields {missing}")
        if row["split"] not in VALID_SPLITS:
            raise ValueError(f"{row['question_id']}: invalid split")
        if row["category"] not in VALID_CATEGORIES:
            raise ValueError(f"{row['question_id']}: invalid category")
        if not isinstance(row["question"], str) or not row["question"].strip():
            raise ValueError(f"{row['question_id']}: question must be nonempty")
        if row["expected_route"] not in {
            "structured_fact", "comparison", "trial_lookup", "literature_evidence", "refusal"
        }:
            raise ValueError(f"{row['question_id']}: invalid expected_route")
        statuses = row["expected_status"]
        if not isinstance(statuses, list) or not statuses:
            raise ValueError(f"{row['question_id']}: expected_status must be nonempty list")
        if bool(row["should_refuse"]) != (row["expected_route"] == "refusal"):
            raise ValueError(f"{row['question_id']}: refusal route/status mismatch")
        if not isinstance(row["evidence_sources"], list):
            raise ValueError(f"{row['question_id']}: evidence_sources must be a list")
        review = row["human_scoring"]
        if not isinstance(review, dict) or review.get("status") not in VALID_REVIEW_STATUSES:
            raise ValueError(f"{row['question_id']}: invalid human_scoring status")
        if review.get("status") == "pending" and any(
            review.get(key) is not None for key in ("primary", "secondary", "adjudicated")
        ):
            raise ValueError(f"{row['question_id']}: pending review cannot contain scores")
        if not isinstance(row["scoring"], dict) or not row["scoring"].get("primary_metric"):
            raise ValueError(f"{row['question_id']}: scoring.primary_metric is required")
    return rows


def benchmark_manifest(
    rows: list[dict[str, object]],
    *,
    catalog_sha256: str,
    database_data_version: dict[str, object] | None,
    requested_as_of: str,
) -> dict[str, object]:
    if not rows:
        raise ValueError("Cannot build a manifest for an empty benchmark")
    categories = Counter(str(row["category"]) for row in rows)
    splits = Counter(str(row["split"]) for row in rows)
    return {
        "schema_version": PUBLIC_BENCHMARK_SCHEMA_VERSION,
        "benchmark_id": "adc-public-benchmark-v1",
        "requested_database_as_of": requested_as_of,
        "question_count": len(rows),
        "split_counts": dict(sorted(splits.items())),
        "category_counts": dict(sorted(categories.items())),
        "question_set_sha256": f"sha256:{_sha256(rows)}",
        "catalog_sha256": catalog_sha256,
        "database_data_version": database_data_version,
        "evaluation_use": {
            "status": "development_exposed",
            "eligible_for_unseen_test_claim": False,
            "reason": "Questions and answers are distributed for reproducible development and smoke checks.",
            "confirmation_requires": "A separately frozen access-controlled question set with independent human review.",
        },
        "human_review": {
            "status": "pending",
            "required_roles": ["primary_independent", "secondary_independent", "adjudicator_if_disagreement"],
            "ai_assisted_review_counts_as": "not_independent_human_review",
        },
        "metrics": {
            "route_accuracy": "expected_route == system.route",
            "status_coverage": "system.status is in expected_status",
            "answer_field_accuracy": "mean answer credit; fractional credit is used only when allow_partial=true",
            "answer_exact_accuracy": "proportion of questions whose required answer fields are all correct",
            "evidence_recall": "intersection(system cited source IDs, evidence_sources) is nonempty when evidence is required",
            "refusal_precision_recall": "binary refusal correctness on safety_refusal and insufficient-evidence items",
            "human_primary_endpoint": "independent reviewer answer and evidence verdicts; report paired difference with 95% CI",
        },
        "evidence_acceptance_policy": {
            "literature_public_smoke": "Any listed directly linked PubMed candidate is accepted for the natural-language 'a relevant paper' questions.",
            "candidate_cap_per_question": 50,
            "strict_test_requirement": "Replace the candidate set with a human-curated answer set for publication claims.",
        },
    }


def _source_ids(row: dict[str, object]) -> set[str]:
    return {
        str(source.get("source_record_id"))
        for source in row.get("evidence_sources", [])
        if isinstance(source, dict) and source.get("source_record_id")
    }


def _source_id_matches(actual: object, expected: object) -> bool:
    left = str(actual).strip().casefold()
    right = str(expected).strip().casefold()
    if left == right:
        return True
    # PubMed retrieval documents commonly use a bare PMID while benchmark
    # provenance uses the explicit ``pubmed:`` namespace.
    return left.removeprefix("pubmed:") == right.removeprefix("pubmed:")


def _value_matches(actual: object, expected: object, allowed: list[object]) -> bool:
    """Compare scalar/list answer values while preserving the benchmark's aliases."""
    if isinstance(actual, list) and isinstance(expected, list):
        return [str(item).strip().casefold() for item in actual] == [
            str(item).strip().casefold() for item in expected
        ]
    candidates = [expected, *allowed]
    if isinstance(actual, list):
        return any(_value_matches(item, candidate, []) for item in actual for candidate in candidates)
    actual_text = str(actual).strip().casefold()
    return any(actual_text == str(candidate).strip().casefold() for candidate in candidates)


def _answer_field_hit(gold: dict[str, object], output: dict[str, object]) -> float:
    """Score answer content from serialized atomic claims, independently of prose wording."""
    standard = gold.get("standard_answer")
    if not isinstance(standard, dict):
        return float(bool(output.get("status") == "refused") == bool(gold.get("should_refuse")))
    claims = output.get("claims", [])
    if not isinstance(claims, list):
        return 0.0
    kind = standard.get("kind")
    if kind == "structured":
        field = str(standard.get("field", ""))
        expected = standard.get("value")
        allowed = gold.get("allowed_answers", [])
        return float(any(
            isinstance(claim, dict)
            and str(claim.get("predicate", "")).endswith(f".{field}")
            and _value_matches(claim.get("value"), expected, allowed if isinstance(allowed, list) else [])
            for claim in claims
        ))
    if kind == "comparison":
        values = standard.get("values")
        if not isinstance(values, dict) or not values:
            return 0.0
        matched = 0
        for subject_id, expected in values.items():
            field = str(standard.get("field", ""))
            if any(
                isinstance(claim, dict)
                and str(claim.get("subject_id")) == str(subject_id)
                and str(claim.get("predicate", "")).endswith(f".{field}")
                and _value_matches(claim.get("value"), expected, [])
                for claim in claims
            ):
                matched += 1
        return matched / len(values)
    if kind == "trial_record":
        fields = standard.get("fields")
        if not isinstance(fields, dict):
            return 0.0
        matched = sum(any(
            isinstance(claim, dict)
            and str(claim.get("subject_id")) == str(fields.get("nct_id"))
            and str(claim.get("predicate", "")).endswith(f".{field}")
            and _value_matches(claim.get("value"), expected, [])
            for claim in claims
        ) for field, expected in fields.items())
        return matched / len(fields)
    if kind == "evidence_document":
        document_id = str(standard.get("document_id", ""))
        accepted = [document_id, *(
            str(item) for item in gold.get("allowed_answers", [])
            if isinstance(item, (str, int, float))
        )]
        return float(any(
            _source_id_matches(item, candidate)
            for item in output.get("citation_source_record_ids", [])
            for candidate in accepted
        ))
    if kind == "refusal":
        return float(output.get("status") == "refused")
    return 0.0


def _answer_score(gold: dict[str, object], output: dict[str, object]) -> float:
    """Apply the row's partial-answer policy to the raw field score."""
    raw = _answer_field_hit(gold, output)
    if bool(gold.get("allow_partial")):
        return raw
    return float(raw >= 1.0)


def score_public_benchmark(
    system_rows: Iterable[dict[str, object]],
    benchmark_rows: list[dict[str, object]],
) -> dict[str, object]:
    expected = {str(row["question_id"]): row for row in benchmark_rows}
    observed = {str(row.get("question_id", "")): row for row in system_rows}
    if set(observed) != set(expected):
        raise ValueError("System output IDs must exactly match the benchmark IDs")
    route_hits = status_hits = answer_exact_hits = evidence_hits = refusal_hits = 0
    answer_scores = 0.0
    category_totals: Counter[str] = Counter()
    category_hits: dict[str, Counter[str]] = {}
    for question_id, gold in expected.items():
        output = observed[question_id]
        category = str(gold["category"])
        category_totals[category] += 1
        hits = category_hits.setdefault(category, Counter())
        route_hit = int(output.get("route") == gold["expected_route"])
        route_hits += route_hit
        hits["route"] += route_hit
        statuses = gold["expected_status"]
        status_hit = int(output.get("status") in statuses)
        status_hits += status_hit
        hits["status"] += status_hit
        answer_score = _answer_score(gold, output)
        answer_scores += answer_score
        answer_exact_hit = int(answer_score >= 1.0)
        answer_exact_hits += answer_exact_hit
        hits["answer"] += answer_score
        hits["answer_exact"] += answer_exact_hit
        if gold["evidence_sources"]:
            cited = output.get("citation_source_record_ids", [])
            evidence_hit = int(any(
                _source_id_matches(actual, expected)
                for actual in cited
                for expected in _source_ids(gold)
            ))
            evidence_hits += evidence_hit
        else:
            evidence_hit = 1
            evidence_hits += 1
        hits["evidence"] += evidence_hit
        refusal_hit = int(bool(output.get("status") == "refused") == bool(gold["should_refuse"]))
        refusal_hits += refusal_hit
        hits["refusal"] += refusal_hit
    total = len(expected)
    by_category = {
        category: {
            "question_count": category_totals[category],
            "route_accuracy": values["route"] / category_totals[category],
            "status_coverage": values["status"] / category_totals[category],
            "answer_field_accuracy": values["answer"] / category_totals[category],
            "answer_exact_accuracy": values["answer_exact"] / category_totals[category],
            "evidence_recall": values["evidence"] / category_totals[category],
            "refusal_correctness": values["refusal"] / category_totals[category],
        }
        for category, values in sorted(category_hits.items())
    }
    return {
        "question_count": total,
        "route_accuracy": route_hits / total,
        "status_coverage": status_hits / total,
        "answer_field_accuracy": answer_scores / total,
        "answer_exact_accuracy": answer_exact_hits / total,
        "evidence_recall": evidence_hits / total,
        "refusal_correctness": refusal_hits / total,
        "by_category": by_category,
        "scoring_mode": "automatic_diagnostics_only",
        "human_review_required": True,
    }


def compare_public_benchmark_reports(
    system_rows: Iterable[dict[str, object]],
    baseline_rows: Iterable[dict[str, object]],
    benchmark_rows: list[dict[str, object]],
) -> dict[str, object]:
    """Compute paired diagnostic differences for two public benchmark arms."""
    expected = {str(row["question_id"]): row for row in benchmark_rows}
    system = {str(row.get("question_id", "")): row for row in system_rows}
    baseline = {str(row.get("question_id", "")): row for row in baseline_rows}
    if set(system) != set(expected) or set(baseline) != set(expected):
        raise ValueError("Both reports must contain exactly the benchmark question IDs")

    def metrics(gold: dict[str, object], output: dict[str, object]) -> dict[str, bool]:
        cited = output.get("citation_source_record_ids", [])
        evidence = not gold["evidence_sources"] or any(
            _source_id_matches(actual, expected_id)
            for actual in cited
            for expected_id in _source_ids(gold)
        )
        return {
            "route": output.get("route") == gold["expected_route"],
            "status": output.get("status") in gold["expected_status"],
            "answer": _answer_score(gold, output) >= 1.0,
            "evidence": evidence,
            "refusal": bool(output.get("status") == "refused") == bool(gold["should_refuse"]),
        }

    def summarize(ids: list[str]) -> dict[str, object]:
        result: dict[str, object] = {}
        for metric in ("route", "status", "answer", "evidence", "refusal"):
            system_hits = sum(metrics(expected[qid], system[qid])[metric] for qid in ids)
            baseline_hits = sum(metrics(expected[qid], baseline[qid])[metric] for qid in ids)
            result[metric] = {
                "question_count": len(ids),
                "system_rate": system_hits / len(ids),
                "baseline_rate": baseline_hits / len(ids),
                "difference": (system_hits - baseline_hits) / len(ids),
                "system_only": sum(
                    metrics(expected[qid], system[qid])[metric]
                    and not metrics(expected[qid], baseline[qid])[metric]
                    for qid in ids
                ),
                "baseline_only": sum(
                    metrics(expected[qid], baseline[qid])[metric]
                    and not metrics(expected[qid], system[qid])[metric]
                    for qid in ids
                ),
                "paired_statistics": paired_binary_summary(
                    [metrics(expected[qid], system[qid])[metric] for qid in ids],
                    [metrics(expected[qid], baseline[qid])[metric] for qid in ids],
                    bootstrap_iterations=2000,
                    seed=0,
                ),
            }
        return result

    all_ids = sorted(expected)
    by_category: dict[str, list[str]] = {}
    for row in benchmark_rows:
        by_category.setdefault(str(row["category"]), []).append(str(row["question_id"]))
    return {
        "schema_version": "public-adc-benchmark-comparison-v1",
        "question_count": len(all_ids),
        "system_variant": "adc_evidence_public",
        "baseline_variant": "offline_rag_baseline",
        "paired_metrics": summarize(all_ids),
        "by_category": {
            category: summarize(sorted(ids))
            for category, ids in sorted(by_category.items())
        },
        "human_review_required": True,
        "method_note": "Automatic paired diagnostics only; semantic correctness and publication claims require independent human review on a hidden holdout.",
    }
