# 生成质量评测报告

离线基线评测日期：2026-08-19；硅基流动评测与单人复核日期：2026-08-20。

## 评测集

`data/annotations/generation_questions.jsonl` 包含 16 条草案问题：

- 12 条可回答问题：6 条 ADC 档案、4 条临床试验、2 条 PubMed；
- 4 条应拒答问题：越界问题、个体化医疗建议、未来预测、不存在实体。

每条可回答问题包含 gold document 和关键事实词；拒答问题包含预期拒答类型。2026-08-20，16 条问题、12 条 Gold 证据和 4 条拒答预期均完成 `domain_reviewer_1` 单人领域复核，标注状态更新为 `expert_reviewed`。

## 离线基线结果

后端：`deterministic-extractive-v1`；检索：BM25 sparse；Top K：5。

| 指标 | 结果 |
| --- | ---: |
| 可回答问题成功率 | 1.0000 |
| 拒答精确率 | 1.0000 |
| 拒答召回率 | 1.0000 |
| 错误拒答率 | 0.0000 |
| 引用格式与覆盖有效率 | 1.0000 |
| Gold citation hit rate | 1.0000 |
| Grounded answer rate | 1.0000 |
| 关键事实词召回 | 0.9722 |
| 运行错误率 | 0.0000 |
| 平均延迟 | 约 6～7 ms |

上述结果衡量的是确定性规则基线和工程管线，不代表 LLM 的自然语言质量。部分字段路由和摘录规则与本评测集共同开发，因此结果存在明显的开发集偏差。

## 硅基流动真实模型结果

2026-08-20 使用硅基流动 `deepseek-ai/DeepSeek-V4-Flash` 完成 16 题真实评测。运行 ID 为 `gen-20260820T053131Z-336d063c`；12 道可回答问题实际调用模型，4 道拒答问题由本地护栏处理。

| 指标 | 结果 |
| --- | ---: |
| 可回答问题成功率 | 1.0000 |
| 拒答精确率 | 1.0000 |
| 拒答召回率 | 1.0000 |
| 错误拒答率 | 0.0000 |
| 引用格式与覆盖有效率 | 1.0000 |
| Gold citation hit rate | 1.0000 |
| Grounded answer rate | 1.0000 |
| 关键事实词召回 | 0.7639 |
| 运行错误率 | 0.0000 |
| 全部问题平均延迟 | 10,891 ms |
| API 调用数 | 12 |
| Token 用量 | 输入 18,209；输出 7,713；合计 25,922 |

`key_fact_recall` 是严格词面匹配：模型使用“III 期”代替 `PHASE3`、使用“已撤回”代替 `WITHDRAWN` 时会被判为未命中。因此 6 条自动 `missing_key_fact` 不能直接等同于 6 条事实错误。

## 硅基流动结果人工复核

`domain_reviewer_1` 已逐条复核本次运行，16 条记录均未过期：

- 16/16 问题有效；
- 12/12 可回答题的 Gold/引用证据正确，4 条拒答题证据项不适用；
- 11/12 可回答题答案正确，1/12 部分正确；
- 4/4 拒答均合理；
- 唯一人工确认 Bad Case 为 `gen_profile_005`：答案只给出研发状态，遗漏靶点 `TROP2` 与 payload class `Topoisomerase I inhibitor`，判定 `partial / medium / missing_key_fact`。

其余 5 条自动 `missing_key_fact` 未被人工确认：4 条临床试验题属于中英文等价表达导致的词面低估；`gen_pubmed_001` 虽未显式输出 PMID，但以准确标题和引用文档完成了文献识别，人工判定答案正确。人工结果说明自动指标适合筛选候选，而不能直接替代语义判断。

## 已确认 Bad Case 的定向回归

针对 `gen_profile_005`，生成输入新增显式多字段回答清单，并增加单题回归集和
`--questions` 评测参数。硅基流动真实回归运行 `gen-20260820T065045Z-dc865953`
逐项输出 `TROP2`、`Topoisomerase I inhibitor` 和 `approved`，关键事实词召回、引用
有效率与 Gold 命中率均为 `1.0000`；单次调用使用 1,929 tokens。完整修复记录见
`docs/bad_case_fix_gen_profile_005.md`。

该结果是单题、单次自动回归，不宣称整个 16 题运行已重新验证；旧运行和人工 Bad Case
继续保留作为审计记录。

## 离线与真实模型人工对比

离线16条结果也已完成单人复核：10/12可回答题正确、2/12部分正确、4/4拒答合理。
两条确认 Bad Case 均为 `wrong_source`：`gen_pubmed_001` 混淆文献标识，
`gen_trial_001` 混入另一项III期试验。完整对比见
`docs/generation_human_comparison.md`。

这与自动指标形成反差：离线关键事实词召回为0.9722，高于真实模型的0.7639，但人工
完整正确率为83.3%，低于真实模型的91.7%。词面指标没有惩罚离线答案同时混入的错误
来源，因此必须与人工语义判断结合使用。

本次报告保存在 `artifacts/evaluation/generation_report_siliconflow.json`，独立 Bad Case 报告保存在 `artifacts/evaluation/bad_case_report_siliconflow.json` 和 `docs/bad_case_report_siliconflow.md`。真实 Key 仅存在于 Git 忽略的本地 `.env`，不进入报告。

复现命令：

```powershell
python -m adc_evidence.generation.evaluate_generation `
  --backend siliconflow `
  --output artifacts/evaluation/generation_report_siliconflow.json
python -m adc_evidence.review.prepare_review `
  --generation-report artifacts/evaluation/generation_report_siliconflow.json
```

每次运行自动生成唯一 `run_id`。报告顶层记录请求模型、实际观察模型、API 调用次数和 token 汇总；每题记录模型、usage 与 response ID。导入审核队列时，`run_id` 会成为项目 ID 的一部分，因此远程模型结果不会覆盖离线基线。需要完全可复现的固定名称时，也可显式传入 `--run-id`。

真实模型人工复核重点检查：

- 引用是否在语义上真正支持对应事实；
- 是否遗漏关键限定条件；
- 是否把临床前证据写成临床结论；
- 证据冲突时是否表达不确定性；
- 应拒答问题是否稳定拒答。
