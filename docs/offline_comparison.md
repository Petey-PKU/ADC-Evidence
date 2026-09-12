# 同语料离线对照

当前不需要使用远程模型。为了检验结构化路由和字段校验的增量作用，项目提供一个普通
RAG 对照：两组共享同一数据库副本、题集、sparse 检索、top-k=5 和确定性
`ExtractiveGenerator`，对照组关闭结构化路由、结构化字段查询和字段级校验。

这不是“普通 RAG 的准确率”或“系统优越性”证明。它只能显示两种工程路径在同一输入上
产生的状态、路由、引用和程序诊断差异。语义正确性、证据充分性、引用对应和拒答合理性
仍需独立人员复核。

## 命令

```powershell
$env:PYTHONIOENCODING='utf-8'
$env:PYTHONPATH='src'
.venv/Scripts/python.exe -m adc_evidence.evaluation.benchmark run-system `
  --window-id OFFLINE_WINDOW `
  --database PATH_TO_FROZEN_DATABASE `
  --output PATH_TO_SYSTEM_REPORT

.venv/Scripts/python.exe -m adc_evidence.evaluation.benchmark run-offline-baseline `
  --window-id OFFLINE_WINDOW `
  --database PATH_TO_FROZEN_DATABASE `
  --output PATH_TO_BASELINE_REPORT

.venv/Scripts/python.exe -m adc_evidence.evaluation.benchmark compare-offline `
  --system-report PATH_TO_SYSTEM_REPORT `
  --baseline-report PATH_TO_BASELINE_REPORT `
  --output PATH_TO_COMPARISON
```

三个命令的 `OFFLINE_WINDOW`、数据库、题集哈希和 prompt 版本必须一致。私有数据库的
报告、答案、引用和比较结果必须写在私有评测目录；不要将其复制到公开仓库。

## 解释规则

比较输出按题目类别给出预期状态匹配率、回答比例、错误数和配对状态/路由计数。它不从
`required_terms` 自动推导医学正确率，也不把结构化系统的拒答直接视为普通 RAG 的错误。
系统若覆盖更多字段，可能提高回答覆盖；对照若回答更多题，也可能引入没有证据的结论。
这两个方向都必须由评审者按同一评分表判断。

旧 120 题已经参与实现调试，当前只属于开发暴露数据。确认性比较需要另建独立保留集，
在揭盲前锁定数据、题目、检索预算、实现版本和统计计划。
