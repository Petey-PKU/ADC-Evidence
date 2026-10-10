# 公共 ADC 数据集与 Benchmark v1

## 当前状态

项目当前用于验证“数据构建 → 证据入库 → 检索 → 结构化回答 → 自动回归”的完整链路，状态保持 `not_ready_for_submission`。公开目录和 Benchmark 都是开发/烟雾测试输入，不构成论文语义金标准。

研究范围以 HER2/TROP2 传统 ADC 为主，资料截止日为 `2026-09-18`；公共工程快照使用 `2026-09-30` 目标窗口。目录位于 `data/public/marketed_adc_catalog.csv`，公开 Benchmark 位于 `data/annotations/public_benchmark_v1.jsonl`，其 manifest 绑定题目文件、目录哈希和数据版本。

目录字段使用 `verification_status` 和 `attention_items` 记录自动检查结果。候选来源定位保存 URL、字段、定位信息和支持级别；自动匹配只产生待验证提示，不会把候选值静默写成事实。冲突值保持并列，并在证据卡中显示来源链。

## 构建与审计

```powershell
$env:PYTHONPATH="src"
python scripts/build_public_dataset.py `
  --catalog data/public/marketed_adc_catalog.csv `
  --as-of 2026-09-30 `
  --pubmed-max 1000 `
  --trial-page-size 100 `
  --trial-max-pages 20

python scripts/audit_public_dataset.py `
  --database data/processed/adc_public_2026-09-30.db `
  --output artifacts/evaluation/public_dataset_audit.json
```

构建器只调用公开数据源，不调用生成模型。SQLite、原始响应和质量报告默认写入忽略路径；manifest 记录请求日期、实际窗口、来源运行状态、数量和哈希。`needs_review` 或 `unknown` 只表示自动检查未完成，不能解释为完整覆盖。

对候选 URL 做自动预核验：

```powershell
python scripts/audit_public_catalog_sources.py `
  --catalog data/public/marketed_adc_catalog.csv `
  --candidate-locators data/public/catalog_source_locator_candidates.jsonl `
  --output artifacts/evaluation/public_catalog_source_content_audit.json
```

报告记录 HTTP 状态、内容类型、名称/别名匹配、来源类别和字段级候选定位。`candidate_support_only`、`candidate_locator_pending_verification` 和 `field_level_source_missing` 都是自动诊断标签；只有实际证据进入数据库后，回答服务才会引用它。

## Benchmark v1

运行自动基准：

```powershell
python scripts/validate_public_benchmark.py `
  --questions data/annotations/public_benchmark_v1.jsonl `
  --manifest data/annotations/public_benchmark_v1.manifest.json `
  --catalog data/public/marketed_adc_catalog.csv

python scripts/run_public_benchmark.py `
  --questions data/annotations/public_benchmark_v1.jsonl `
  --database data/processed/adc_public_2026-09-30.db `
  --output artifacts/evaluation/public_benchmark_v1_report.json
```

Benchmark v1 包含 98 道开发/公开 smoke 题，覆盖结构化字段、多 ADC 比较、临床试验、PubMed 证据和安全拒答。每道题包含标准答案、允许答案、证据来源、预期路由、预期状态、部分回答规则和自动评分字段。公开题集标记为 `development_exposed`，只用于可重复回归。

自动指标包括路由准确率、状态覆盖率、答案字段得分、完整答案准确率、证据来源召回率和拒答正确性。文献题允许同一 ADC 的已关联 PubMed 候选集合，用于测试检索覆盖；这不是单一语义金标准。报告中的 `automatic_scoring`、`automatic_validation` 和 paired diagnostics 只用于工程判断。

同库离线基线可关闭结构化路由：

```powershell
python scripts/run_public_benchmark.py `
  --disable-structured-routing `
  --questions data/annotations/public_benchmark_v1.jsonl `
  --database data/processed/adc_public_2026-09-30.db `
  --output artifacts/evaluation/public_benchmark_v1_baseline.json
```

## 下一步

1. 固定目标日期对应的数据库、原始快照 manifest 和检索索引，并重新运行自动基准。
2. 收集自动失败样本，按路由、证据完整性、引用有效性和字段覆盖分类，形成可复现回归集。
3. 保持 `not_ready_for_submission`，直到另行定义并完成正式的投稿证据要求；本项目当前不把人工审核作为运行前提。
