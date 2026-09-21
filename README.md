# ADC-Evidence

ADC-Evidence 是一个面向 ADC 研发信息核查的证据工作台。v0.6.0 研究实现已在
`v0.6.0-research-baseline` 标签冻结，正式对照评测和独立人工复核仍待完成。
现有 120 题已用于后续开发调整，只能作为探索性评测或回归集；确认性结论需要新保留集。
题集编码、测试集使用及自定义数据库绑定的更正见 [题集审计](docs/question_audit_2026-09-12.md)。
已实现的数据、检索、问答和复核流程为：

```text
公开数据源 -> 标准化 -> SQLite -> 文档切片 -> 混合检索 -> 引用约束生成 -> 拒答与评测 -> 人工复核 -> Bad Case -> Docker
```

## 当前功能

- 初始化 SQLite 数据库并导入 10 条 HER2/TROP2 ADC 演示记录；
- 按 ADC 标准名称、别名、靶点或 payload 模糊查询；
- 展示 ADC 组成、研发状态和数据审核状态；
- 提供基础数据统计；
- 重复初始化不会制造重复记录。
- 从 ClinicalTrials.gov API v2 获取临床试验；
- 从 PubMed ESearch/EFetch 获取文献元数据和摘要；
- 对限定 ADC 名单获取 ADCdb 详情快照；
- 建立 ADC、靶点、payload 与文献/试验之间的规则关联；
- 生成来源哈希、证据记录和数据质量报告。
- 将 ADC 档案、PubMed 摘要和临床试验转换为统一可检索文档；
- 使用确定性规则切分文本，并保存文档级和切片级哈希；
- 使用 SQLite FTS5/BM25、384 维多语言 embedding 和精确余弦向量索引；
- 使用 Reciprocal Rank Fusion 提供稀疏、向量和混合检索；
- 提供 24 条草案专家问题及 Hit@K、MRR、nDCG 评测；
- 在 Streamlit 的独立检索页展示可追溯切片，该页面不调用生成模型；
- 将检索证据编号为 `S1...Sn`，生成逐行带引用的回答；
- 对越界、个体化医疗建议、未来预测和证据不足问题执行拒答；
- 生成后校验引用编号、无效引用和逐行引用覆盖率；
- 提供硅基流动 Chat Completions、OpenAI Responses API 和无需 key 的离线摘录基线；
- 提供 16 条生成/拒答评测问题及自动化质量报告。
- 将 24 条检索问题和 16 条生成问题导入可持久化人工复核队列；
- 支持问题、证据、答案、拒答、严重度和错误分类的多维审核；
- 将审核结论与系统输出内容哈希绑定，自动识别过期结论；
- 为每次检索/生成评测分配唯一运行 ID，使离线与远程模型结果并存；
- 记录实际模型、逐题 token usage、response ID 与运行级 token 汇总；
- 将全部待审项目和人工结论导出为 JSONL、CSV 与 SHA-256 manifest；
- 自动生成规则筛选与人工结论分离的 Bad Case JSON/Markdown 报告；
- 提供轻量 Docker demo、可选完整 CPU 检索镜像、Compose 健康检查与 GitHub Actions CI。
- 保存不可变来源快照、时间化原子事实、字段级证据、冲突状态和变化事件；
- 提供互斥、逐来源重试、完整性/数量异常/缺失记录门禁的安全刷新命令；
- 仅更新受影响检索文档和分块，并将向量索引绑定到确定性语料版本；
- 在暂存环境通过门禁后生成发布清单，备份线上库并支持发布失败自动回滚。
- 提供字段级可展开来源、时间、快照、审核状态和历史值的 ADC 证据卡；
- 支持 2～10 个 ADC 的结构化比较、单元格证据以及版本化 CSV/Markdown 导出；
- 提供最近 1/7/30 天变化中心，可按 ADC、靶点、来源和事件类型过滤；
- 导出包含数据/模式/策略/语料版本、字段证据和免责声明的 Evidence Brief。
- 在检索和模型调用前路由结构化事实、比较、变化、试验、文献和拒答任务；
- 将回答拆为带主体、谓词、规范值和证据绑定的原子结论；
- 对结构化值与字段证据执行确定性校验，对文献结论执行逐条文本支持校验；
- 显式返回已回答项与未回答项；冲突、缺失或校验失败时部分回答或拒答。

