# 数据来源与采集边界

当前公开快照（2026-09-13）包含 23 个 ADC、3,503 条试验和 1,410 篇 PubMed 文献，
其中 1,366 篇含摘要。两类采集均设上限，状态为 `partial`；这些数量不能解释为完整覆盖。
目标窗口 `2026-09-30` 尚未到达，不能视为已完成该日期的收录。
实际快照哈希及验证结果见[可复现性运行记录](reproducibility_run_2026-09-13.md)，
当前构建参数与使用方式见[公开数据集说明](public_dataset_and_benchmark.md)。

下列各来源中的“历史范围”来自 2026-08-19 的运行记录，不是当前数据库的实时统计。
公开种子初始化只导入 ADC 演示档案；正式研究运行须检查实际数据库的覆盖、来源快照和
历史观测，并记录新的数据版本。当前 `data/processed/data_quality_report.json` 与提交的
公开 demo-seed 数据库一致；旧的采集规模保存在
`data/processed/data_quality_report_historical_2026-08-20.json`，只能作为历史快照。

## ClinicalTrials.gov

- 接口：`https://clinicaltrials.gov/api/v2/studies`
- 版本：通过 `https://clinicaltrials.gov/api/v2/version` 记录 `dataTimestamp`
- 格式：JSON
- 历史范围：10 个种子 ADC 名称组成的查询；当时命中 833 条并全部保存
- 更新方式：重新运行采集管线，以 `nct_id` 幂等更新

## PubMed

- 接口：NCBI E-utilities 的 ESearch 与 EFetch
- 格式：ESearch JSON、EFetch XML
- 历史范围：ADC 名称、HER2/TROP2 及 ADC 主题组合查询，按相关度保存前 200 条；成功解析 199 篇
- 请求标识：`tool=adc_evidence_mvp`，可通过 `.env` 配置 `NCBI_EMAIL` 和 `NCBI_API_KEY`
- 注意：PubMed 摘要可能受版权保护，本项目保存的批量原始响应不提交 Git，也不作为可再分发语料发布

## ADCdb

- 页面：`https://adcdb.idrblab.net/`
- 当前未发现文档化公开 API 或全库下载入口
- 历史范围：只对当时的 10 个 ADC 做低频、精确名称查询，不做全站镜像；当前公开构建默认不采集 ADCdb
- 保存内容：搜索页 HTML、详情页 HTML、SHA-256、ADCdb ID 和解析字段
- 历史精确匹配结果：8/10；`MRG002` 和 `SHR-A1921` 当时未获得同名结果，因此不建立 ADCdb 外部 ID
- 风险控制：解析器按结果中的 ADC Name 精确匹配，绝不直接采用页面第一条结果

## 可追溯性

每个来源记录至少保存：

- 来源名称和来源记录 ID；
- 获取时间；
- 来源 URL；
- 原始文件路径；
- SHA-256；
- 数据集版本或时间戳。

自动规则生成的证据状态统一为 `needs_review`。
