# 研究范围与截止日期核验（2026-09-18）

本记录将论文主研究范围固定为 HER2/TROP2 ADC 研发信息，截止日期固定为
`2026-09-18`。机器可读版本见
[`configs/research_cutoff_2026-09-18.json`](../configs/research_cutoff_2026-09-18.json)。

## 主张范围

论文主结果只覆盖 `configs/evidence_policy.json` 中的 HER2/TROP2 目标和传统
`antibody_drug_conjugate`。公开目录中的 21 个核心 ADC 可以作为补充数据审计；
`photoimmunoconjugate` 与 `recombinant_immunotoxin`（目录中的两个扩展模态）不进入
主结果。字段范围为：

- ADC：`target`、`antibody`、`linker_name`、`linker_type`、`payload_name`、
  `payload_class`、`dar`、`indication`、`development_status`、`company`；
- 临床试验：状态、阶段、疾病、干预、主要终点、入组数、开始日期和完成日期；
- 文献：标题、摘要、发表日期和出版类型。

这些字段是评测对象的范围定义，不代表当前字段已经完成一级来源人工确认。

## 已核验的冲突

当前公开目录候选定位仍有三组竞争值，不能自动选一个作为金标准：

| ADC | 字段 | 候选值 | 当前处理 |
|---|---|---|---|
| `adc_016` | `dar` | `5.7` / `6` | 保留两值，等待一级来源裁决 |
| `adc_016` | `payload_name` | `SHR9265` / `rezetecan` | 核对结构命名和产品来源 |
| `adc_019` | `payload_name` | `DGN549` / `DGN549C` / `FGN849` | 区分偶联物、连接子-载荷复合物和释放组分 |

完整候选队列包含 23 个目录条目的 299 个 ADC-字段审核项，当前仍为
`pending_primary_check`；候选来源定位不能替代独立人工审核。见[字段审核队列](catalog_field_review_queue_2026-09-21.md)。

## 2026-09-18 日期边界结果

使用当前本地公开数据库运行日期审计时，记录规模为 23 个 ADC、3,503 条试验、1,410
篇文献和 6,754 条实体关联。来源覆盖仍是 ClinicalTrials.gov `partial`、PubMed
`partial`、ADCdb `unknown`，ADC 事实来源质量为 `needs_review`。因此这些数量只能描述
当前抓取快照，不能表示全集覆盖。

按 `2026-09-18` 审计文献日期，发现 7 条卷期日期晚于截止日：6 条有截止日前的电子发表
日期，1 条只有截止日前的 PubMed/Entrez 入库证据并带日期顺序警告。7 条均保持
`candidate_pending_review`。试验最后更新时间的最大值为 `2026-09-11`，在截止日内。

这次审计只检查日期边界，**没有把标记为 `2026-09-30` 的数据库还原成历史数据库**。
正式论文结果前仍需按 9 月 18 日重新冻结原始快照、数据库、索引和 manifest，并绑定
同一版本的独立 holdout。

## 当前结论

截止日期和主研究字段已经明确，冲突集合已经显式登记；但正式结果仍被以下事项阻塞：

1. 生成真正的 2026-09-18 cutoff-specific 数据库、原始快照清单和匹配索引；
2. 完成用于论文主张的字段一级来源人工复核；
3. 完成独立 holdout 的双人评分、分歧裁决和人工 manifest。
