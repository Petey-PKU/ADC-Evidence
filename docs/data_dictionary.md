# 数据字典（阶段 0～1）

| 字段 | 含义 | 是否必填 |
|---|---|---|
| adc_id | 项目内部稳定标识 | 是 |
| adc_name | ADC 标准名称 | 是 |
| aliases | 别名列表，CSV 中使用 `|` 分隔 | 否 |
| target | 标准化靶点名称 | 是 |
| antibody | 抗体名称或说明 | 否 |
| linker_name | Linker 名称或说明 | 否 |
| linker_type | `cleavable`、`non-cleavable` 或 `unknown` | 是 |
| payload_name | Payload 名称 | 否 |
| payload_class | Payload 机制分类 | 否 |
| dar | Drug-to-antibody ratio，允许缺失 | 否 |
| indication | 当前演示适应证 | 否 |
| development_status | `approved`、`investigational`、`discontinued` 或 `unknown` | 是 |
| company | 研发企业 | 否 |
| source_url | 当前参考入口，后续替换为字段级证据 | 否 |
| data_review_status | `needs_review` 或 `reviewed` | 是 |

## 阶段 2～3 新增表

| 表 | 用途 | 主键 |
|---|---|---|
| ingestion_runs | 记录每次采集参数、状态和汇总 | run_id |
| source_records | 原始来源、文件路径、版本和 SHA-256 | source + source_record_id |
| documents | PubMed 文献元数据和摘要 | document_id |
| trials | ClinicalTrials.gov 标准化试验记录 | nct_id |
| entity_links | ADC/靶点/payload 与文献、试验的关联 | 组合主键 |
| external_identifiers | ADC 与 ADCdb ID 等外部标识的映射 | 组合主键 |
| evidence | 字段级或记录级证据 | evidence_id |
| entity_aliases | 实体标准名、别名和标准化别名 | 组合主键 |

所有列表字段在 SQLite 中以 JSON 文本保存；例如 `phases_json`、`interventions_json` 和 `authors_json`。