> 当前数据仅用于开发和界面演示，尚未经过系统文献审核，不能用于科研或临床决策。

研究执行入口见 [冻结记录](docs/release_v0.6_research_baseline.md)和
[研究协议](docs/research_protocol.md)。文档中的历史采集规模与旧版评测汇总不代表当前
运行数据库：仅初始化公开种子会得到 10 个 ADC，正式评测前必须单独确认试验、文献、
快照和历史数据是否存在，并冻结评测数据版本。
无远程模型的同语料对照命令见 [离线对照协议](docs/offline_comparison.md)。

## 环境要求

- Python 3.11 或更高版本
- Windows、macOS 或 Linux

## 安装

建议在项目目录创建虚拟环境：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[rag,generation]"
```

## 初始化数据库

```powershell
python -m adc_evidence.init_db
```

默认生成：

```text
data/processed/adc_evidence.db
```

## 采集真实数据

```powershell
python -m adc_evidence.ingestion.pipeline
```

默认范围：

- ADCdb：10 个指定 ADC 的低频精确查询；
- ClinicalTrials.gov：当前查询命中的全部记录，单页最多 100 条（通过多页游标继续抓取）；
- PubMed：按相关度取前 200 条。

可单独跳过某个来源：

```powershell
python -m adc_evidence.ingestion.pipeline --skip-adcdb
python -m adc_evidence.ingestion.pipeline --skip-trials
python -m adc_evidence.ingestion.pipeline --skip-pubmed
```

原始响应保存在 `data/raw/<run_id>/`，默认不提交 Git。数据库质量报告保存在 `data/processed/data_quality_report.json`。

生产安全刷新应使用暂存、门禁、备份和索引版本绑定的一体化命令：

```powershell
python -m adc_evidence.refresh
```

该命令与参数、退出码、回滚语义见
[`docs/v0.6_stage2_continuous_refresh.md`](docs/v0.6_stage2_continuous_refresh.md)。直接运行采集管线适合本地开发，
不应替代生产发布流程。

启动页面后，“ADC 证据卡”“ADC 比较”和“变化中心”三个标签页直接读取结构化事实与变化
事件，不调用生成模型。阶段 3 的字段状态、导出结构和验收路径见
[`docs/v0.6_stage3_evidence_workbench.md`](docs/v0.6_stage3_evidence_workbench.md)。

“证据问答”会先选择结构化查询或文献检索路径。结构化字段不调用模型，文献生成结论必须
逐条通过直接文本支持校验；完整协议与失败关闭范围见
[`docs/v0.6_stage4_structured_answering.md`](docs/v0.6_stage4_structured_answering.md)。

重新生成质量报告：

```powershell
python -m adc_evidence.processing.quality_report
```

## 启动页面

```powershell
streamlit run src/adc_evidence/app.py
```

## 构建检索索引

```powershell
python -m adc_evidence.rag.build_index
```

首次运行会下载并缓存多语言 MiniLM 模型。只验证流程而不下载模型时可使用：

```powershell
python -m adc_evidence.rag.build_index --backend hashing
```

哈希后端仅供开发测试，不用于语义检索结果展示。

命令行检索：

```powershell
python -m adc_evidence.rag.retriever "Dato-DXd 的 payload 释放机制" --mode hybrid --top-k 5
```

运行检索评测：

```powershell
python -m adc_evidence.rag.evaluate --modes sparse dense hybrid
```

详细设计与指标说明见 `docs/retrieval_design.md` 和 `docs/retrieval_evaluation.md`。公开版保留汇总指标和方法说明；包含评审者标识、本机路径及运行元数据的原始人工复核快照不进入公开仓库。

## 结构化优先证据问答

无需 API key 的结构化字段核查与离线文献演示：

```powershell
python -m adc_evidence.generation.answer "T-DXd 的靶点、载荷和 DAR 是什么？" --backend extractive
```

默认研究流程使用离线抽取式后端，不需要任何模型 API。只有在明确批准远程模型实验时，才将
`.env.example` 复制为 `.env` 并在本地填写：

```text
ADC_LLM_BACKEND=siliconflow
ADC_OFFLINE_ONLY=false
SILICONFLOW_API_KEY=your_key_here
SILICONFLOW_BASE_URL=https://api.siliconflow.cn/v1
SILICONFLOW_MODEL=deepseek-ai/DeepSeek-V4-Flash
```

先只运行一道测试题：

```powershell
python -m adc_evidence.generation.answer "T-DXd 的靶点、载荷和 DAR 是什么？" --backend siliconflow
```

运行生成与拒答评测：

```powershell
python -m adc_evidence.generation.evaluate_generation --backend extractive
python -m adc_evidence.generation.evaluate_generation `
  --backend siliconflow `
  --output artifacts/evaluation/generation_report_siliconflow.json
