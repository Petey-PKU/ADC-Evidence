# 公共 ADC 数据集与 Benchmark v1

## 当前发布状态

公共目录位于 `data/public/marketed_adc_catalog.csv`，包含 23 个截至
2026-06-30 已有监管批准记录的 ADC 候选（包括 2 个历史撤回记录）。在 2026-09-13
构建的本地快照中，目录扩展为 23 个 ADC、1,750 条 ClinicalTrials.gov 试验和 998
篇 PubMed 文献，其中 956 篇含摘要。请求的 `2026-09-30` 是未来目标窗口，因此本次
清单将 `as_of_status` 标为 `future_target_pending`，不把未来日期当作已观察数据。

本目录是可审阅的公共种子，字段仍标为 `primary_check_pending`。每个字段在公开发布前
必须绑定监管标签、注册库记录或其他一手来源；当前目录的总览来源只是范围参考，不能
直接充当人工金标准。私有 SQLite、原始响应、评审身份和评审导出不会复制到本目录。

## 构建流程

```powershell
$env:PYTHONPATH="src"
$env:HTTP_PROXY="http://127.0.0.1:7890"   # 仅在本机需要代理时设置
$env:HTTPS_PROXY="http://127.0.0.1:7890"
python scripts/build_public_dataset.py `
  --catalog data/public/marketed_adc_catalog.csv `
  --as-of 2026-09-30 `
  --pubmed-max 1000 `
  --trial-page-size 1000 `
  --trial-max-pages 10
```

命令只调用公开数据源，不调用生成模型。SQLite、原始响应和质量报告默认写入
`data/processed` 与 `data/raw` 的忽略路径；manifest 记录请求日期、实际数据窗口、
来源运行状态、数量和哈希。PubMed 结果可能因解析或来源使用限制而不适合直接再分发，
所以发布前应按记录检查许可证，必要时只发布 PMID、标题、摘要 URL 和哈希。

构建器还会生成 `literature_topics` 表，按 `literature-topic-rule-v1` 对标题和摘要做透明的
词法初筛，主题包括 `mechanism`、`efficacy` 和 `safety`。表中保存命中的词、规则版本和
`needs_review` 状态；它用于组织检索和人工复核队列，不代表论文相关性的最终判断。

构建索引时必须指定同一个数据库，避免把演示库和公共快照混在一起：

```powershell
python -m adc_evidence.rag.build_index `
  --database data/processed/adc_public_2026-09-30.db `
  --index-path artifacts/vector_index/public_2026-09-30 `
  --backend hashing
```

启动 Streamlit 时设置 `ADC_DATABASE_PATH`、`ADC_SEED_PATH` 和
`ADC_VECTOR_INDEX_PATH`，即可直接使用该快照。结构化问题和离线摘录路径不调用远程
生成模型；索引中的本地 hashing 后端只用于可复现开发，语义检索可按许可下载本地
embedding 模型后重新构建。

## Benchmark v1

`scripts/build_public_benchmark.py` 从公共快照生成
`data/annotations/public_benchmark_v1.jsonl` 及其 manifest。本轮生成 86 道公开开发/烟
雾测试题，覆盖：

- 结构化 ADC 字段；
- 多 ADC 比较；
- NCT 试验状态和阶段；
- PubMed 文献证据；
- 证据不足、个体化治疗和预测类拒答。

每道题都包含：标准答案、允许答案、证据来源、题目类型、允许部分回答、是否应拒答、
自动评分字段和人工评分占位。当前 `human_scoring.status` 全部为 `pending`，因此该
文件只能作为公开开发集和可重复 smoke benchmark，不能支持独立人工准确率或顶会论文
主结论。

文献题的自然语言问题是“给出一篇直接相关文献”，公开 smoke 集因此允许每个 ADC 最多
50 篇已关联 PubMed 候选中的任意一篇，并在 `evidence_sources` 和 `allowed_answers` 中
完整列出候选。这种策略用于检验检索覆盖，不等同于严格的单一金标准；论文测试集必须
由人工逐题确认候选集合和相关性。

Benchmark 还包含一小组机制、疗效和安全性主题题，来源是同一快照中的词法初筛标签，
用于验证主题路由是否能找到相应证据。主题标签和候选文献都必须经过人工相关性复核。

Benchmark 的自动指标包括路由准确率、状态覆盖率、答案字段准确率、证据来源召回率和
拒答正确性。论文主指标还需要至少两名独立复核者按照相同评分表评估答案、证据、引用、
完整性和拒答合理性，并保存独立标签与裁决记录。

可用 `scripts/prepare_public_benchmark_review.py` 从 benchmark 和运行报告生成逐题复核包；
复核包会保留系统原文、claims、引用和 gold 证据，并将所有 verdict 留空。它只准备复核
材料，不会把自动结果标记为人工结果。

## 下一步冻结规则

1. 在 `2026-09-30` 或实际目标日期重新运行目录，记录当时来源版本，并逐字段完成一手
   来源核验。
2. 由未参与实现的人员从公共数据库抽取开发题，另建访问受控的最终测试题；公开题集
   不得再被称为 unseen holdout。
3. 对每个测试题完成双人独立评审和必要的第三方裁决，再计算配对差值、95% CI、
   McNemar 检验和多重比较校正。
4. 固定数据库、题集、检索预算、实现版本和统计计划后，运行 ADC-Evidence、离线 RAG
   基线以及经许可的外部基线。
