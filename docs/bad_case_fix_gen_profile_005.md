# `gen_profile_005` Bad Case 修复记录

## 原始问题

问题要求同时回答 Dato-DXd 的靶点、payload class 和研发状态。原始硅基流动运行
`gen-20260820T053131Z-336d063c` 命中正确 Gold 文档，引用校验通过，但答案只给出
“已批准”这一项。`domain_reviewer_1` 将其判定为：

- 答案质量：`partial`；
- 严重度：`medium`；
- 错误分类：`missing_key_fact`；
- 遗漏事实：`TROP2`、`Topoisomerase I inhibitor`。

这说明根因位于生成完整性，而不是检索、Gold 或引用格式。

## 最小修复

生成输入现在会从问题中提取可识别的回答项，并写入独立的
`<answer_requirements>` 清单。系统指令要求模型逐项覆盖清单；任一要求缺少直接证据时
必须拒答，不能静默省略。该机制面向靶点、payload、payload class、DAR、linker、
研发/招募状态、注册号、试验阶段、终点和文献识别等常见 ADC 问题字段，不针对某个
药物名称写死答案。

同时新增：

- `data/annotations/generation_regression_questions.jsonl` 单题回归集；
- 评测命令的 `--questions` 参数；
- 回答项提取和显式清单的自动化测试。

## 回归结果

离线回归和硅基流动真实回归的 `key_fact_recall` 均为 `1.0000`。真实回归运行 ID 为
`gen-20260820T065045Z-dc865953`，只调用一次模型，使用 1,929 tokens；回答为：

```text
- 靶点：TROP2 [S1]
- 载荷类型：Topoisomerase I inhibitor [S1]
- 研发状态：已获批（approved）[S1]
```

该回答命中 `adc_profile:adc_007`，引用校验通过，三个要求均被覆盖。报告保存在
`artifacts/evaluation/generation_regression_siliconflow.json`，SHA-256 为
`83282DA4296EA1E4B06AEDC93E437B5B745C078C2DE3F8542693BB6BE4E86F97`。

## 结论边界

本次结果证明已确认 Bad Case 在一次真实回归中消失，但单题、单次采样不能证明整体
16 题均改善，也不能排除模型输出波动。旧运行、旧人工结论和原 Bad Case 保留不变；
如需声明修复具有稳定性，应增加重复运行或重新执行完整评测，并建立新的独立人工复核
记录。
