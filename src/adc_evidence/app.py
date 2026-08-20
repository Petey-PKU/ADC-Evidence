from __future__ import annotations

import json
import os

import streamlit as st

from adc_evidence.config import (
    DEFAULT_DATABASE_PATH,
    DEFAULT_SEED_PATH,
    GENERATION_REPORT_PATH,
    RETRIEVAL_REPORT_PATH,
    VECTOR_INDEX_PATH,
    environment_flag,
)
from adc_evidence.database import (
    create_database,
    database_stats,
    initialize_database,
    search_adcs,
)
from adc_evidence.generation.generators import (
    configured_generation_backends,
    create_generator,
)
from adc_evidence.generation.service import EvidenceAnsweringService
from adc_evidence.rag.retriever import HybridRetriever
from adc_evidence.review.repository import (
    ANSWER_VERDICTS,
    ERROR_CATEGORIES,
    EVIDENCE_VERDICTS,
    QUESTION_VERDICTS,
    REFUSAL_VERDICTS,
    SEVERITIES,
    get_review_documents,
    list_review_items,
    list_review_runs,
    prepare_review_queue,
    review_stats,
    save_expert_review,
)


st.set_page_config(
    page_title="ADC-Evidence",
    page_icon="🧬",
    layout="wide",
)

PUBLIC_DEMO = environment_flag("ADC_PUBLIC_DEMO", default=False)


def ensure_database() -> None:
    create_database(DEFAULT_DATABASE_PATH)
    if database_stats(DEFAULT_DATABASE_PATH)["adc_count"] == 0:
        initialize_database(DEFAULT_DATABASE_PATH, DEFAULT_SEED_PATH)


def ensure_review_queue() -> None:
    prepare_review_queue(
        database_path=DEFAULT_DATABASE_PATH,
        generation_report_path=GENERATION_REPORT_PATH,
        retrieval_report_path=RETRIEVAL_REPORT_PATH,
        retrieval_mode="sparse",
    )


def display_record(record: dict[str, object]) -> None:
    title = str(record["adc_name"])
    aliases = str(record.get("aliases") or "")
    if aliases:
        title = f"{title}（{aliases}）"

    with st.expander(title, expanded=True):
        left, middle, right = st.columns(3)
        left.metric("靶点", str(record["target"]))
        middle.metric("Payload", str(record.get("payload_name") or "未记录"))
        dar_value = record.get("dar")
        right.metric("DAR", str(dar_value) if dar_value is not None else "未记录")

        details = {
            "抗体": record.get("antibody") or "未记录",
            "Linker": record.get("linker_name") or "未记录",
            "Linker 类型": record.get("linker_type") or "未记录",
            "Payload 类型": record.get("payload_class") or "未记录",
            "适应证": record.get("indication") or "未记录",
            "研发状态": record.get("development_status") or "未记录",
            "企业": record.get("company") or "未记录",
            "数据审核状态": record.get("data_review_status") or "未记录",
        }
        for label, value in details.items():
            label_column, value_column = st.columns([1, 3])
            label_column.markdown(f"**{label}**")
            value_column.write(str(value))

        source_url = record.get("source_url")
        if source_url:
            st.link_button("查看当前参考入口", str(source_url))


@st.cache_resource
def retrieval_engine() -> HybridRetriever:
    return HybridRetriever(DEFAULT_DATABASE_PATH, VECTOR_INDEX_PATH)


