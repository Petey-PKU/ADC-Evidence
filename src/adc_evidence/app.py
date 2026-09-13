from __future__ import annotations

import json
import os

import streamlit as st

from adc_evidence.config import (
    BENCHMARK_REVIEW_PACKET_PATH,
    DEFAULT_DATABASE_PATH,
    DEFAULT_SEED_PATH,
    GENERATION_REPORT_PATH,
    RETRIEVAL_REPORT_PATH,
    VECTOR_INDEX_PATH,
    environment_flag,
)
from adc_evidence.database import (
    database_stats,
    search_adcs,
)
from adc_evidence.generation.generators import (
    configured_generation_backends,
    create_generator,
)
from adc_evidence.generation.service import EvidenceAnsweringService
from adc_evidence.evidence_policy import load_evidence_policy
from adc_evidence.rag.retriever import HybridRetriever
from adc_evidence.repository import data_quality_metrics
from adc_evidence.review.repository import (
    ANSWER_VERDICTS,
    CITATION_VERDICTS,
    COMPLETENESS_VERDICTS,
    ERROR_CATEGORIES,
    EVIDENCE_VERDICTS,
    QUESTION_VERDICTS,
    REFUSAL_VERDICTS,
    REVIEWER_SLOTS,
    SEVERITIES,
    get_review_documents,
    list_review_items,
    list_review_runs,
    prepare_review_queue,
    review_stats,
    save_expert_review,
)
from adc_evidence.workbench import (
    build_evidence_brief,
    compare_adcs,
    comparison_to_csv,
    comparison_to_markdown,
    evidence_brief_to_json,
    evidence_brief_to_markdown,
    evidence_data_version,
    get_adc_evidence_card,
    list_changes,
    sync_public_seed_facts,
)


st.set_page_config(
    page_title="ADC-Evidence",
    page_icon="🧬",
    layout="wide",
)

PUBLIC_DEMO = environment_flag("ADC_PUBLIC_DEMO", default=False)


def ensure_database() -> None:
    sync_public_seed_facts(DEFAULT_DATABASE_PATH, DEFAULT_SEED_PATH)


def ensure_review_queue() -> None:
    prepare_review_queue(
        database_path=DEFAULT_DATABASE_PATH,
        generation_report_path=GENERATION_REPORT_PATH,
        retrieval_report_path=RETRIEVAL_REPORT_PATH,
        benchmark_packet_path=BENCHMARK_REVIEW_PACKET_PATH,
        retrieval_mode="sparse",
    )


FIELD_STATUS_LABELS = {
    "current": "当前",
    "conflicted": "来源冲突",
    "missing": "未记录",
}

FRESHNESS_LABELS = {
    "current": "在新鲜度范围内",
    "stale": "可能过期",
    "unknown": "新鲜度未知",
    "demo_source": "公开演示种子",
    "mixed": "多来源混合",
}


def _display_field_evidence(field: dict[str, object]) -> None:
    status = FIELD_STATUS_LABELS.get(str(field["status"]), str(field["status"]))
    freshness = FRESHNESS_LABELS.get(
        str(field["freshness_status"]),
        str(field["freshness_status"]),
    )
    prefix = "⚠️ " if field["is_conflicted"] or field["is_stale"] else ""
    with st.expander(
        f"{prefix}{field['label']}：{field['display_value']}",
        expanded=bool(field["is_conflicted"]),
    ):
        st.caption(
            f"字段：{field['predicate']} · 状态：{status} · 新鲜度：{freshness} · "
            f"审核：{field['review_status']} · 当前证据：{field['evidence_count']} 条"
        )
        if field["is_missing"]:
            st.info("当前事实层没有该字段的直接证据，系统不会使用模型常识补齐。")
            return
        if field["is_conflicted"]:
            st.warning("多个来源给出了不同值；冲突值全部保留，尚未静默裁决。")
        for value in field["values"]:
            st.markdown(
                f"**规范值：{value['display_value']}** · 事实状态：{value['status']} · "
                f"有效起点：{value['valid_from']}"
            )
            for evidence in value["evidence"]:
                st.markdown(
                    f"- **{evidence['source_display_name']}** / "
                    f"`{evidence['source_record_id']}`"
                )
                st.caption(
                    f"观测时间：{evidence['observed_at']} · "
                    f"来源更新时间：{evidence['source_updated_at'] or '未提供'} · "
                    f"快照：{evidence['snapshot_id'] or '公开种子无快照'} · "
                    f"审核：{evidence['review_status']}"
                )
                st.write(evidence["evidence_text"])
                if evidence["source_url"]:
                    st.markdown(
                        f"[打开这一条原始来源]({evidence['source_url']})"
                    )
        if field["history"]:
            st.markdown("**历史或已被替代的值**")
            for historical in field["history"]:
                st.write(
                    f"- {historical['display_value']} · {historical['status']} · "
                    f"{historical['valid_from']} → {historical['valid_to'] or '未关闭'}"
                )


