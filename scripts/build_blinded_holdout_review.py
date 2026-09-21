"""Build a blinded two-arm human-review packet from an external holdout run.

The question file and run report may live outside the public repository.  The
generated packet deliberately omits standard answers and arm identities; keep
the identity map separate until independent ratings and adjudication finish.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import hmac
import secrets
from pathlib import Path
from typing import Any

from adc_evidence.evaluation.holdout import holdout_manifest


ARM_NAMES = ("adc_evidence", "offline_rag_baseline")
REVIEW_SLOTS = ("primary", "secondary")


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _file_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip()
    ]
    if not rows or any(not isinstance(row, dict) for row in rows):
        raise ValueError("Question file must contain at least one JSON object per line")
    return rows


def _blank_review(candidate_id: str, question_id: str, blind_arm: str, slot: str) -> dict[str, Any]:
    return {
        "candidate_id": candidate_id,
        "question_id": question_id,
        "blind_arm": blind_arm,
        "reviewer_slot": slot,
        "review_origin": None,
        "answer_verdict": None,
        "evidence_verdict": None,
        "citation_verdict": None,
        "completeness_verdict": None,
        "refusal_verdict": None,
        "severity": None,
        "error_categories": [],
        "notes": None,
    }


def _candidate_output(source: dict[str, Any]) -> dict[str, Any]:
    """Keep review-relevant output while excluding run metadata and gold fields."""
    return {
        "status": source.get("status"),
        "answer": source.get("answer"),
        "claims": [
            {key: claim.get(key) for key in ("text", "citation_ids")}
            for claim in source.get("claims", [])
        ],
        "citations": [
            {key: citation.get(key) for key in ("citation_id", "title", "source_url", "excerpt")}
            for citation in source.get("citations", [])
        ],
    }


def build_blinded_packet(
    questions: list[dict[str, Any]],
    run: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    """Return packet, private identity map, and blank review rows."""
    if not questions or any(not isinstance(row, dict) for row in questions):
        raise ValueError("Question set must not be empty")
    question_ids = [row.get("question_id") for row in questions]
    if any(not isinstance(qid, str) or not qid.strip() or qid != qid.strip() for qid in question_ids):
        raise ValueError("Question IDs must be nonempty")
    if len(question_ids) != len(set(question_ids)):
        raise ValueError("Question IDs must be unique")

    if not isinstance(run, dict):
        raise ValueError("Run report must be an object")
    for question in questions:
        if not isinstance(question.get("question"), str) or not question["question"].strip():
            raise ValueError("Question text must be nonempty")
    # run_public_holdout loads these defaults before hashing. Do not alter the
    # frozen file or ignore any other content when checking report binding.
    normalized = [dict(row) for row in questions]
    for row in normalized:
        row.setdefault("split", "holdout")
        row.setdefault("evaluation_use", "public_smoke_holdout")
    expected = holdout_manifest(normalized)
    for field in ("question_set_hash", "question_id_sha256", "question_count"):
        if run.get(field) != expected[field]:
            raise ValueError(f"Run report disagrees with question file: {field}")
    arms = run.get("arms")
    if not isinstance(arms, dict) or set(arms) != set(ARM_NAMES):
        raise ValueError(f"Run report must contain exactly {list(ARM_NAMES)} arms")
    for field in ("evaluation_window_id", "question_set_hash", "question_id_sha256"):
        if not isinstance(run.get(field), str) or not run[field].strip():
            raise ValueError(f"Run report needs nonempty {field}")

    by_arm: dict[str, dict[str, dict[str, Any]]] = {}
    for arm in ARM_NAMES:
        report = arms[arm]
        if not isinstance(report, dict):
            raise ValueError(f"Arm report must be an object: {arm}")
        rows = report.get("questions")
        if not isinstance(rows, list):
            raise ValueError(f"Arm report needs a questions list: {arm}")
        observed = {str(row.get("question_id", "")): row for row in rows if isinstance(row, dict)}
        if len(rows) != len(question_ids) or len(observed) != len(rows) or set(observed) != set(question_ids):
            raise ValueError(f"{arm} must contain exactly the frozen question IDs")
        for row in rows:
            if row.get("status") not in {"answered", "partial", "refused", "error"} or not isinstance(row.get("answer"), str):
                raise ValueError("Each output needs a valid status and answer text")
            for field in ("claims", "citations"):
                items = row.get(field, [])
                if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
                    raise ValueError(f"Output {field} must be a list of objects")
        by_arm[arm] = observed

    packet_questions: list[dict[str, Any]] = []
    identity_rows: list[dict[str, Any]] = []
    review_rows: list[dict[str, Any]] = []
    # Preserve this key only in the coordinator's identity file. Public hashes
    # and the released source must not suffice to recover A/B assignments.
    blinding_key = secrets.token_hex(32)
    for question in questions:
        question_id = str(question["question_id"])
        ordered_arms = sorted(
            ARM_NAMES,
            key=lambda arm: hmac.new(bytes.fromhex(blinding_key), _canonical({
                "question_set_hash": run["question_set_hash"],
                "question_id": question_id,
                "arm": arm,
            }).encode("utf-8"), hashlib.sha256).hexdigest(),
        )
        candidates: list[dict[str, Any]] = []
        for index, arm in enumerate(ordered_arms):
            blind_arm = chr(ord("A") + index)
            candidate_id = f"{question_id}:{blind_arm}"
            candidates.append({
                "candidate_id": candidate_id,
                "blind_arm": blind_arm,
                "output": _candidate_output(by_arm[arm][question_id]),
            })
            identity_rows.append({
                "candidate_id": candidate_id,
                "question_id": question_id,
                "blind_arm": blind_arm,
                "arm": arm,
                "model": arms[arm].get("model"),
                "arm_run_id": arms[arm].get("run_id"),
                "output_hash": by_arm[arm][question_id].get("output_hash"),
            })
            review_rows.extend(
                _blank_review(candidate_id, question_id, blind_arm, slot)
                for slot in REVIEW_SLOTS
            )

        # Only source type and URL are carried into the packet.  Gold values,
        # source record IDs, and scoring metadata stay in the frozen question file.
        reference_sources = [
            {
                "source_type": source.get("source_type"),
                "source_url": source.get("source_url"),
            }
            for source in question.get("evidence_sources", [])
            if isinstance(source, dict)
        ]
        packet_questions.append({
            "question_id": question_id,
            "question": question.get("question"),
            "category": question.get("category"),
            "reference_sources": reference_sources,
            "candidates": candidates,
        })

    identity = {
        "schema_version": "v0.6-two-arm-blind-identity-map-v1",
        "evaluation_window_id": run["evaluation_window_id"],
        "question_set_hash": run["question_set_hash"],
        "question_id_sha256": run["question_id_sha256"],
        "mapping": identity_rows,
        "blinding_key": blinding_key,
        "assignment_method": "hmac-sha256-private-key-v1",
    }
    mapping_hash = _digest(identity)
    identity["mapping_hash"] = mapping_hash
    packet = {
        "schema_version": "v0.6-two-arm-blinded-review-packet-v1",
        "evaluation_window_id": run["evaluation_window_id"],
        "question_set_hash": run["question_set_hash"],
        "question_id_sha256": run["question_id_sha256"],
        "question_count": len(packet_questions),
        "candidate_count": len(identity_rows),
        "blinded": True,
        "blinding_limit": "Answer style and source content may still suggest method identity.",
        "mapping_hash": mapping_hash,
        "identity_disclosure_rule": (
            "Keep the identity map separate until both independent ratings are saved "
            "and disagreements are adjudicated."
        ),
        "questions": packet_questions,
    }
    return packet, identity, review_rows


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def validate_output_paths(inputs: list[Path], outputs: list[Path], repo_root: Path) -> None:
    resolved = [path.resolve() for path in outputs]
    if len(set(resolved)) != len(resolved):
        raise ValueError("Output paths must be distinct")
    for path in resolved:
        if path in {item.resolve() for item in inputs}:
            raise ValueError("Output must not overwrite an input")
        if path.is_relative_to(repo_root.resolve()):
            raise ValueError("Review artifacts must stay outside the public repository")
        if path.exists():
            raise ValueError("Output already exists; choose a new review packet directory")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--questions", type=Path, required=True)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--identity-map", type=Path, required=True)
    parser.add_argument("--reviews", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()

    validate_output_paths(
        [args.questions, args.run],
        [args.packet, args.identity_map, args.reviews, args.manifest],
        Path(__file__).resolve().parents[1],
    )

    questions = _read_jsonl(args.questions)
    run = json.loads(args.run.read_text(encoding="utf-8-sig"))
    packet, identity, review_rows = build_blinded_packet(questions, run)
    _write_json(args.packet, packet)
    _write_json(args.identity_map, identity)
    args.reviews.parent.mkdir(parents=True, exist_ok=True)
    with args.reviews.open("x", encoding="utf-8") as handle:
        handle.write("".join(_canonical(row) + "\n" for row in review_rows))
    manifest = {
        "schema_version": "v0.6-two-arm-review-manifest-v1",
        "status": "awaiting_independent_human_review",
        "question_count": packet["question_count"],
        "candidate_count": packet["candidate_count"],
        "required_review_count": len(review_rows),
        "independent_reviewers_per_candidate": len(REVIEW_SLOTS),
        "questions_sha256": _file_digest(args.questions),
        "run_sha256": _file_digest(args.run),
        "packet_sha256": _file_digest(args.packet),
        "identity_map_sha256": _file_digest(args.identity_map),
        "review_template_sha256": _file_digest(args.reviews),
        "mapping_hash": identity["mapping_hash"],
        "human_review_required": True,
        "ai_assisted_labels_accepted": False,
        "evaluation_use": run.get("evaluation_use"),
        "readiness_note": (
            "Packet preparation validates question binding, not unseen-test independence, "
            "gold validity, source licensing, or matched execution conditions."
        ),
    }
    _write_json(args.manifest, manifest)
    print(json.dumps({key: manifest[key] for key in (
        "status", "question_count", "candidate_count", "required_review_count"
    )}))


if __name__ == "__main__":
    main()
