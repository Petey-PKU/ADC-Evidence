from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from adc_evidence.config import (
    BAD_CASE_MARKDOWN_PATH,
    BAD_CASE_REPORT_PATH,
    DEFAULT_DATABASE_PATH,
    GENERATION_REPORT_PATH,
    RETRIEVAL_REPORT_PATH,
)
from adc_evidence.review.repository import all_expert_reviews


def _automatic_generation_cases(report: dict[str, Any]) -> list[dict[str, object]]:
    cases: list[dict[str, object]] = []
    run_id = str(report.get("run_id") or "")
    for row in report.get("questions", []):
        categories: list[str] = []
        should_refuse = bool(row.get("should_refuse"))
        status = str(row.get("status", "unknown"))
        if status == "error":
            categories.append("system_error")
        if not should_refuse and status == "refused":
            categories.append("over_refusal")
        if should_refuse and status == "answered":
            categories.append("under_refusal")
        if not should_refuse and status == "answered":
            if not bool(row.get("citation_valid")):
                categories.append("invalid_citation")
            if row.get("expected_document_ids") and not bool(row.get("gold_citation_hit")):
                categories.append("wrong_source")
            if float(row.get("key_fact_recall", 0.0)) < 1.0:
                categories.append("missing_key_fact")
        if categories:
            cases.append(
                {
                    "item_id": (
                        f"generation:{run_id}:{row['question_id']}"
                        if run_id
                        else f"generation:{row['question_id']}"
                    ),
                    "item_type": "generation",
                    "evaluation_run_id": run_id or "legacy",
                    "question_id": row["question_id"],
                    "question": row["question"],
                    "categories": categories,
                    "severity": "high" if "system_error" in categories else "medium",
                    "detection_source": "automatic_rule",
                    "details": {
                        "status": status,
                        "key_fact_recall": row.get("key_fact_recall"),
                        "citation_valid": row.get("citation_valid"),
                        "gold_citation_hit": row.get("gold_citation_hit"),
                        "expected_document_ids": row.get("expected_document_ids", []),
                        "cited_document_ids": row.get("cited_document_ids", []),
                        "model": row.get("model") or report.get("requested_model"),
                        "usage": row.get("usage", {}),
                        "response_id": row.get("response_id"),
                    },
                }
            )
    return cases


def _automatic_retrieval_cases(
    report: dict[str, Any], *, mode: str
) -> list[dict[str, object]]:
    result = next(
        (item for item in report.get("results", []) if item.get("mode") == mode),
        None,
    )
    if result is None:
        return []
    run_id = str(report.get("run_id") or "")
    cases: list[dict[str, object]] = []
    for row in result.get("questions", []):
        reciprocal_rank = float(row.get("reciprocal_rank", 0.0))
        categories: list[str] = []
        severity = "low"
        if not bool(row.get("hit_at_5", 0.0)):
            categories.append("retrieval_miss")
            severity = "high"
        elif reciprocal_rank < 1.0:
            categories.append("low_rank")
            severity = "medium" if reciprocal_rank < (1 / 3) else "low"
        if categories:
            cases.append(
                {
                    "item_id": (
                        f"retrieval:{run_id}:{mode}:{row['question_id']}"
                        if run_id
                        else f"retrieval:{row['question_id']}"
                    ),
                    "item_type": "retrieval",
                    "evaluation_run_id": run_id or "legacy",
                    "question_id": row["question_id"],
                    "question": row["question"],
                    "categories": categories,
                    "severity": severity,
                    "detection_source": "automatic_rule",
                    "details": {
                        "mode": mode,
                        "reciprocal_rank": reciprocal_rank,
                        "hit_at_5": row.get("hit_at_5"),
                        "expected_document_ids": row.get("expected_document_ids", []),
                        "retrieved_document_ids": row.get("retrieved_document_ids", []),
                    },
                }
            )
    return cases


def _manual_cases(database_path: Path) -> tuple[list[dict[str, object]], int, int]:
    reviews = all_expert_reviews(database_path)
    cases: list[dict[str, object]] = []
    stale_count = 0
    for review in reviews:
        stale = review["item_content_hash"] != review["content_hash"]
        stale_count += int(stale)
        has_problem = any(
            (
                review["question_verdict"] != "valid",
                review["evidence_verdict"] in {"partial", "incorrect"},
                review["answer_verdict"] in {"partial", "incorrect"},
                review["refusal_verdict"] == "incorrect",
                review["severity"] != "none",
                bool(review["error_categories"]),
            )
        )
        if not has_problem:
            continue
        cases.append(
            {
                "item_id": review["item_id"],
                "item_type": review["item_type"],
                "evaluation_run_id": review["evaluation_run_id"],
                "question_id": review["question_id"],
                "question": review["question"],
                "categories": review["error_categories"] or ["other"],
                "severity": review["severity"],
                "detection_source": "expert_review",
                "reviewer": review["reviewer"],
                "reviewed_at": review["reviewed_at"],
                "is_stale": stale,
                "details": {
                    "question_verdict": review["question_verdict"],
                    "evidence_verdict": review["evidence_verdict"],
                    "answer_verdict": review["answer_verdict"],
                    "refusal_verdict": review["refusal_verdict"],
                    "notes": review["notes"],
                },
            }
        )
    return cases, len(reviews), stale_count