def display_evidence_card(card: dict[str, object]) -> None:
    aliases = "、".join(card["aliases"])
    st.subheader(str(card["adc_name"]))
    st.caption(
        f"ADC ID：{card['adc_id']} · 别名：{aliases or '无'} · "
        f"数据版本：{card['data_version']['data_version'][:21]}…"
    )
    field_map = dict(card["field_map"])
    summary_columns = st.columns(4)
    summary_columns[0].metric("靶点", field_map["adc.target"]["display_value"])
    summary_columns[1].metric(
        "Payload", field_map["adc.payload_name"]["display_value"]
    )
    summary_columns[2].metric("DAR", field_map["adc.dar"]["display_value"])
    summary_columns[3].metric(
        "研发状态", field_map["adc.development_status"]["display_value"]
    )
    if card["conflicted_fields"]:
        st.warning(
            "存在未解决冲突：" + "、".join(card["conflicted_fields"])
        )
    if card["stale_fields"]:
        st.warning("可能过期字段：" + "、".join(card["stale_fields"]))
    if not card["traceability_complete"]:
        st.error("至少一个非空字段缺少完整来源、时间或审核状态，不应作为可发布核查结果。")
    for field in card["fields"]:
        _display_field_evidence(field)


def _event_value(value: object) -> str:
    if value in (None, [], {}):
        return "无"
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


@st.cache_resource
def retrieval_engine() -> HybridRetriever:
    return HybridRetriever(DEFAULT_DATABASE_PATH, VECTOR_INDEX_PATH)


@st.cache_resource
def answering_service(backend: str) -> EvidenceAnsweringService:
    return EvidenceAnsweringService(
        database_path=DEFAULT_DATABASE_PATH,
        retriever=retrieval_engine(),
        generator=create_generator(backend),
    )


def display_search_result(result) -> None:
    source_labels = {
        "adc_profile": "ADC 档案",
        "pubmed": "PubMed",
        "clinical_trial": "ClinicalTrials.gov",
    }
    with st.expander(
        f"#{result.rank} · {source_labels.get(result.source_type, result.source_type)} · {result.title}",
        expanded=result.rank <= 3,
    ):
        st.caption(
            f"文档 ID：{result.retrieval_document_id} · "
            f"切片 ID：{result.chunk_id} · 检索分数：{result.score:.4f}"
        )
        st.write(result.content)
        adc_names = result.metadata.get("adc_names", [])
        targets = result.metadata.get("targets", [])
        if adc_names or targets:
            st.caption(
                f"关联 ADC：{', '.join(adc_names) or '未关联'} · "
                f"靶点：{', '.join(targets) or '未关联'}"
            )
        if result.source_url:
            st.link_button("打开原始来源", result.source_url)


def display_answer_result(result) -> None:
    route_labels = {
        "structured_fact": "结构化事实",
        "comparison": "结构化比较",
        "change_query": "变化事件",
        "trial_lookup": "临床试验字段",
        "literature_evidence": "文献证据",
        "refusal": "拒答",
    }
    if result.status in {"answered", "partial"}:
        if result.status == "answered":
            st.success("回答中的原子结论已通过证据支持校验")
        else:
            st.warning("部分回答：仅展示已通过校验的结论，未回答项已明确列出")
        st.markdown(result.answer)
        validation = result.validation
        claim_validation = result.claim_validation
        metric_columns = st.columns(4)
        metric_columns[0].metric("问题路由", route_labels.get(result.route, result.route))
        metric_columns[1].metric(
            "已支持结论",
            claim_validation.supported_claim_count if claim_validation else len(result.claims),
        )
        metric_columns[2].metric("引用来源", len(result.citations))
        metric_columns[3].metric("耗时", f"{result.latency_ms} ms")
        if validation:
            st.caption(f"引用完整性覆盖率：{validation.coverage:.0%}")
        if result.data_version:
            st.caption(
                "数据版本："
                f"{str(result.data_version['data_version'])[:21]}… · "
                f"策略：{result.data_version['policy_version']} · "
                f"路由依据：{result.route_reason}"
            )
        if result.unanswered:
            with st.expander("查看未回答项", expanded=True):
                for gap in result.unanswered:
                    st.write(f"- {gap.item}：{gap.detail}（{gap.reason}）")
        st.subheader("引用证据")
        for citation in result.citations:
            with st.expander(
                f"[{citation.citation_id}] {citation.title}", expanded=False
            ):
                st.caption(
                    f"文档 ID：{citation.retrieval_document_id} · "
                    f"切片 ID：{citation.chunk_id} · 来源：{citation.source_type}"
                )
                st.write(citation.excerpt)
                if citation.source_url:
                    st.markdown(f"[打开原始来源]({citation.source_url})")
        if result.usage:
            st.caption(f"模型 token 用量：{result.usage}")
    elif result.status == "refused":
        st.warning(f"系统拒答：{result.answer}")
        st.caption(
            f"问题路由：{route_labels.get(result.route, result.route)} · "
            f"拒答原因代码：{result.refusal_reason}"
        )
        if result.validation and not result.validation.valid:
            st.caption(
                f"引用校验：覆盖率 {result.validation.coverage:.0%}；"
                f"无效引用 {', '.join(result.validation.invalid_ids) or '无'}"
            )
        if result.claim_validation:
            st.caption(
                "结论支持校验："
                f"{result.claim_validation.supported_claim_count}/"
                f"{result.claim_validation.claim_count} 通过"
            )
    else:
        st.error(result.answer)
        st.caption(f"错误类型：{result.refusal_reason}")


