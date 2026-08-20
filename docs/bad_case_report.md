# Bad Case 分析报告

生成时间：`2026-08-20T07:31:59.363652+00:00`
生成评测运行：`legacy`

> 自动规则只用于筛选待复核样本，不等同于领域专家结论。人工结果与自动信号分开统计。

## 摘要

- 自动规则标记：4 条
- 人工复核记录：56 条
- 人工确认 Bad Case：3 条
- 因系统输出变化而过期的人工记录：0 条

## 自动规则标记

| ID | 类型 | 错误分类 | 严重度 | 问题 |
|---|---|---|---|---|
| `gen_pubmed_001` | generation | missing_key_fact | medium | 哪篇 PubMed 文献报告 Dato-DXd 在 TROP2 表达肿瘤中的细胞内转运、DXd 释放和临床前抗肿瘤活性？ |
| `trial_004` | retrieval | low_rank | medium | Dato-DXd、carboplatin 和 pembrolizumab 用于初治 NSCLC 脑转移的单臂 II 期研究是哪项？ |
| `pubmed_001` | retrieval | low_rank | low | 哪篇 PubMed 文献报告 Dato-DXd 在 TROP2 表达肿瘤中的细胞内转运、DXd 释放和临床前抗肿瘤活性？ |
| `pubmed_006` | retrieval | low_rank | low | Dato-DXd 在低分化子宫内膜癌中临床前活性的研究是哪篇？ |

## 人工复核发现

| ID | 复核者 | 错误分类 | 严重度 | 是否过期 | 备注 |
|---|---|---|---|---|---|
| `gen_profile_005` | domain_reviewer_1 | missing_key_fact | medium | 否 | 只回答了研发状态，遗漏 TROP2 和 Topoisomerase I inhibitor |
| `gen_pubmed_001` | domain_reviewer_1 | wrong_source | medium | 否 | 答案引用了能够支持机制描述的 Gold 文档，但第一行将被询问的文献识别为 pubmed:41321283，而预期文献为 pubmed:34413126，存在文献标识混淆。 |
| `gen_trial_001` | domain_reviewer_1 | wrong_source | medium | 否 | 答案引用了能够支持机制描述的 Gold 文档，但系统实际文档中的第二项NCT05911295 不是 II 期，而是 III 期 |

## 建议处理顺序

1. 先复核 `high` 严重度以及拒答、引用错误。
2. 再检查检索低排名样本的实体别名、术语扩展和 gold 文档合理性。
3. 对 `missing_key_fact` 比较原始证据、检索切片与答案，定位是检索还是生成问题。
4. 修复后重新生成评测报告并导入队列；内容哈希变化会提示旧结论已过期。