def build_bad_case_report(
    *,
    generation_report_path: Path = GENERATION_REPORT_PATH,
    retrieval_report_path: Path = RETRIEVAL_REPORT_PATH,
    database_path: Path = DEFAULT_DATABASE_PATH,
    retrieval_mode: str = "sparse",
) -> dict[str, object]:
    generation_report = (
        json.loads(generation_report_path.read_text(encoding="utf-8"))
        if generation_report_path.exists()
        else {}
    )
    retrieval_report = (
        json.loads(retrieval_report_path.read_text(encoding="utf-8"))
        if retrieval_report_path.exists()
        else {}
    )
    automatic_cases = [
        *_automatic_generation_cases(generation_report),
        *_automatic_retrieval_cases(retrieval_report, mode=retrieval_mode),
    ]
    manual_cases, manual_review_count, stale_manual_review_count = _manual_cases(
        database_path
    )
    category_counts = Counter(
        category
        for case in [*automatic_cases, *manual_cases]
        for category in case["categories"]
    )
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "review_status": (
            "expert_reviews_present" if manual_review_count else "awaiting_expert_review"
        ),
        "generation_run_id": generation_report.get("run_id", "legacy"),
        "retrieval_mode": retrieval_mode,
        "method_note": (
            "Automatic rules are triage signals, not expert conclusions. "
            "Expert-review findings are reported separately and stale reviews are retained."
        ),
        "summary": {
            "automatic_bad_case_count": len(automatic_cases),
            "manual_review_count": manual_review_count,
            "manual_bad_case_count": len(manual_cases),
            "stale_manual_review_count": stale_manual_review_count,
            "category_counts": dict(sorted(category_counts.items())),
        },
        "automatic_cases": automatic_cases,
        "manual_cases": manual_cases,
    }


def render_bad_case_markdown(report: dict[str, object]) -> str:
    summary = report["summary"]
    lines = [
        "# Bad Case 分析报告",
        "",
        f"生成时间：`{report['generated_at']}`",
        f"生成评测运行：`{report['generation_run_id']}`",
        "",
        "> 自动规则只用于筛选待复核样本，不等同于领域专家结论。人工结果与自动信号分开统计。",
        "",
        "## 摘要",
        "",
        f"- 自动规则标记：{summary['automatic_bad_case_count']} 条",
        f"- 人工复核记录：{summary['manual_review_count']} 条",
        f"- 人工确认 Bad Case：{summary['manual_bad_case_count']} 条",
        f"- 因系统输出变化而过期的人工记录：{summary['stale_manual_review_count']} 条",
        "",
        "## 自动规则标记",
        "",
    ]
    automatic_cases = report["automatic_cases"]
    if automatic_cases:
        lines.extend(
            [
                "| ID | 类型 | 错误分类 | 严重度 | 问题 |",
                "|---|---|---|---|---|",
            ]
        )
        for case in automatic_cases:
            question = str(case["question"]).replace("|", "\\|")
            lines.append(
                f"| `{case['question_id']}` | {case['item_type']} | "
                f"{', '.join(case['categories'])} | {case['severity']} | {question} |"
            )
    else:
        lines.append("当前自动规则未标记 Bad Case。")
    lines.extend(["", "## 人工复核发现", ""])
    manual_cases = report["manual_cases"]
    if manual_cases:
        lines.extend(
            [
                "| ID | 复核者 | 错误分类 | 严重度 | 是否过期 | 备注 |",
                "|---|---|---|---|---|---|",
            ]
        )
        for case in manual_cases:
            note = str(case["details"].get("notes", "")).replace("|", "\\|")
            lines.append(
                f"| `{case['question_id']}` | {case['reviewer']} | "
                f"{', '.join(case['categories'])} | {case['severity']} | "
                f"{'是' if case['is_stale'] else '否'} | {note or '—'} |"
            )
    else:
        lines.append(
            "尚无人工确认的 Bad Case；"
            f"已完成人工复核 {summary['manual_review_count']} 条。"
        )
    lines.extend(
        [
            "",
            "## 建议处理顺序",
            "",
            "1. 先复核 `high` 严重度以及拒答、引用错误。",
            "2. 再检查检索低排名样本的实体别名、术语扩展和 gold 文档合理性。",
            "3. 对 `missing_key_fact` 比较原始证据、检索切片与答案，定位是检索还是生成问题。",
            "4. 修复后重新生成评测报告并导入队列；内容哈希变化会提示旧结论已过期。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build automatic and human bad-case reports.")
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE_PATH)
    parser.add_argument("--generation-report", type=Path, default=GENERATION_REPORT_PATH)
    parser.add_argument("--retrieval-report", type=Path, default=RETRIEVAL_REPORT_PATH)
    parser.add_argument("--retrieval-mode", default="sparse")
    parser.add_argument("--output", type=Path, default=BAD_CASE_REPORT_PATH)
    parser.add_argument("--markdown", type=Path, default=BAD_CASE_MARKDOWN_PATH)
    args = parser.parse_args()
    report = build_bad_case_report(
        generation_report_path=args.generation_report,
        retrieval_report_path=args.retrieval_report,
        database_path=args.database,
        retrieval_mode=args.retrieval_mode,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    args.markdown.write_text(render_bad_case_markdown(report), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