ensure_database()
if not PUBLIC_DEMO:
    ensure_review_queue()

st.title("ADC-Evidence")
st.caption("v0.6 阶段 5：冻结题集、三组盲评、原子结论复核与 Bad Case 回归")
st.warning(
    "自动采集数据与检索结果尚未经过系统人工审核，不能用于科研结论、临床或投资决策。"
)

stats = database_stats(DEFAULT_DATABASE_PATH)
quality_metrics = data_quality_metrics(DEFAULT_DATABASE_PATH)
active_fact_count = int(quality_metrics["current_fact_count"]) + int(
    quality_metrics["conflicted_fact_count"]
)
stat_columns = st.columns(3)
stat_columns[0].metric("ADC 记录", stats["adc_count"])
stat_columns[1].metric("靶点数量", stats["target_count"])
stat_columns[2].metric("标记为已批准", stats["approved_count"])

evidence_columns = st.columns(3)
evidence_columns[0].metric("PubMed 文献", stats["document_count"])
evidence_columns[1].metric("临床试验", stats["trial_count"])
evidence_columns[2].metric("当前原子事实", active_fact_count)
active_version = evidence_data_version(DEFAULT_DATABASE_PATH)
st.caption(
    f"数据版本：{active_version['data_version'][:21]}… · "
    f"模式：{active_version['schema_version']} · "
    f"策略：{active_version['policy_version']}"
)

st.divider()
(
    evidence_card_tab,
    comparison_tab,
    change_tab,
    retrieval_tab,
    answer_tab,
    review_tab,
) = st.tabs(
    [
        "ADC 证据卡",
        "ADC 比较",
        "变化中心",
        "证据检索",
        "证据问答",
        "专家复核（只读）" if PUBLIC_DEMO else "专家复核",
    ]
)

adc_options = search_adcs(DEFAULT_DATABASE_PATH, "")
adc_labels = {
    str(record["adc_id"]): (
        f"{record['adc_name']} · {record['target']} · {record['adc_id']}"
    )
    for record in adc_options
}

with evidence_card_tab:
    st.info("所有非空字段均来自结构化事实层；可展开查看来源、时间、快照和审核状态。")
    selected_adc_id = st.selectbox(
        "选择或搜索 ADC",
        list(adc_labels),
        format_func=lambda adc_id: adc_labels[adc_id],
        key="evidence_card_adc",
    )
    card = get_adc_evidence_card(DEFAULT_DATABASE_PATH, selected_adc_id)
    display_evidence_card(card)
    card_brief = build_evidence_brief(DEFAULT_DATABASE_PATH, [selected_adc_id])
    brief_columns = st.columns(2)
    brief_columns[0].download_button(
        "下载 Evidence Brief（Markdown）",
        data=evidence_brief_to_markdown(card_brief),
        file_name=f"{selected_adc_id}_evidence_brief.md",
        mime="text/markdown",
        use_container_width=True,
    )
    brief_columns[1].download_button(
        "下载 Evidence Brief（JSON）",
        data=evidence_brief_to_json(card_brief),
        file_name=f"{selected_adc_id}_evidence_brief.json",
        mime="application/json",
        use_container_width=True,
    )
    st.caption(card["disclaimer"])

