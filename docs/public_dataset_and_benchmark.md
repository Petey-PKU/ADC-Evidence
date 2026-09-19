# 公共 ADC 数据集与 Benchmark v1

## 当前发布状态

公共目录位于 `data/public/marketed_adc_catalog.csv`，包含 23 个截至
2026-06-30 已有监管批准记录的 ADC 候选（包括 1 个历史撤回记录）。在 2026-09-13
构建的本地快照中，目录扩展为 23 个 ADC、3,503 条 ClinicalTrials.gov 试验和 1,410
篇 PubMed 文献，其中 1,366 篇含摘要；23 个 ADC 均至少有一条文献实体关联。请求的 `2026-09-30` 是未来目标窗口，因此本次
清单将 `as_of_status` 标为 `future_target_pending`，不把未来日期当作已观察数据。

本目录是可审阅的公共种子，字段仍标为 `primary_check_pending`。每个字段在公开发布前
必须绑定监管标签、注册库记录或其他一手来源；当前目录的总览来源只是范围参考，不能
直接充当人工金标准。私有 SQLite、原始响应、评审身份和评审导出不会复制到本目录。

范围边界由 `data/public/catalog_scope_policy.json` 声明：核心集合只计入传统
`antibody_drug_conjugate`；`photoimmunoconjugate` 和 `recombinant_immunotoxin`
作为扩展模态单独报告。当前目录的核心/扩展数量为 21/2。分类本身仍是
`provisional_pending_primary_source_review`，不能替代结构字段的一手来源复核。

## 构建流程

```powershell
$env:PYTHONPATH="src"
$env:HTTP_PROXY="http://127.0.0.1:7890"   # 仅在本机需要代理时设置
$env:HTTPS_PROXY="http://127.0.0.1:7890"
python scripts/build_public_dataset.py `
  --catalog data/public/marketed_adc_catalog.csv `
  --as-of 2026-09-30 `
  --pubmed-max 1000 `
  --trial-page-size 100 `
  --trial-max-pages 20
```

命令只调用公开数据源，不调用生成模型。SQLite、原始响应和质量报告默认写入
`data/processed` 与 `data/raw` 的忽略路径；manifest 记录请求日期、实际数据窗口、
来源运行状态、数量和哈希。PubMed 结果可能因解析或来源使用限制而不适合直接再分发，
所以发布前应按记录检查许可证，必要时只发布 PMID、标题、摘要 URL 和哈希。

可对本地快照生成不含记录正文的去重、实体链接、字段事实覆盖和来源完整性审计：

```powershell
$env:PYTHONPATH="src"
python scripts/audit_public_dataset.py `
  --database data/processed/adc_public_2026-09-30.db `
  --output artifacts/evaluation/public_dataset_audit.json
```

审计会将计划中的抓取上限记录为 `partial`，不会把部分 PubMed 结果解释为全集覆盖；
`link_coverage_by_adc`、`missing_trial_link_adc_ids`、`missing_document_link_adc_ids` 和
`orphan_link_counts` 用于发现实体关联缺口，
不会把没有关联记录的 ADC 静默计入文献或试验覆盖率。
其中 `adc_fact_provenance` 的 `source_types=["curated_seed"]` 只表示字段已绑定候选来源
链接；只有后续人工确认并记录为相应一级来源类型，才可用于论文中的金标准统计。
审计还输出 `adc_fact_source_quality`，对当前字段 evidence 的空 URL 和通用首页 URL
计数；`adc_fact_source_quality_status=needs_review` 时，不能把该快照当作字段来源已核验。
数据库可能保留多次采集尝试。审计报告同时保留 `source_runs` 历史，并按
`finished_at`/`started_at` 选择每个来源的 `latest_source_runs`；`incomplete_sources`
只根据最新一次运行判断，避免把旧的失败尝试误读成当前快照状态。

可对候选 URL 做一次带超时的内容预核验（不修改目录字段，也不生成人工 verdict）：

```powershell
$env:PYTHONPATH="src"
$env:HTTP_PROXY="http://127.0.0.1:7890"
$env:HTTPS_PROXY="http://127.0.0.1:7890"
python scripts/audit_public_catalog_sources.py `
  --catalog data/public/marketed_adc_catalog.csv `
  --output artifacts/evaluation/public_catalog_source_content_audit.json
