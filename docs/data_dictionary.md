# 数据字典（阶段 0～1）

本文描述 v0.5 及更早版本的单值档案和采集表。v0.6 的时间化事实、字段级来源、冲突和
变化事件规范以 [v0.6 数据与证据规范](v0.6_data_spec.md) 为准。

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

## v0.6 时间化事实与持续刷新表

| 表 | 用途 | 主键 |
|---|---|---|
| schema_versions | 记录已经应用的数据库模式版本 | version |
| source_snapshots | 保存内容寻址、不可变的来源快照元数据 | snapshot_id |
| facts | 保存原子事实的当前、历史和冲突版本 | fact_id |
| fact_evidence | 把事实版本绑定到来源快照及字段位置 | fact_evidence_id |
| change_events | 保存字段变化、冲突、采集失败和记录缺失事件 | event_id |
| ingestion_source_runs | 保存一次采集中每个来源的状态、数量和完整性 | run_id + source |
| source_run_records | 保存来源运行的完整记录 ID 清单 | run_id + source + source_record_id |

ingestion_source_runs.status 表示采集是否按配置范围完成；is_complete 表示结果是否覆盖来源的
完整查询集合。只有连续两个 status=complete 且 is_complete=1 的运行才允许据此生成
source.record_missing。详细发布门禁见
[v0.6 阶段 2：持续采集与安全增量发布](v0.6_stage2_continuous_refresh.md)。