python -m adc_evidence.review.prepare_review `
  --generation-report artifacts/evaluation/generation_report_siliconflow.json
```

远程模型评测会产生 API 调用费用，只应在单题验证通过后运行。每次新评测都会自动生成 `run_id`；不同运行导入审核队列后不会互相覆盖。完整的 Key 安全、单题验证、常见错误和 OpenAI 可选配置见 `docs/api_configuration.md`；设计与指标说明见 `docs/generation_design.md` 和 `docs/generation_evaluation.md`。

下面的远程模型数字是历史工程记录，不是当前离线研究的投稿结果；它们来自已暴露题集和单人复核，不能作为独立测试或系统优越性的证据。

这些历史复核记录和远程运行产物保存在私有历史快照中，原始导出、评审者标识和本机运行元数据不随公共仓库发布。公共仓库当前没有真实人工金标准；投稿前必须重新提交带 `human_independent` / `human_adjudicated` provenance 的评审文件，并通过 readiness audit。

已完成的硅基流动 `deepseek-ai/DeepSeek-V4-Flash` 真实运行包含 12 次 API 调用：回答成功率、拒答召回、引用有效率与 Gold citation hit 均为 1.0000，关键事实词召回为 0.7639，合计使用 25,922 tokens。单人领域复核确认 11/12 可回答题正确、1/12 部分正确、4/4 拒答合理；唯一确认 Bad Case 是 `gen_profile_005` 遗漏两个关键事实。

针对该 Bad Case，系统新增多字段回答清单和单题回归集。一次独立硅基流动回归完整输出 `TROP2`、`Topoisomerase I inhibitor` 与 `approved`，关键事实召回恢复为 1.0000；该结果只代表单题单次验证，不替代完整重评。修复记录见 `docs/bad_case_fix_gen_profile_005.md`。

私有历史快照中的 56 条主队列曾完成单人复核。离线基线为10/12答案正确、2/12部分正确、4/4拒答合理；真实模型为11/12答案正确、1/12部分正确、4/4拒答合理。离线自动词面召回更高，但人工正确率更低，原因是两条答案混入错误来源。完整比较见 `docs/generation_human_comparison.md`；这些数字不构成公共仓库的独立测试证据。

## 专家复核与 Bad Case

基础检索与离线生成评测构成 40 条审核队列；导入硅基流动运行后，当前队列扩展为 56 条：

```powershell
python -m adc_evidence.review.prepare_review
```

在 Streamlit 的“专家复核”页核对问题、gold 文档、原始证据、答案和拒答。复核完成或模型结果更新后，生成 Bad Case 报告：

```powershell
python -m adc_evidence.review.bad_cases
python -m adc_evidence.review.export_reviews
```

导出命令生成 `expert_reviews.jsonl`、`expert_reviews.csv` 和带文件哈希的 manifest。详细口径见 `docs/expert_review_guide.md`。私有历史快照中的 24 条检索问题曾完成单人复核，问题与 Gold 均通过；自动规则仍标出 3 条检索低排名和 1 条生成关键事实覆盖不足。公共版本只保留方法说明，不把这些历史结果包装成独立人工证据。

## Docker 部署

默认轻量演示版：

```powershell
docker compose up --build
```

需要使用宿主机 MiniLM 索引时构建完整 CPU 版：

```powershell
docker compose -f compose.yaml -f compose.full.yaml up --build
```

默认 demo 镜像已完成实际构建和 HTTP 200 健康检查。完整说明见 `docs/deployment.md`。

京东云单机部署使用独立的 `compose.prod.yaml`。默认只监听
`127.0.0.1:8501`、启用公开只读演示模式，并将数据库、索引和备份保存在代码目录外。
首次安装、SSH 隧道测试和持续更新命令见 `docs/server_deployment.md`。

