from __future__ import annotations

import json
import os

import streamlit as st

from adc_evidence.config import (
    DEFAULT_DATABASE_PATH,
    PUBLIC_DATABASE_FILENAME,
    VECTOR_INDEX_PATH,
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
)


st.set_page_config(
    page_title="ADC-Evidence",
    page_icon="🧬",
    layout="wide",
)

def ensure_database() -> None:
    if not DEFAULT_DATABASE_PATH.is_file():
        raise FileNotFoundError(
            "The configured public database is missing: "
            f"{DEFAULT_DATABASE_PATH}. Mount or copy the full public snapshot "
            "before starting the app."
        )
    if DEFAULT_DATABASE_PATH.name == PUBLIC_DATABASE_FILENAME:
        stats = database_stats(DEFAULT_DATABASE_PATH)
        if (
            stats["adc_count"] <= 10
            or stats["document_count"] == 0
            or stats["trial_count"] == 0
        ):
            raise RuntimeError(
                "The configured public database does not look like the v0.7 "
                "public snapshot. Check ADC_DATABASE_PATH before starting."
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
            f"来源状态：{field['review_status']} · 当前证据：{field['evidence_count']} 条"
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
                    f"来源状态：{evidence['review_status']}"
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
        st.error("至少一个非空字段缺少完整来源、时间或来源状态，不应作为可发布核查结果。")
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

st.title("ADC-Evidence")
st.caption("v0.7：连接完整公共快照的证据卡、比较、变化、检索与自动证据校验")
st.warning(
    "页面展示可追溯来源与自动校验结果；请在使用前核对原始来源，系统不提供个体化医疗或投资建议。"
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
) = st.tabs(
    [
        "ADC 证据卡",
        "ADC 比较",
        "变化中心",
        "证据检索",
        "证据问答",
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
    st.info("所有非空字段均来自结构化事实层；可展开查看来源、时间、快照和来源状态。")
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
                            f"{evidence['observed_at']} · 来源状态：{evidence['review_status']}"
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
    change_metrics = st.columns(2)
    change_metrics[0].metric("变化事件", len(change_rows))
    change_metrics[1].metric(
        "高严重度",
        sum(1 for event in change_rows if event["severity"] == "high"),
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
                f"来源状态：{event['review_status']} · 事件 ID：{event['event_id']}"
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

with st.sidebar:
    st.header("当前版本")
    st.write("v0.7.0-public-snapshot")
    st.caption(f"数据：{active_version['data_version'][:21]}…")
    st.caption(f"策略：{active_version['policy_version']}")
    git_sha = os.getenv("ADC_GIT_SHA", "").strip()
    if git_sha and git_sha != "unknown":
        st.caption(f"部署提交：{git_sha[:12]}")
    st.write("数据源：公共 ADC 快照（PubMed、ClinicalTrials.gov、ADCdb）")
    st.write("当前边界：证据约束回答，不提供个体化医疗建议。")