with comparison_tab:
    st.info("选择 2～10 个 ADC。缺失和冲突会显式显示，比较值不会由模型补齐。")
    default_comparison = list(adc_labels)[:2]
    selected_comparison_ids = st.multiselect(
        "选择 ADC",
        list(adc_labels),
        default=default_comparison,
        format_func=lambda adc_id: adc_labels[adc_id],
        key="comparison_adc_ids",
    )
    if len(selected_comparison_ids) < 2:
        st.info("至少选择 2 个 ADC 才能比较。")
    elif len(selected_comparison_ids) > 10:
        st.error("一次最多比较 10 个 ADC。")
    else:
        comparison = compare_adcs(
            DEFAULT_DATABASE_PATH,
            selected_comparison_ids,
        )
        comparison_rows = []
        comparison_names = {
            str(adc["adc_id"]): str(adc["adc_name"])
            for adc in comparison["adcs"]
        }
        for row in comparison["rows"]:
            display_row = {"字段": row["label"]}
            for adc_id, adc_name in comparison_names.items():
                cell = row["cells"][adc_id]
                suffixes = []
                if cell["status"] == "conflicted":
                    suffixes.append("冲突")
                if cell["freshness_status"] == "stale":
                    suffixes.append("可能过期")
                suffix = f" [{' / '.join(suffixes)}]" if suffixes else ""
                display_row[adc_name] = f"{cell['display_value']}{suffix}"
            comparison_rows.append(display_row)
        st.dataframe(
            comparison_rows,
            use_container_width=True,
            hide_index=True,
        )
        if not comparison["traceability_complete"]:
            st.error("比较中存在缺少追溯信息的非空单元格，不能作为正式核查输出。")

        export_columns = st.columns(3)
        export_columns[0].download_button(
            "下载比较 CSV",
            data=comparison_to_csv(comparison),
            file_name="adc_evidence_comparison.csv",
            mime="text/csv",
            use_container_width=True,
        )
        export_columns[1].download_button(
            "下载比较 Markdown",
            data=comparison_to_markdown(comparison),
            file_name="adc_evidence_comparison.md",
            mime="text/markdown",
            use_container_width=True,
        )
        comparison_brief = build_evidence_brief(
            DEFAULT_DATABASE_PATH,
            selected_comparison_ids,
        )
        export_columns[2].download_button(
            "下载 Evidence Brief",
            data=evidence_brief_to_markdown(comparison_brief),
            file_name="adc_comparison_evidence_brief.md",
            mime="text/markdown",
            use_container_width=True,
        )

        evidence_row_labels = {
            str(row["predicate"]): str(row["label"])
            for row in comparison["rows"]
        }
        evidence_predicate = st.selectbox(
            "展开一个比较字段的单元格证据",
            list(evidence_row_labels),
            format_func=lambda predicate: evidence_row_labels[predicate],
            key="comparison_evidence_predicate",
        )
        selected_row = next(
            row
            for row in comparison["rows"]
            if row["predicate"] == evidence_predicate
        )
        for adc_id, adc_name in comparison_names.items():
            cell = selected_row["cells"][adc_id]
            with st.expander(
                f"{adc_name}：{cell['display_value']} · {cell['status']}",
                expanded=False,
            ):
                if cell["status"] == "missing":
                    st.info("该单元格没有直接事实证据。")
                for value in cell["values"]:
                    for evidence in value["evidence"]:
                        st.markdown(
                            f"- **{evidence['source_display_name']}** / "
                            f"`{evidence['source_record_id']}` · "
                            f"{evidence['observed_at']} · {evidence['review_status']}"
                        )
                        if evidence["source_url"]:
                            st.markdown(
                                f"[打开单元格原始来源]({evidence['source_url']})"
                            )

with change_tab:
    st.info("变化事件由事实版本差异产生，不由生成模型猜测；默认按检测时间倒序展示。")
    change_policy = load_evidence_policy()
    change_filter_columns = st.columns(2)
    change_days = change_filter_columns[0].radio(
        "时间范围",
        [1, 7, 30],
        index=1,
        format_func=lambda days: f"最近 {days} 天",
        horizontal=True,
        key="change_days",
    )
    selected_change_adc_ids = change_filter_columns[1].multiselect(
        "ADC",
        list(adc_labels),
        format_func=lambda adc_id: adc_labels[adc_id],
        key="change_adc_ids",
    )
    target_options = sorted({str(record["target"]) for record in adc_options})
    detailed_filter_columns = st.columns(3)
    selected_targets = detailed_filter_columns[0].multiselect(
        "靶点",
        target_options,
        key="change_targets",
    )
    source_options = list(change_policy.sources)
    selected_sources = detailed_filter_columns[1].multiselect(
        "来源",
        source_options,
        format_func=lambda source: change_policy.sources[source].display_name,
        key="change_sources",
    )
    event_type_options = list(change_policy.change_types)
    selected_event_types = detailed_filter_columns[2].multiselect(
        "事件类型",
        event_type_options,
        key="change_event_types",
    )
    change_rows = list_changes(
        DEFAULT_DATABASE_PATH,
        days=change_days,
        adc_ids=selected_change_adc_ids,
        targets=selected_targets,
        sources=selected_sources,
        event_types=selected_event_types,
    )
    change_metrics = st.columns(3)
    change_metrics[0].metric("变化事件", len(change_rows))
    change_metrics[1].metric(
        "高严重度",
        sum(1 for event in change_rows if event["severity"] == "high"),
    )
    change_metrics[2].metric(
        "待审核",
        sum(1 for event in change_rows if event["review_required"]),
    )
    if not change_rows:
        st.info("当前时间范围和筛选条件下没有变化事件。")
    for event in change_rows:
        entity_text = "、".join(event["entities"]["adc_names"]) or str(
            event["subject_id"]
        )
        with st.expander(
            f"{event['detected_at']} · {event['event_type']} · {entity_text}",
            expanded=event["severity"] == "high",
        ):
            st.caption(
                f"严重度：{event['severity']} · 来源：{event['source'] or '系统'} · "
                f"审核：{event['review_status']} · 事件 ID：{event['event_id']}"
            )
            value_columns = st.columns(2)
            value_columns[0].markdown("**变化前**")
            value_columns[0].code(_event_value(event["old_value"]))
            value_columns[1].markdown("**变化后**")
            value_columns[1].code(_event_value(event["new_value"]))
            st.write(
                f"关联 ADC：{'、'.join(event['entities']['adc_names']) or '无'}；"
                f"靶点：{'、'.join(event['entities']['targets']) or '无'}；"
                f"来源记录：{event['source_record_id'] or '无'}；"
                f"快照：{event['snapshot_id'] or '无'}"
            )
            if event["snapshot"] and event["snapshot"].get("source_url"):
                st.markdown(
                    f"[打开事件来源快照]({event['snapshot']['source_url']})"
                )