@st.cache_resource
def answering_service(backend: str) -> EvidenceAnsweringService:
    return EvidenceAnsweringService(
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
    if result.status == "answered":
        st.success("回答已通过引用完整性校验")
        st.markdown(result.answer)
        validation = result.validation
        metric_columns = st.columns(3)
        metric_columns[0].metric("引用来源", len(result.citations))
        metric_columns[1].metric(
            "引用覆盖率",
            f"{validation.coverage:.0%}" if validation else "未校验",
        )
        metric_columns[2].metric("耗时", f"{result.latency_ms} ms")
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
                    st.link_button("打开原始来源", citation.source_url)
        if result.usage:
            st.caption(f"模型 token 用量：{result.usage}")
    elif result.status == "refused":
        st.warning(f"系统拒答：{result.answer}")
        st.caption(f"拒答原因代码：{result.refusal_reason}")
        if result.validation and not result.validation.valid:
            st.caption(
                f"引用校验：覆盖率 {result.validation.coverage:.0%}；"
                f"无效引用 {', '.join(result.validation.invalid_ids) or '无'}"
            )
    else:
        st.error(result.answer)
        st.caption(f"错误类型：{result.refusal_reason}")


ensure_database()
if not PUBLIC_DEMO:
    ensure_review_queue()

st.title("ADC-Evidence")
st.caption("阶段 8：ADC 证据检索、带引用问答、人工复核与 Bad Case 闭环")
st.warning(
    "自动采集数据与检索结果尚未经过系统人工审核，不能用于科研结论、临床或投资决策。"
)

stats = database_stats(DEFAULT_DATABASE_PATH)
stat_columns = st.columns(3)
stat_columns[0].metric("ADC 记录", stats["adc_count"])
stat_columns[1].metric("靶点数量", stats["target_count"])
stat_columns[2].metric("标记为已批准", stats["approved_count"])

evidence_columns = st.columns(3)
evidence_columns[0].metric("PubMed 文献", stats["document_count"])
evidence_columns[1].metric("临床试验", stats["trial_count"])
evidence_columns[2].metric("证据记录", stats["evidence_count"])

st.divider()
database_tab, retrieval_tab, answer_tab, review_tab = st.tabs(
    [
        "ADC 结构化数据",
        "证据检索",
        "带引用问答",
        "专家复核（只读）" if PUBLIC_DEMO else "专家复核",
    ]
)

with database_tab:
    query = st.text_input(
        "查询 ADC",
        placeholder="输入标准名称、别名、靶点或 payload，例如 T-DXd、HER2、DXd",
    )
    records = search_adcs(DEFAULT_DATABASE_PATH, query)
    st.write(f"找到 {len(records)} 条记录")

    if not records:
        st.info("没有找到匹配记录。可以尝试 HER2、TROP2、T-DXd、Trodelvy 或 DXd。")
    else:
        for adc_record in records:
            display_record(adc_record)

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
        "回答只能使用当前数据库检索到的证据；证据不足、问题越界或引用校验失败时会拒答。"
    )
    backend_options = configured_generation_backends()
    answer_query = st.text_input(
        "研究问题",
        placeholder="例如：T-DXd 的靶点、payload 和 DAR 分别是什么？",
        key="answer_query",
    )
    answer_controls = st.columns(3)
    backend = answer_controls[0].selectbox(
        "生成后端",
        backend_options,
        format_func={
            "extractive": "离线证据摘录（无 LLM）",
            "siliconflow": "硅基流动 Chat Completions",
            "openai": "OpenAI Responses API",
        }.get,
    )
    answer_mode = answer_controls[1].selectbox(
        "检索方式",
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
            "当前未检测到 SILICONFLOW_API_KEY 或 OPENAI_API_KEY，因此只启用"
            "确定性离线摘录后端。配置任一 key 并重启页面后会出现对应选项。"
        )

    if st.button(
        "生成带引用回答",
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
    filter_columns = st.columns(3)
    item_type_label = filter_columns[0].selectbox(
        "复核对象",
        ["全部", "检索问题与 gold 文档", "生成/拒答结果"],
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
        if item["item_type"] == "generation":
            st.markdown("**系统回答**")
            st.markdown(str(item["system_output"]))
        else:
            st.caption("检索结果按从上到下的顺序排列；请同时判断问题表述和 gold 文档。")
        review_documents = get_review_documents(
            list(dict.fromkeys([*expected_documents, *system_documents])),
            DEFAULT_DATABASE_PATH,
        )
        with st.expander("展开核对原始证据", expanded=False):
            if not review_documents:
                st.warning("当前项目数据库中没有找到这些文档。")
            for document in review_documents:
                st.markdown(
                    f"**{document['retrieval_document_id']} · {document['title']}**"
                )
                st.write(document["content"])
                if document["source_url"]:
                    st.link_button(
                        f"打开来源：{document['retrieval_document_id']}",
                        str(document["source_url"]),
                    )
                st.divider()
        with st.expander("查看自动评测信号", expanded=False):
            st.json(item["metadata"])

        current_question = str(item.get("question_verdict") or "valid")
        current_evidence = str(item.get("evidence_verdict") or "correct")
        default_answer = (
            "not_applicable"
            if item["item_type"] == "retrieval" or item["expected_refusal"]
            else "correct"
        )
        current_answer = str(item.get("answer_verdict") or default_answer)
        default_refusal = "correct" if item["expected_refusal"] else "not_applicable"
        current_refusal = str(item.get("refusal_verdict") or default_refusal)
        current_severity = str(item.get("severity") or "none")
        current_categories = list(item.get("error_categories") or [])
        current_notes = str(item.get("notes") or "")

        with st.form("expert_review_form"):
            verdict_columns = st.columns(2)
            question_verdict = verdict_columns[0].selectbox(
                "问题表述",
                QUESTION_VERDICTS,
                index=QUESTION_VERDICTS.index(current_question),
                format_func={
                    "valid": "有效",
                    "needs_edit": "需修改",
                    "invalid": "无效",
                }.get,
            )
            evidence_verdict = verdict_columns[1].selectbox(
                "gold / 引用证据",
                EVIDENCE_VERDICTS,
                index=EVIDENCE_VERDICTS.index(current_evidence),
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
                index=ANSWER_VERDICTS.index(current_answer),
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
                index=REFUSAL_VERDICTS.index(current_refusal),
                format_func={
                    "correct": "合理",
                    "incorrect": "不合理",
                    "not_applicable": "不适用",
                }.get,
            )
            severity = st.selectbox(
                "问题严重度",
                SEVERITIES,
                index=SEVERITIES.index(current_severity),
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
        if submitted and not PUBLIC_DEMO:
            save_expert_review(
                item_id=str(item["item_id"]),
                reviewer=reviewer,
                question_verdict=question_verdict,
                evidence_verdict=evidence_verdict,
                answer_verdict=answer_verdict,
                refusal_verdict=refusal_verdict,
                severity=severity,
                error_categories=list(error_categories),
                notes=notes,
                database_path=DEFAULT_DATABASE_PATH,
            )
            st.success("人工复核已保存。")
            st.rerun()

with st.sidebar:
    st.header("当前版本")
    st.write("v0.5.0-reviewed")
    git_sha = os.getenv("ADC_GIT_SHA", "").strip()
    if git_sha and git_sha != "unknown":
        st.caption(f"部署提交：{git_sha[:12]}")
    if PUBLIC_DEMO:
        st.caption("公开只读演示模式")
    st.write("数据源：ADC 种子数据、PubMed、ClinicalTrials.gov、ADCdb")
    st.write("当前边界：证据约束回答，不提供个体化医疗建议。")
