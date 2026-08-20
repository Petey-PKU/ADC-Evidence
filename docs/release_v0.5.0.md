# v0.5.0 — Reviewed evaluation milestone

`v0.5.0` 固定了 ADC-Evidence 从真实数据、检索、带引用生成到人工复核与 Bad Case 回归的首个完整闭环。

## 完成内容

- 24 条专家检索问题及 Gold 文档完成单人复核，并重新运行 sparse、dense、hybrid 检索评测。
- 接入 SiliconFlow OpenAI-compatible API，使用 `deepseek-ai/DeepSeek-V4-Flash` 完成 16 条真实模型评测。
- 离线抽取式与 SiliconFlow 两组共 32 条生成结果完成单人复核；主复核队列累计 56/56 完成。
- 人工确认 3 条 Bad Case，并针对缺失关键事实的问题加入回答要求清单和单题回归集。
- 补充环境变量护栏、运行隔离、模型/token/response ID 追踪、复核导出及过期结果识别。
- 完成部署说明、评测文档和公开发布护栏。

## 验证结果

- 单元测试：44/44 通过。
- Streamlit AppTest：0 个异常。
- SiliconFlow 完整评测：16 题、0 API 错误、25,922 tokens。
- 定向真实模型回归：`gen_profile_005` 关键事实召回率由缺项状态提升至 1.0。

## 证据边界

人工结论来自一名药剂学/ADC 领域项目作者的专家复核，尚未进行第二评审者复核或一致性统计。自动指标不能替代人工正确性判断；本系统只做证据约束的信息检索与总结，不提供个体化医疗建议。

公开仓库仅保留汇总指标和方法说明；含评审者标识、本机路径及运行元数据的原始复核快照保存在非公开里程碑中。
