from __future__ import annotations

import json
import re
import time
import unicodedata
from contextlib import closing
from pathlib import Path
from typing import Iterable

from adc_evidence.database import connect, create_database
from adc_evidence.generation.models import (
    AnswerGap,
    AnswerResult,
    AtomicClaim,
    CitationSource,
    ClaimSupport,
    ClaimValidationSummary,
    QuestionPlan,
)
from adc_evidence.workbench import (
    ADC_FIELD_SPECS,
    compare_adcs,
    evidence_data_version,
    get_adc_evidence_card,
    list_changes,
)


STRUCTURED_MODEL = "v0.6-structured-validator-v2"
ADC_FIELD_LABELS = dict(ADC_FIELD_SPECS)
DEFAULT_PROFILE_FIELDS = (
    "adc.target",
    "adc.payload_name",
    "adc.payload_class",
    "adc.dar",
    "adc.development_status",
)

_ADC_FIELD_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("adc.payload_class", ("payload class", "载荷类型", "载荷类别", "作用机制类型")),
    ("adc.payload_name", ("payload name", "payload", "载荷名称", "载荷")),
    ("adc.linker_type", ("linker type", "连接子类型", "linker类型")),
    ("adc.linker_name", ("linker name", "连接子名称", "linker", "连接子")),
    ("adc.development_status", ("研发状态", "开发状态", "获批状态", "development status")),
    ("adc.company", ("开发企业", "企业", "公司", "company", "sponsor")),
    ("adc.antibody", ("抗体", "antibody")),
    ("adc.target", ("靶点", "target")),
    ("adc.dar", ("药物抗体比", "dar")),
    ("adc.indication", ("适应证", "适应症", "indication")),
)

_TRIAL_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("trial.nct_id", "注册号", "nct_id"),
    ("trial.overall_status", "试验状态", "overall_status"),
    ("trial.phases", "试验阶段", "phases_json"),
    ("trial.conditions", "疾病/条件", "conditions_json"),
    ("trial.interventions", "干预", "interventions_json"),
    ("trial.primary_outcomes", "主要终点", "primary_outcomes_json"),
    ("trial.enrollment", "入组人数", "enrollment"),
    ("trial.start_date", "开始日期", "start_date"),
    ("trial.completion_date", "完成日期", "completion_date"),
)
_TRIAL_FIELD_LABELS = {predicate: label for predicate, label, _ in _TRIAL_FIELDS}
_TRIAL_COLUMN_BY_PREDICATE = {
    predicate: column for predicate, _, column in _TRIAL_FIELDS
}