with retrieval_tab:
    st.info("本页只返回可追溯的原始切片，不调用大模型，也不生成总结性答案。")
    engine = retrieval_engine()
    manifest_path = VECTOR_INDEX_PATH / "manifest.json"
    manifest = (
        json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest_path.exists()
        else None
    )
    if manifest:
        st.caption(
            f"向量后端：{manifest['embedding_backend']} · "
            f"模型：{manifest['embedding_model']} · "
            f"切片数：{manifest['chunk_count']}"
        )
    else:
        st.warning("尚未发现向量索引；当前只能使用 BM25。")

    retrieval_query = st.text_input(
        "检索问题",
        placeholder="例如：Dato-DXd 在 TROP2 肿瘤中的 payload 释放机制",
        key="retrieval_query",
    )
    control_columns = st.columns(3)
    modes = ["sparse"] if not engine.dense_available else ["sparse", "hybrid", "dense"]
    mode = control_columns[0].selectbox(
        "检索方式",
        modes,
        format_func={
            "hybrid": "混合检索",
            "dense": "语义向量",
            "sparse": "BM25 关键词",
        }.get,
    )
    source_label = control_columns[1].selectbox(
        "来源筛选",
        ["全部", "ADC 档案", "PubMed", "ClinicalTrials.gov"],
    )
    top_k = control_columns[2].slider("返回条数", 3, 15, 5)
    source_map = {
        "全部": None,
        "ADC 档案": "adc_profile",
        "PubMed": "pubmed",
        "ClinicalTrials.gov": "clinical_trial",
    }

    if st.button("开始检索", type="primary", disabled=not retrieval_query.strip()):
        with st.spinner("正在检索本地索引……"):
            try:
                results = engine.search(
                    retrieval_query,
                    mode=mode,
                    top_k=top_k,
                    source_type=source_map[source_label],
                )
            except RuntimeError as error:
                st.error(str(error))
                results = []
        st.write(f"返回 {len(results)} 个相关切片")
        for result in results:
            display_search_result(result)

with answer_tab:
    st.info(
        "系统先路由问题：ADC 字段、比较、变化和试验直接查询结构化数据；"
        "文献结论才进入检索生成。缺失、冲突或不受支持的内容不会由模型常识补齐。"
    )
    backend_options = configured_generation_backends()
    answer_query = st.text_input(
        "研究问题",
        placeholder="例如：T-DXd 的靶点、payload 和 DAR 分别是什么？",
        key="answer_query",
    )
    with st.expander("高级诊断设置", expanded=False):
        st.caption("这些参数仅影响文献证据路由；结构化查询不会调用生成模型。")
        answer_controls = st.columns(3)
        backend = answer_controls[0].selectbox(
            "文献生成后端",
            backend_options,
            format_func={
                "extractive": "离线证据摘录（无 LLM）",
                "siliconflow": "硅基流动 Chat Completions",
                "openai": "OpenAI Responses API",
            }.get,
        )
        answer_mode = answer_controls[1].selectbox(
            "文献检索方式",
            ["sparse", "hybrid", "dense"],
            format_func={
                "hybrid": "混合检索",
                "dense": "语义向量",
                "sparse": "BM25 关键词",
            }.get,
            key="answer_retrieval_mode",
        )
        answer_top_k = answer_controls[2].slider(
            "证据条数", 3, 8, 5, key="answer_top_k"
        )
        if len(backend_options) == 1:
            st.caption(
                "当前未检测到 SILICONFLOW_API_KEY 或 OPENAI_API_KEY，因此文献路由只启用"
                "确定性离线摘录后端。"
            )

    if st.button(
        "核查并回答",
        type="primary",
        disabled=not answer_query.strip(),
        key="answer_button",
    ):
        with st.spinner("正在检索、检查证据并生成回答……"):
            result = answering_service(backend).answer(
                answer_query,
                retrieval_mode=answer_mode,
                top_k=answer_top_k,
            )
        display_answer_result(result)

