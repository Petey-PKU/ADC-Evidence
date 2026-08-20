# 检索系统设计

## 范围

阶段 4～6 只负责找出相关、可追溯的原始证据切片，不调用大模型，也不生成科研结论。

```text
SQLite 原始实体
  -> 统一 retrieval_documents
  -> 可复现 text_chunks
  -> FTS5/BM25 稀疏索引
  -> 多语言 MiniLM embedding
  -> NumPy 精确余弦向量索引
  -> RRF 混合排序
  -> 专家问题集与检索指标
```

## 文档结构

`retrieval_documents` 将三种来源映射为统一字段：

| source_type | 内容 | 文档 ID 示例 |
| --- | --- | --- |
| `adc_profile` | ADC 组成、靶点、DAR、适应证和别名 | `adc_profile:adc_001` |
| `pubmed` | 标题、摘要、期刊和发表日期 | `pubmed:34413126` |
| `clinical_trial` | 标题、状态、分期、疾病、干预、终点和日期 | `trial:NCT04879329` |

每份文档保存来源 URL、内容哈希和实体元数据。`text_chunks` 保存确定性切片 ID、所属文档、序号、字符数、内容哈希和同一份元数据，因此检索结果可以回溯到原始文档。

## 切分策略

- 默认上限 1,200 字符、重叠 160 字符；
- 优先按换行和中英文句末标点切分；
- 超长单句才使用固定宽度切分；
- ADC 结构化档案通常保持为一个切片；
- 文档和切片 ID 均为确定性 ID，重复构建不会制造重复记录。

## 三种检索模式

1. `sparse`：SQLite FTS5 的 BM25。中文问题先做一个很小、可审计的药剂学术语扩展，例如“载荷”扩展为 `payload/warhead/cytotoxic`。
2. `dense`：`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`，输出归一化的 384 维向量；矩阵保存在 `artifacts/vector_index/embeddings.npy`。
3. `hybrid`：对 BM25 和向量结果使用 Reciprocal Rank Fusion。首版问题集以精确药名、试验名和 NCT 号为主，因此默认权重为 sparse:dense = 6:1。

当前只有 1,366 个切片，NumPy 精确余弦检索足够快，也没有独立向量数据库的部署成本。数据规模显著增加后再考虑 FAISS、Qdrant 或 pgvector。

## 评测定义

问题集位于 `data/annotations/retrieval_questions.jsonl`，共 24 条：10 条 ADC 档案、7 条临床试验和 7 条 PubMed 文献。每条记录包含问题、期望文档 ID、类别和复核状态；2026-08-20 首轮领域复核后均标记为 `expert_reviewed`。

当前使用文档级指标：

- Hit@1/3/5/10：前 K 个去重文档中是否至少出现一份相关文档；
- MRR@10：第一份相关文档排名倒数；
- nDCG@10：考虑相关结果排名位置的归一化折损累计增益。

这批问题同时用于首版调试和权重选择，不是独立盲测集，因此结果只能作为工程基线。下一版应由领域专家复核问题与 gold document，并拆分 dev/test。