```

报告只记录 HTTP 状态、内容类型、ADC 名称/别名是否出现在响应文本中、来源类别和字段评估。
`candidate_support_only` 是待人工定位的线索，`field_level_source_missing` 表示目录的单一
候选 URL 尚不能支持结构字段；自动匹配永远不计入金标准。2026-09-13 的实际运行结果为
23 行均返回 HTTP 响应（21 行为 200、1 行为 403、1 行为 412），16 行文本出现名称/别名，
161 个结构字段仍缺字段级来源；PDF 只记录可访问性，不自动提取正文；
状态为 `triage_only_pending_human_source_locator_review`。

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
发布包的示例配置同时设置 `ADC_OFFLINE_ONLY=true` 和
`ADC_LLM_BACKEND=extractive`，确保下载者不配置 API 也能运行。

如果要提供“下载后直接查询”的版本，可运行 `scripts/package_public_release.py`。脚本会
先验证 SQLite 与向量索引的 retrieval corpus 版本一致，再生成包含数据库、索引、公开目录、
benchmark 题集与 manifest、查询程序、必要配置、README 和 SHA-256 清单的 v2 外部发布包；这些二进制文件不会进入
Git 仓库。包内还包含 `marketed_adc_catalog.audit.json`，列出缺失字段、通用监管入口页和
待做的一级来源核验，不把待核验记录伪装成金标准。
打包前还会逐条比较 SQLite 与目录中重叠的 ADC 字段；如果数据库仍是旧来源或旧值，打包会
直接失败，避免发布包中的可查询数据库与目录清单不一致。

程序只从已被 Git 跟踪的公开 Python 源码和明确列出的运行配置打包，并执行文本卫生检查；
本地 `.env`、缓存、未跟踪源码和其他配置不会自动进入发布包。manifest 的 `application`
记录代码提交、工作区是否存在改动、实际数据库/目录/索引路径和 Python 要求；所有程序
文件也进入 SHA-256 清单。开发时打包的脏工作区不能被报告为对应提交的原样发布。

将 v2 压缩包解压到独立文件夹后，按 `RELEASE_README.md` 创建 Python 3.11+ 虚拟环境，
执行 `python -m pip install -e .` 安装基础依赖，再运行：

```powershell
python scripts/run_public_release.py --check
python scripts/run_public_release.py --question "T-DXd 的靶点和载荷是什么？"
python scripts/run_public_release.py
```

最后一条命令启动本机网页 `http://127.0.0.1:8501`。启动器不依赖调用者所在目录，自动选择
解压包内的数据，并强制离线抽取式配置。无需另行克隆代码、采集数据或下载模型；首次
Python 依赖安装需要联网或自行提供依赖 wheel。发布包未捆绑 Python 解释器和第三方依赖。

公共仓库还提供手动触发的 `.github/workflows/public-release.yml`。在 GitHub Actions 中输入
快照日期和抓取上限后，它会在干净的 Ubuntu runner 上重建数据库、hashing 索引和 benchmark，
执行脱敏、语料版本绑定及发布包校验，并将 zip 作为 Actions artifact 提供下载。工作流只有
`workflow_dispatch` 入口，不会因普通代码 push 自动抓取或发布数据；下载者仍应先检查包内的
`RELEASE_MANIFEST.json` 和来源许可。
`RELEASE_MANIFEST.json` 还记录数据库中的 ADC、试验、文献、摘要覆盖率、主题标签数量和
最近采集运行状态；本地快照当前为 `partial`，因为 ClinicalTrials.gov 与 PubMed 均设置了抓取上限，当前数据库分别包含 3,503 和 1,410 条记录。
打包过程会对 SQLite 副本中的本机绝对路径做脱敏，原始数据库不会被修改；发布包不含原始
响应文件，因此无法用这些路径恢复本地采集缓存。

下载者可以在解压前检查发布包：

```powershell
python scripts/verify_public_release.py artifacts/releases/adc-public-2026-09-30.zip
```

只有输出 `status: verified` 且 `checked_file_count` 与发布清单一致时，才应把数据库和索引
接入应用。

## Benchmark v1

`scripts/build_public_benchmark.py` 从公共快照生成
`data/annotations/public_benchmark_v1.jsonl` 及其 manifest。本轮生成 98 道公开开发/烟
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

Benchmark 的自动指标包括路由准确率、状态覆盖率、答案字段平均得分、完整答案准确率、
证据来源召回率和拒答正确性。允许部分回答的题目按字段比例给分；不允许部分回答的题目
必须全部满足标准答案才得分。论文主指标还需要至少两名独立复核者按照相同评分表评估答案、证据、引用、
完整性和拒答合理性，并保存独立标签与裁决记录。

可用 `scripts/prepare_public_benchmark_review.py` 从 benchmark 和运行报告生成逐题复核包；
复核包会保留系统原文、claims、引用和 gold 证据，并将所有 verdict 留空。它只准备复核
材料，不会把自动结果标记为人工结果。

公开 runner 加上 `--disable-structured-routing` 可运行同一数据库、同一索引和同一问题集的
离线 RAG baseline；该选项只关闭结构化路由，便于做配对消融，不引入第二个数据源。
随后可用 `scripts/compare_public_benchmark.py` 计算逐题配对差值和按类别差值；这仍是
自动诊断，并附带 bootstrap 置信区间与精确 McNemar p 值；论文主结论需要在隐藏题集上
完成独立人工评分和预注册统计检验。

一次可复现的 2026-09-13 离线诊断及其输入哈希记录在
[`public_benchmark_diagnostics_2026-09-13.md`](public_benchmark_diagnostics_2026-09-13.md)。

## 下一步冻结规则

1. 在 `2026-09-30` 或实际目标日期重新运行目录，记录当时来源版本，并逐字段完成一手
   来源核验。
2. 由未参与实现的人员从公共数据库抽取开发题，另建访问受控的最终测试题；公开题集
   不得再被称为 unseen holdout。
3. 对每个测试题完成双人独立评审和必要的第三方裁决，再计算配对差值、95% CI、
   McNemar 检验和多重比较校正。
4. 固定数据库、题集、检索预算、实现版本和统计计划后，运行 ADC-Evidence、离线 RAG
   基线以及经许可的外部基线。