with review_tab:
    if PUBLIC_DEMO:
        st.warning(
            "公开演示模式已启用：可查看复核结构，但页面不会建立待审队列或保存人工结论。"
        )
    st.info(
        "本页保存真实人工判断；自动评测只负责建立待审队列，不会自动写入专家结论。"
    )
    current_stats = review_stats(DEFAULT_DATABASE_PATH)
    review_metrics = st.columns(4)
    review_metrics[0].metric("复核项目总数", current_stats["total_items"])
    review_metrics[1].metric("已完成人工复核", current_stats["reviewed_items"])
    review_metrics[2].metric("剩余", current_stats["remaining_items"])
    review_metrics[3].metric("过期结论", current_stats["stale_items"])

    reviewer = st.text_input(
        "复核者标识",
        placeholder="填写姓名缩写或固定代号后保存，例如 reviewer-01",
        key="reviewer_id",
        disabled=PUBLIC_DEMO,
    ).strip()
    reviewer_slot = st.selectbox(
        "本轮复核角色",
        REVIEWER_SLOTS,
        format_func={
            "primary": "第一复核",
            "secondary": "第二独立复核",
            "adjudicator": "分歧裁决",
        }.get,
        key="reviewer_slot",
        disabled=PUBLIC_DEMO,
    )
    review_origin = (
        "human_adjudicated"
        if reviewer_slot == "adjudicator"
        else "human_independent"
    )
    st.caption(
        "来源记录："
        + ("人工裁决" if review_origin == "human_adjudicated" else "独立人工复核")
    )
    filter_columns = st.columns(3)
    item_type_label = filter_columns[0].selectbox(
        "复核对象",
        [
            "全部",
            "检索问题与 gold 文档",
            "生成/拒答结果",
            "三组盲评答案",
            "原子结论",
        ],
        key="review_item_type",
    )
    status_label = filter_columns[1].selectbox(
        "复核状态",
        ["全部", "待复核", "已复核", "结论已过期"],
        key="review_status",
    )
    item_type_map = {
        "全部": None,
        "检索问题与 gold 文档": "retrieval",
        "生成/拒答结果": "generation",
        "三组盲评答案": "benchmark_answer",
        "原子结论": "answer_claim",
    }
    status_map = {
        "全部": "all",
        "待复核": "pending",
        "已复核": "reviewed",
        "结论已过期": "stale",
    }
    selected_item_type = item_type_map[item_type_label]
    run_rows = list_review_runs(
        DEFAULT_DATABASE_PATH,
        item_type=selected_item_type,
    )
    run_labels = {
        str(row["evaluation_run_id"]): (
            f"{row['evaluation_run_id']} · {row['backend']} · "
            f"{row['model_name']} · {row['item_count']}条"
        )
        for row in run_rows
    }
    selected_run = filter_columns[2].selectbox(
        "评测运行",
        ["全部运行", *run_labels],
        format_func=lambda value: run_labels.get(value, value),
        key="review_run_id",
    )
    queue = list_review_items(
        DEFAULT_DATABASE_PATH,
        item_type=selected_item_type,
        evaluation_run_id=None if selected_run == "全部运行" else selected_run,
        status=status_map[status_label],
        reviewer=reviewer,
    )
    if not queue:
        if current_stats["total_items"] == 0:
            st.warning(
                "尚未找到生成或检索评测报告。先运行评测，再执行 "
                "`python -m adc_evidence.review.prepare_review`。"
            )
        else:
            st.success("当前筛选条件下没有待处理项目。")
    else:
        selected_item_id = st.selectbox(
            "选择复核项目",
            [str(item["item_id"]) for item in queue],
            format_func=lambda item_id: next(
                f"[{item['item_type']} · {item['backend']}] "
                f"{item['question_id']} · {item['question']}"
                for item in queue
                if item["item_id"] == item_id
            ),
            key="review_item_id",
        )
        item = next(row for row in queue if row["item_id"] == selected_item_id)
        identity_hidden = bool(item["metadata"].get("identity_hidden"))
        if identity_hidden:
            st.info(
                "当前为身份盲化评审：请先独立保存答案与证据判断；"
                "真实系统和模型只在汇总裁决阶段通过独立身份映射揭示。"
            )
            if item["metadata"].get("second_review_required"):
                st.caption("此题属于双人复核范围，第一、第二复核必须相互独立。")
        if item.get("is_stale"):
            st.warning("系统输出已变化，这条旧人工结论需要重新确认。")
        st.markdown(f"**问题：** {item['question']}")
        expected_documents = list(item["expected_document_ids"])
        system_documents = list(item["system_document_ids"])
        comparison_columns = st.columns(2)
        comparison_columns[0].markdown("**预期 / gold 文档**")
        comparison_columns[0].code(
            "\n".join(expected_documents) or "（应拒答或无 gold 文档）"
        )
        comparison_columns[1].markdown("**系统实际文档**")
        comparison_columns[1].code("\n".join(system_documents) or "（无引用文档）")
        st.caption(
            f"类型：{item['item_type']} · 类别：{item['category']} · "
            f"运行：{item['evaluation_run_id']} · 后端：{item['backend']} · "
            f"模型：{item['model_name']} · 状态：{item['system_status']}"
        )
        if item["item_type"] != "retrieval":
            st.markdown(
                "**待审原子结论**"
                if item["item_type"] == "answer_claim"
                else "**系统回答**"
            )
            st.markdown(str(item["system_output"]))
        else:
            st.caption("检索结果按从上到下的顺序排列；请同时判断问题表述和 gold 文档。")
        review_documents = get_review_documents(
            list(dict.fromkeys([*expected_documents, *system_documents])),
            DEFAULT_DATABASE_PATH,
        )
        external_citations = list(item["metadata"].get("external_citations", []))
        with st.expander("展开核对原始证据", expanded=False):
            if not review_documents and not external_citations:
                st.warning("当前项目数据库中没有找到这些文档。")
            for document in review_documents:
                st.markdown(
                    f"**{document['retrieval_document_id']} · {document['title']}**"
                )
                st.write(document["content"])
                if document["source_url"]:
                    st.markdown(
                        f"[打开来源：{document['retrieval_document_id']}]"
                        f"({document['source_url']})"
                    )
                st.divider()
            for citation in external_citations:
                st.markdown(
                    f"**{citation.get('citation_id') or '网页来源'} · "
                    f"{citation.get('title') or '未命名来源'}**"
                )
                st.write(citation.get("excerpt") or "（没有可显示的网页摘录）")
                if citation.get("source_url"):
                    st.markdown(
                        f"[打开网页来源]({citation['source_url']})"
                    )
                st.divider()
        with st.expander("查看自动评测信号", expanded=False):
            st.json(item["metadata"])

        require_explicit_verdict = identity_hidden and item.get("review_id") is None
        current_question = (
            None
            if require_explicit_verdict
            else str(item.get("question_verdict") or "valid")
        )
        current_evidence = (
            None
            if require_explicit_verdict
            else str(item.get("evidence_verdict") or "correct")
        )
        default_answer = (
            "not_applicable"
            if item["item_type"] == "retrieval" or item["expected_refusal"]
            else "correct"
        )
        current_answer = (
            None
            if require_explicit_verdict
            else str(item.get("answer_verdict") or default_answer)
        )
        default_citation = (
            "correct"
            if item["item_type"] in {"benchmark_answer", "answer_claim"}
            else "not_applicable"
        )
        current_citation = (
            None
            if require_explicit_verdict
            else str(item.get("citation_verdict") or default_citation)
        )
        default_completeness = (
            "correct" if item["item_type"] == "benchmark_answer" else "not_applicable"
        )
        current_completeness = (
            None
            if require_explicit_verdict
            else str(item.get("completeness_verdict") or default_completeness)
        )
        default_refusal = "correct" if item["expected_refusal"] else "not_applicable"
        current_refusal = (
            None
            if require_explicit_verdict
            else str(item.get("refusal_verdict") or default_refusal)
        )
        current_severity = (
            None
            if require_explicit_verdict
            else str(item.get("severity") or "none")
        )
        current_categories = list(item.get("error_categories") or [])
        current_notes = str(item.get("notes") or "")

        with st.form("expert_review_form"):
            verdict_columns = st.columns(2)
            question_verdict = verdict_columns[0].selectbox(
                "问题表述",
                QUESTION_VERDICTS,
                index=(
                    None
                    if current_question is None
                    else QUESTION_VERDICTS.index(current_question)
                ),
                placeholder="请选择",
                format_func={
                    "valid": "有效",
                    "needs_edit": "需修改",
                    "invalid": "无效",
                }.get,
            )
            evidence_verdict = verdict_columns[1].selectbox(
                "gold / 引用证据",
                EVIDENCE_VERDICTS,
                index=(
                    None
                    if current_evidence is None
                    else EVIDENCE_VERDICTS.index(current_evidence)
                ),
                placeholder="请选择",
                format_func={
                    "correct": "正确",
                    "partial": "部分正确",
                    "incorrect": "错误",
                    "not_applicable": "不适用",
                }.get,
            )
            answer_columns = st.columns(2)
            answer_verdict = answer_columns[0].selectbox(
                "答案质量",
                ANSWER_VERDICTS,
                index=(
                    None
                    if current_answer is None
                    else ANSWER_VERDICTS.index(current_answer)
                ),
                placeholder="请选择",
                format_func={
                    "correct": "正确",
                    "partial": "部分正确",
                    "incorrect": "错误",
                    "not_applicable": "不适用",
                }.get,
            )
            refusal_verdict = answer_columns[1].selectbox(
                "拒答是否合理",
                REFUSAL_VERDICTS,
                index=(
                    None
                    if current_refusal is None
                    else REFUSAL_VERDICTS.index(current_refusal)
                ),
                placeholder="请选择",
                format_func={
                    "correct": "合理",
                    "incorrect": "不合理",
                    "not_applicable": "不适用",
                }.get,
            )
            benchmark_columns = st.columns(2)
            citation_verdict = benchmark_columns[0].selectbox(
                "引用对应关系",
                CITATION_VERDICTS,
                index=(
                    None
                    if current_citation is None
                    else CITATION_VERDICTS.index(current_citation)
                ),
                placeholder="请选择",
                format_func={
                    "correct": "正确",
                    "partial": "部分正确",
                    "incorrect": "错误",
                    "not_applicable": "不适用",
                }.get,
            )
            completeness_verdict = benchmark_columns[1].selectbox(
                "多要点完整性",
                COMPLETENESS_VERDICTS,
                index=(
                    None
                    if current_completeness is None
                    else COMPLETENESS_VERDICTS.index(current_completeness)
                ),
                placeholder="请选择",
                format_func={
                    "correct": "完整",
                    "partial": "部分完整",
                    "incorrect": "不完整",
                    "not_applicable": "不适用",
                }.get,
            )
            severity = st.selectbox(
                "问题严重度",
                SEVERITIES,
                index=(
                    None
                    if current_severity is None
                    else SEVERITIES.index(current_severity)
                ),
                placeholder="请选择",
                format_func={
                    "none": "无问题",
                    "low": "低",
                    "medium": "中",
                    "high": "高",
                    "critical": "严重",
                }.get,
            )
            error_categories = st.multiselect(
                "错误分类（可多选）",
                ERROR_CATEGORIES,
                default=current_categories,
            )
            notes = st.text_area(
                "复核依据与修改建议",
                value=current_notes,
                placeholder="记录核对来源、缺失事实或建议修正方式。",
            )
            submitted = st.form_submit_button(
                "保存人工复核",
                type="primary",
                disabled=PUBLIC_DEMO or not reviewer,
            )
        if not reviewer and not PUBLIC_DEMO:
            st.caption("填写复核者标识后才能保存；系统不会生成虚假的专家身份。")
        required_verdicts = (
            question_verdict,
            evidence_verdict,
            answer_verdict,
            citation_verdict,
            completeness_verdict,
            refusal_verdict,
            severity,
        )
        if submitted and not PUBLIC_DEMO and any(
            verdict is None for verdict in required_verdicts
        ):
            st.error("请先完成全部判断字段，再保存本轮复核。")
        elif submitted and not PUBLIC_DEMO:
            save_expert_review(
                item_id=str(item["item_id"]),
                reviewer=reviewer,
                question_verdict=question_verdict,
                evidence_verdict=evidence_verdict,
                answer_verdict=answer_verdict,
                citation_verdict=citation_verdict,
                completeness_verdict=completeness_verdict,
                refusal_verdict=refusal_verdict,
                reviewer_slot=reviewer_slot,
                review_origin=review_origin,
                severity=severity,
                error_categories=list(error_categories),
                notes=notes,
                database_path=DEFAULT_DATABASE_PATH,
            )
            st.success("人工复核已保存。")
            st.rerun()

with st.sidebar:
    st.header("当前版本")
    st.write("v0.6-stage5")
    st.caption(f"数据：{active_version['data_version'][:21]}…")
    st.caption(f"策略：{active_version['policy_version']}")
    git_sha = os.getenv("ADC_GIT_SHA", "").strip()
    if git_sha and git_sha != "unknown":
        st.caption(f"部署提交：{git_sha[:12]}")
    if PUBLIC_DEMO:
        st.caption("公开只读演示模式")
    st.write("数据源：ADC 种子数据、PubMed、ClinicalTrials.gov、ADCdb")
    st.write("当前边界：证据约束回答，不提供个体化医疗建议。")
