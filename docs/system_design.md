# 阶段 0～1 系统设计

## 用户与问题

目标用户是希望快速查询 ADC 基础组成和研发状态的研发人员。当前阶段仅验证软件流程，不提供科研结论。

## 输入

ADC 标准名称、别名、靶点或 payload 的搜索词。

## 输出

匹配 ADC 的抗体、linker、payload、DAR、适应证、研发状态、企业及数据审核状态。

## 数据流

```text
data/sample/adcs.csv
    -> Pydantic 字段校验
    -> SQLite adcs / adc_aliases
    -> 查询函数
    -> Streamlit 页面
```

## 阶段 2～3 数据流

```text
ClinicalTrials.gov JSON ─┐
PubMed JSON/XML ─────────┼─> 原始快照 + SHA-256
ADCdb HTML ──────────────┘          |
                                  v
                           来源专用解析器
                                  |
                                  v
                     实体标准化 + 规则关联
                         |                |
                         v                v
                  documents/trials   evidence/links
                         \                /
                          └── SQLite ────┘
```

## 当前阶段边界

当前包含真实公开数据、规则型实体关联和证据追踪，但不包含 RAG、语义向量检索、模型预测或临床建议。所有自动证据都需要人工复核。