首次启动时，如果数据库不存在，页面会自动导入演示数据。

## 运行测试

```powershell
python -m unittest discover -s tests -v
```

项目测试使用 Python 标准库 `unittest`，因此即使没有安装 pytest 也能运行。

## 投稿前审计

```powershell
$env:PYTHONPATH="src"
python scripts/audit_paper_readiness.py --output artifacts/evaluation/paper_readiness.json
python scripts/build_public_artifact_manifest.py --output artifacts/evaluation/public_artifact_manifest.json
```

默认审计应返回 `not_ready_for_submission`，直到真实独立人工标签和访问受控的未见 holdout
同时通过；公开 smoke holdout、自动指标和 AI 辅助复核不能替代这两项证据。

若提供真实人工标签，必须同时传入 `--human-review-manifest`；审计会校验标签文件哈希、题号集合哈希、题数、版本和评测窗口。

## 数据说明

`data/sample/adcs.csv` 是项目范围与实体别名的种子数据。`aliases` 字段使用竖线 `|` 分隔多个别名。自动采集证据仍统一标记为 `needs_review`；只有人工复核后才能改为 `reviewed`。

面向公开快照的 ADC 目录位于 `data/public/marketed_adc_catalog.csv`。它与 10 条演示种子分开维护，当前包含 23 条监管批准候选记录；使用 `scripts/build_public_dataset.py` 可在本地生成带文献和试验来源哈希的 SQLite 快照。详细范围、未来截止日处理和 Benchmark v1 见 [`docs/public_dataset_and_benchmark.md`](docs/public_dataset_and_benchmark.md)。

需要验证下载后直接查询的完整快照，可在 GitHub Actions 手动运行
[`Build public dataset release`](.github/workflows/public-release.yml)。工作流会生成并校验
数据库、索引、benchmark、查询程序及配置的压缩包；普通代码 push 不会自动抓取或发布数据。
当前工作流只生成并校验 `research_only` 包，不上传或发布压缩包；完成逐项来源许可核查并提供
v2 redistribution attestation 后，才可在本地生成可再分发包。研究包可解压到独立文件夹，无需另行克隆仓库或重建数据库。按包内
`RELEASE_README.md` 安装 Python 3.11+ 的基础依赖后，运行
`python scripts/run_public_release.py` 启动网页，或使用 `--question` 执行单次查询。
启动器自动选择包内数据，固定使用离线结构化/抽取式回答；首次依赖安装仍需联网，
包内不包含 Python 解释器、依赖 wheel 或生成模型。

## 后续工作

历史阶段 5 记录了 120 题内部评测协议、三组同窗协议、盲评对象、第二复核与裁决规则。
面向公开快照的当前 Benchmark v1 已独立生成 98 道开发/公开 smoke 题，并明确标记为
`development_exposed`；它用于复现和回归检查，不能代替论文的独立人工复核和隐藏测试集。
完整的公共数据范围、下载包和评测门禁见
[公共数据集与 Benchmark 说明](docs/public_dataset_and_benchmark.md)及
[阶段 5 说明](docs/v0.6_stage5_benchmark_review.md)。

v0.6 将项目从带引用问答演示升级为 ADC 证据核查、比较和变化追踪工作台。阶段 0 已固定
[产品范围](docs/v0.6_product_scope.md)、[数据与证据规范](docs/v0.6_data_spec.md)和
[验收门禁](docs/v0.6_acceptance_plan.md)；机器可读来源与冲突策略位于
configs/evidence_policy.json。阶段 1 已实现
[时间化事实与历史数据层](docs/v0.6_stage1_data_layer.md)，在保持现有查询兼容的同时
增加不可变来源快照、字段级事实、跨来源冲突和变化事件；阶段 2～4 已继续完成
[安全持续刷新](docs/v0.6_stage2_continuous_refresh.md)、
[证据工作台](docs/v0.6_stage3_evidence_workbench.md)和
[结构化优先问答与结论验证](docs/v0.6_stage4_structured_answering.md)。
[盲评、对照评测与回归闭环](docs/v0.6_stage5_benchmark_review.md)已把差异化优势转成可审计
的人工作答正确性、证据支持、引用对应、完整性和拒答指标；结果只有在真实三组同窗运行并
完成规定复核后才可发布。