def _normalized(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold()


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _display(value: object) -> str:
    if isinstance(value, list):
        return "；".join(_display(item) for item in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _resolve_adcs(database_path: Path, question: str) -> list[tuple[str, str]]:
    create_database(database_path)
    with closing(connect(database_path)) as connection:
        rows = connection.execute(
            """
            SELECT adc.adc_id, adc.adc_name, alias.alias
            FROM adcs AS adc
            LEFT JOIN adc_aliases AS alias ON alias.adc_id = adc.adc_id
            ORDER BY adc.adc_id, alias.alias
            """
        ).fetchall()
    names: dict[str, str] = {}
    forms: list[tuple[str, str, int]] = []
    lowered = _normalized(question)
    for row in rows:
        adc_id = str(row["adc_id"])
        names[adc_id] = str(row["adc_name"])
        for raw in (row["adc_name"], row["alias"]):
            if raw is None:
                continue
            form = _normalized(str(raw)).strip()
            if len(form) < 3:
                continue
            position = lowered.find(form)
            if position >= 0:
                forms.append((adc_id, form, position))
    resolved: list[tuple[str, str]] = []
    seen: set[str] = set()
    for adc_id, _, position in sorted(forms, key=lambda item: (item[2], -len(item[1]))):
        if adc_id not in seen:
            resolved.append((adc_id, names[adc_id]))
            seen.add(adc_id)
    return resolved


def _extract_adc_predicates(question: str) -> list[str]:
    lowered = _normalized(question)
    predicates: list[str] = []
    payload_class_requested = any(
        marker in lowered for marker in _ADC_FIELD_KEYWORDS[0][1]
    )
    linker_type_requested = any(
        marker in lowered for marker in _ADC_FIELD_KEYWORDS[2][1]
    )
    for predicate, markers in _ADC_FIELD_KEYWORDS:
        if predicate == "adc.payload_name" and payload_class_requested:
            specific = ("payload name", "载荷名称")
            if not any(marker in lowered for marker in specific):
                continue
        if predicate == "adc.linker_name" and linker_type_requested:
            specific = ("linker name", "连接子名称")
            if not any(marker in lowered for marker in specific):
                continue
        if any(marker in lowered for marker in markers):
            predicates.append(predicate)
    return predicates


def _extract_trial_predicates(question: str) -> list[str]:
    lowered = _normalized(question)
    mappings = (
        ("trial.overall_status", ("状态", "招募", "撤回", "暂停", "status")),
        ("trial.phases", ("阶段", "几期", "期试验", "phase")),
        ("trial.conditions", ("疾病", "癌种", "条件", "condition")),
        ("trial.interventions", ("干预", "用药", "intervention")),
        ("trial.primary_outcomes", ("主要终点", "终点", "outcome", "endpoint")),
        ("trial.enrollment", ("入组", "人数", "enrollment")),
        ("trial.start_date", ("开始日期", "启动日期", "start date")),
        ("trial.completion_date", ("完成日期", "completion date")),
    )
    predicates = [
        predicate
        for predicate, markers in mappings
        if any(marker in lowered for marker in markers)
    ]
    if "nct" in lowered or "注册号" in lowered:
        predicates.insert(0, "trial.nct_id")
    return list(dict.fromkeys(predicates))


def _extract_days(question: str) -> int:
    lowered = _normalized(question)
    if any(marker in lowered for marker in ("30天", "三十天", "一个月", "近月")):
        return 30
    if any(marker in lowered for marker in ("1天", "一天", "24小时", "今天", "今日")):
        return 1
    return 7


def route_question(database_path: Path, question: str) -> QuestionPlan:
    """Create a deterministic, inspectable query plan before accessing evidence."""
    lowered = _normalized(question)
    resolved = _resolve_adcs(database_path, question)
    adc_ids = [item[0] for item in resolved]
    adc_names = [item[1] for item in resolved]
    targets = [target for target in ("HER2", "TROP2") if target.casefold() in lowered]
    nct_ids = list(dict.fromkeys(re.findall(r"\bNCT\d{8}\b", question, re.I)))
    nct_ids = [item.upper() for item in nct_ids]
    comparison = any(
        marker in lowered for marker in ("比较", "对比", "区别", "差异", " versus ", " vs ")
    )
    change = any(
        marker in lowered
        for marker in (
            "最近", "近一", "变化", "变更", "更新", "新增", "过去",
            "采集失败", "来源缺失", "记录缺失", "变化事件", "冲突",
        )
    )
    trial = bool(nct_ids) or any(
        marker in lowered
        for marker in ("临床试验", "试验", "注册号", "招募", "主要终点", "入组", "nct")
    )
    trial = trial or bool(re.search(r"\b(?:phase\s*)?(?:i{1,3}|iv|v)\s*期", lowered, re.I))
    literature = any(
        marker in lowered
        for marker in (
            "pubmed",
            "pmid",
            "文献",
            "论文",
            "摘要",
            "机制",
            "耐药",
            "研究结论",
            "疗效",
            "安全性",
            "半衰期",
            "活性",
            "转运",
            "释放",
            "研究",
            "提及",
        )
    )

    if comparison:
        if len(adc_ids) < 2:
            if literature:
                return QuestionPlan(
                    route="literature_evidence",
                    reason="literature_intent_overrides_incomplete_comparison_entities",
                    confidence=0.9,
                    adc_ids=adc_ids,
                    adc_names=adc_names,
                    targets=targets,
                )
            return QuestionPlan(
                route="refusal",
                reason="comparison_requires_two_known_adcs",
                confidence=1.0,
                adc_ids=adc_ids,
                adc_names=adc_names,
            )
        return QuestionPlan(
            route="comparison",
            reason="comparison_intent_with_multiple_known_adcs",
            confidence=1.0,
            adc_ids=adc_ids,
            adc_names=adc_names,
            predicates=_extract_adc_predicates(question) or list(DEFAULT_PROFILE_FIELDS),
            targets=targets,
        )
    if change:
        return QuestionPlan(
            route="change_query",
            reason="recent_change_intent",
            confidence=0.98,
            adc_ids=adc_ids,
            adc_names=adc_names,
            targets=targets,
            days=_extract_days(question),
        )
    if trial:
        return QuestionPlan(
            route="trial_lookup",
            reason="trial_identifier_or_registry_field_intent",
            confidence=1.0 if nct_ids else 0.92,
            adc_ids=adc_ids,
            adc_names=adc_names,
            predicates=_extract_trial_predicates(question)
            or ["trial.nct_id", "trial.overall_status", "trial.phases"],
            nct_ids=nct_ids,
            targets=targets,
        )
    if literature:
        return QuestionPlan(
            route="literature_evidence",
            reason="literature_or_unstructured_research_claim_intent",
            confidence=0.9,
            adc_ids=adc_ids,
            adc_names=adc_names,
            targets=targets,
        )
    predicates = _extract_adc_predicates(question)
    if adc_ids:
        return QuestionPlan(
            route="structured_fact",
            reason="known_adc_with_structured_field_intent",
            confidence=1.0 if predicates else 0.85,
            adc_ids=adc_ids,
            adc_names=adc_names,
            predicates=predicates or list(DEFAULT_PROFILE_FIELDS),
            targets=targets,
        )
    return QuestionPlan(
        route="refusal",
        reason="no_supported_entity_or_route",
        confidence=0.95,
        targets=targets,
    )


class _CitationRegistry:
    def __init__(self) -> None:
        self.items: list[CitationSource] = []
        self._ids: dict[str, str] = {}

    def add(
        self,
        *,
        key: str,
        chunk_id: str,
        retrieval_document_id: str,
        source_type: str,
        title: str,
        source_url: str,
        excerpt: str,
    ) -> str:
        existing = self._ids.get(key)
        if existing:
            return existing
        citation_id = f"S{len(self.items) + 1}"
        self._ids[key] = citation_id
        self.items.append(
            CitationSource(
                citation_id=citation_id,
                chunk_id=chunk_id,
                retrieval_document_id=retrieval_document_id,
                source_type=source_type,
                title=title,
                source_url=source_url,
                excerpt=excerpt,
            )
        )
        return citation_id


def validate_structured_claim(
    claim: AtomicClaim,
    *,
    expected_value: object,
    allowed_citation_ids: Iterable[str],
) -> ClaimSupport:
    allowed = set(allowed_citation_ids)
    missing_citations = [item for item in claim.citation_ids if item not in allowed]
    value_matches = _canonical(claim.value) == _canonical(expected_value)
    if not claim.citation_ids:
        reason = "missing_field_evidence"
    elif missing_citations:
        reason = "citation_not_bound_to_field"
    elif not value_matches:
        reason = "value_not_equal_to_structured_field"
    else:
        reason = None
    return ClaimSupport(
        claim_id=claim.claim_id,
        supported=reason is None,
        citation_ids=claim.citation_ids,
        matched_terms=[_display(expected_value)] if value_matches else [],
        missing_terms=[] if value_matches else [_display(expected_value)],
        reason=reason,
    )


def _field_citations(
    registry: _CitationRegistry,
    *,
    adc_name: str,
    predicate: str,
    field: dict[str, object],
) -> list[str]:
    citation_ids: list[str] = []
    for value in field["values"]:
        for evidence in value["evidence"]:
            citation_ids.append(
                registry.add(
                    key=str(evidence["fact_evidence_id"]),
                    chunk_id=str(evidence["fact_evidence_id"]),
                    retrieval_document_id=f"fact:{value['fact_id']}",
                    source_type=f"structured_fact:{evidence['source']}",
                    title=f"{adc_name} · {field['label']}",
                    source_url=str(evidence["source_url"]),
                    excerpt=str(evidence["evidence_text"]),
                )
            )
    return list(dict.fromkeys(citation_ids))


def _gap(field_label: str, reason: str) -> AnswerGap:
    if reason == "conflicted":
        detail = "存在未解决的来源冲突，系统不选择单一值。"
    elif reason == "validation_failed":
        detail = "结构化值或字段证据映射未通过校验。"
    else:
        detail = "当前事实层没有该字段的直接证据。"
    return AnswerGap(item=field_label, reason=reason, detail=detail)


def _answer_result(
    *,
    question: str,
    plan: QuestionPlan,
    claims: list[AtomicClaim],
    checks: list[ClaimSupport],
    gaps: list[AnswerGap],
    registry: _CitationRegistry,
    data_version: dict[str, object],
    started_at: float,
) -> AnswerResult:
    supported_ids = {
        citation_id for claim in claims for citation_id in claim.citation_ids
    }
    citations = [
        citation for citation in registry.items if citation.citation_id in supported_ids
    ]
    if claims:
        lines = [
            f"- {claim.text} "
            + "".join(f"[{citation_id}]" for citation_id in claim.citation_ids)
            for claim in claims
        ]
        if gaps:
            lines.extend(
                ["", "未回答："]
                + [f"- {gap.item}：{gap.detail}" for gap in gaps]
            )
        status = "partial" if gaps else "answered"
        refusal_reason = "partial_evidence" if gaps else None
    else:
        status = "refused"
        refusal_reason = "structured_evidence_insufficient"
        lines = ["现有结构化证据不足，无法可靠回答。"]
        if gaps:
            lines.extend(["", "未回答："] + [f"- {gap.item}：{gap.detail}" for gap in gaps])
    supported_count = sum(check.supported for check in checks)
    validation = ClaimValidationSummary(
        valid=bool(checks) and supported_count == len(checks),
        support_kind="structured",
        claim_count=len(checks),
        supported_claim_count=supported_count,
        unsupported_claim_count=len(checks) - supported_count,
        claims=checks,
    )
    return AnswerResult(
        question=question,
        status=status,
        answer="\n".join(lines),
        refusal_reason=refusal_reason,
        generator_backend="structured",
        model=STRUCTURED_MODEL,
        retrieval_mode="structured",
        route=plan.route,
        route_reason=plan.reason,
        retrieved_source_count=len(citations),
        citations=citations,
        claim_validation=validation,
        claims=claims,
        unanswered=gaps,
        data_version=data_version,
        latency_ms=round((time.perf_counter() - started_at) * 1000),
    )


class StructuredAnswerEngine:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path

    def answer(
        self,
        question: str,
        plan: QuestionPlan,
        *,
        started_at: float | None = None,
    ) -> AnswerResult:
        started = started_at or time.perf_counter()
        version = evidence_data_version(self.database_path)
        if plan.route == "structured_fact":
            return self._adc_fields(question, plan, version, started)
        if plan.route == "comparison":
            return self._comparison(question, plan, version, started)
        if plan.route == "trial_lookup":
            return self._trials(question, plan, version, started)
        if plan.route == "change_query":
            return self._changes(question, plan, version, started)
        raise ValueError(f"Structured engine cannot execute route: {plan.route}")

    def _adc_fields(
        self,
        question: str,
        plan: QuestionPlan,
        version: dict[str, object],
        started: float,
    ) -> AnswerResult:
        registry = _CitationRegistry()
        claims: list[AtomicClaim] = []
        checks: list[ClaimSupport] = []
        gaps: list[AnswerGap] = []
        for adc_id in plan.adc_ids:
            card = get_adc_evidence_card(
                self.database_path, adc_id, data_version=version
            )
            for predicate in plan.predicates:
                field = card["field_map"].get(predicate)
                label = f"{card['adc_name']} · {ADC_FIELD_LABELS.get(predicate, predicate)}"
                if field is None or field["is_missing"]:
                    gaps.append(_gap(label, "missing_direct_evidence"))
                    continue
                if field["is_conflicted"]:
                    gaps.append(_gap(label, "conflicted"))
                    continue
                citation_ids = _field_citations(
                    registry,
                    adc_name=str(card["adc_name"]),
                    predicate=predicate,
                    field=field,
                )
                value = [item["value"] for item in field["values"]]
                claim = AtomicClaim(
                    claim_id=f"C{len(checks) + 1}",
                    text=(
                        f"{card['adc_name']} 的{field['label']}为"
                        f"{field['display_value']}。"
                    ),
                    subject_type="adc",
                    subject_id=adc_id,
                    predicate=predicate,
                    value=value,
                    citation_ids=citation_ids,
                    support_kind="structured",
                    validation_status="supported",
                )
                check = validate_structured_claim(
                    claim,
                    expected_value=value,
                    allowed_citation_ids=citation_ids,
                )
                checks.append(check)
                if check.supported:
                    claims.append(claim)
                else:
                    gaps.append(_gap(label, "validation_failed"))
        return _answer_result(
            question=question,
            plan=plan,
            claims=claims,
            checks=checks,
            gaps=gaps,
            registry=registry,
            data_version=version,
            started_at=started,
        )

    def _comparison(
        self,
        question: str,
        plan: QuestionPlan,
        version: dict[str, object],
        started: float,
    ) -> AnswerResult:
        comparison = compare_adcs(self.database_path, plan.adc_ids)
        registry = _CitationRegistry()
        claims: list[AtomicClaim] = []
        checks: list[ClaimSupport] = []
        gaps: list[AnswerGap] = []
        for predicate in plan.predicates:
            row = next(
                (item for item in comparison["rows"] if item["predicate"] == predicate),
                None,
            )
            if row is None:
                continue
            for adc in comparison["adcs"]:
                cell = row["cells"][adc["adc_id"]]
                label = f"{adc['adc_name']} · {row['label']}"
                if cell["status"] == "missing":
                    gaps.append(_gap(label, "missing_direct_evidence"))
                    continue
                if cell["status"] == "conflicted":
                    gaps.append(_gap(label, "conflicted"))
                    continue
                field = {**cell, "label": row["label"]}
                citation_ids = _field_citations(
                    registry,
                    adc_name=str(adc["adc_name"]),
                    predicate=predicate,
                    field=field,
                )
                value = [item["value"] for item in cell["values"]]
                claim = AtomicClaim(
                    claim_id=f"C{len(checks) + 1}",
                    text=f"{adc['adc_name']} 的{row['label']}为{cell['display_value']}。",
                    subject_type="adc",
                    subject_id=str(adc["adc_id"]),
                    predicate=predicate,
                    value=value,
                    citation_ids=citation_ids,
                    support_kind="structured",
                    validation_status="supported",
                )
                check = validate_structured_claim(
                    claim,
                    expected_value=value,
                    allowed_citation_ids=citation_ids,
                )
                checks.append(check)
                if check.supported:
                    claims.append(claim)
                else:
                    gaps.append(_gap(label, "validation_failed"))
        return _answer_result(
            question=question,
            plan=plan,
            claims=claims,
            checks=checks,
            gaps=gaps,
            registry=registry,
            data_version=version,
            started_at=started,
        )

    def _trial_rows(self, question: str, plan: QuestionPlan):
        create_database(self.database_path)
        with closing(connect(self.database_path)) as connection:
            if plan.nct_ids:
                placeholders = ",".join("?" for _ in plan.nct_ids)
                rows = connection.execute(
                    f"SELECT * FROM trials WHERE nct_id IN ({placeholders}) ORDER BY nct_id",
                    plan.nct_ids,
                ).fetchall()
            elif plan.adc_ids:
                placeholders = ",".join("?" for _ in plan.adc_ids)
                rows = connection.execute(
                    f"""
                    SELECT DISTINCT trial.* FROM trials AS trial
                    JOIN entity_links AS link
                      ON link.source_record_type = 'trial'
                     AND link.source_record_id = trial.nct_id
                    WHERE link.entity_type = 'adc'
                      AND link.entity_id IN ({placeholders})
                    ORDER BY trial.nct_id
                    """,
                    plan.adc_ids,
                ).fetchall()
            else:
                rows = connection.execute("SELECT * FROM trials ORDER BY nct_id").fetchall()
        phase = None
        lowered = _normalized(question)
        for marker, value in (
            ("iii期", "PHASE3"),
            ("3期", "PHASE3"),
            ("ii期", "PHASE2"),
            ("2期", "PHASE2"),
            ("i期", "PHASE1"),
            ("1期", "PHASE1"),
        ):
            if marker in lowered:
                phase = value
                break
        if phase:
            rows = [row for row in rows if phase in str(row["phases_json"]).upper()]
        return rows[:5]

    def _trials(
        self,
        question: str,
        plan: QuestionPlan,
        version: dict[str, object],
        started: float,
    ) -> AnswerResult:
        registry = _CitationRegistry()
        claims: list[AtomicClaim] = []
        checks: list[ClaimSupport] = []
        gaps: list[AnswerGap] = []
        rows = self._trial_rows(question, plan)
        if not rows:
            label = ", ".join(plan.nct_ids) or "符合条件的临床试验"
            gaps.append(
                AnswerGap(
                    item=label,
                    reason="no_matching_record",
                    detail="当前 ClinicalTrials.gov 标准化记录中没有匹配项。",
                )
            )
        for row in rows:
            for predicate in plan.predicates:
                column = _TRIAL_COLUMN_BY_PREDICATE.get(predicate)
                if column is None:
                    continue
                raw_value = row[column]
                value = (
                    json.loads(str(raw_value))
                    if column.endswith("_json") and raw_value is not None
                    else raw_value
                )
                label = f"{row['nct_id']} · {_TRIAL_FIELD_LABELS[predicate]}"
                if value in (None, "", [], {}):
                    gaps.append(_gap(label, "missing_direct_evidence"))
                    continue
                display_value = _display(value)
                citation_id = registry.add(
                    key=f"trial:{row['nct_id']}:{predicate}",
                    chunk_id=f"trial:{row['nct_id']}#{predicate}",
                    retrieval_document_id=f"clinical_trial:{row['nct_id']}",
                    source_type="clinical_trial",
                    title=str(row["brief_title"]),
                    source_url=str(row["source_url"]),
                    excerpt=f"{_TRIAL_FIELD_LABELS[predicate]}: {display_value}",
                )
                claim = AtomicClaim(
                    claim_id=f"C{len(checks) + 1}",
                    text=f"{row['nct_id']} 的{_TRIAL_FIELD_LABELS[predicate]}为{display_value}。",
                    subject_type="trial",
                    subject_id=str(row["nct_id"]),
                    predicate=predicate,
                    value=value,
                    citation_ids=[citation_id],
                    support_kind="structured",
                    validation_status="supported",
                )
                check = validate_structured_claim(
                    claim,
                    expected_value=value,
                    allowed_citation_ids=[citation_id],
                )
                checks.append(check)
                if check.supported:
                    claims.append(claim)
                else:
                    gaps.append(_gap(label, "validation_failed"))
        return _answer_result(
            question=question,
            plan=plan,
            claims=claims,
            checks=checks,
            gaps=gaps,
            registry=registry,
            data_version=version,
            started_at=started,
        )

    def _changes(
        self,
        question: str,
        plan: QuestionPlan,
        version: dict[str, object],
        started: float,
    ) -> AnswerResult:
        registry = _CitationRegistry()
        claims: list[AtomicClaim] = []
        checks: list[ClaimSupport] = []
        gaps: list[AnswerGap] = []
        events = list_changes(
            self.database_path,
            days=plan.days or 7,
            adc_ids=plan.adc_ids,
            targets=plan.targets,
        )
        if not events:
            gaps.append(
                AnswerGap(
                    item=f"最近 {plan.days or 7} 天变化",
                    reason="no_matching_record",
                    detail="当前变化事件表中没有匹配记录；这不代表外部世界一定没有变化。",
                )
            )
        for event in events[:20]:
            old_value = event["old_value"]
            new_value = event["new_value"]
            subject = ", ".join(event["entities"]["adc_names"]) or str(event["subject_id"])
            excerpt = (
                f"事件类型: {event['event_type']}\n"
                f"主体: {subject}\n旧值: {_display(old_value)}\n"
                f"新值: {_display(new_value)}\n检测时间: {event['detected_at']}"
            )
            snapshot = event.get("snapshot") or {}
            citation_id = registry.add(
                key=str(event["event_id"]),
                chunk_id=f"change:{event['event_id']}",
                retrieval_document_id=f"change_event:{event['event_id']}",
                source_type=f"change_event:{event['source'] or 'internal'}",
                title=f"{subject} · {event['event_type']}",
                source_url=str(snapshot.get("source_url") or ""),
                excerpt=excerpt,
            )
            value = {"old": old_value, "new": new_value}
            claim = AtomicClaim(
                claim_id=f"C{len(claims) + 1}",
                text=(
                    f"{subject} 在 {event['detected_at']} 检测到 {event['event_type']}："
                    f"{_display(old_value)} → {_display(new_value)}。"
                ),
                subject_type=str(event["subject_type"]),
                subject_id=str(event["subject_id"]),
                predicate=str(event["predicate"] or event["event_type"]),
                value=value,
                citation_ids=[citation_id],
                support_kind="structured",
                validation_status="supported",
            )
            check = validate_structured_claim(
                claim,
                expected_value=value,
                allowed_citation_ids=[citation_id],
            )
            checks.append(check)
            if check.supported:
                claims.append(claim)
        return _answer_result(
            question=question,
            plan=plan,
            claims=claims,
            checks=checks,
            gaps=gaps,
            registry=registry,
            data_version=version,
            started_at=started,
        )
