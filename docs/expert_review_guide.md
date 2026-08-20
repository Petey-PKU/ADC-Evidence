# 专家人工复核 SOP

## 目标与边界

人工复核用于验证问题表述、gold 文档、系统引用、答案事实和拒答决策。自动指标只能帮助排序，不能替代领域判断。当前队列初始包含 40 条项目，人工复核计数从 0 开始。

## 开始复核

```powershell
python -m adc_evidence.review.prepare_review
streamlit run src/adc_evidence/app.py
```

打开“专家复核”标签页，填写固定复核者代号，并使用“评测运行”筛选器选择需要审核的检索、离线生成或远程模型运行。每位复核者对同一运行中的同一项目保留一条最新记录；不同运行和不同复核者互不覆盖。

新模型报告使用独立文件并显式导入：

```powershell
python -m adc_evidence.generation.evaluate_generation `
  --backend siliconflow `
  --output artifacts/evaluation/generation_report_siliconflow.json
python -m adc_evidence.review.prepare_review `
  --generation-report artifacts/evaluation/generation_report_siliconflow.json
```

## 判断顺序

1. 判断问题是否清晰、在 ADC 项目范围内、是否存在时间或适用范围歧义。
2. 展开原始证据，检查 gold 文档是否真的支持问题，并按链接回到 PubMed 或 ClinicalTrials.gov 原始页面。
3. 对检索项目，检查 gold 文档排名和前列结果的相关性。
4. 对生成项目，逐条核对答案事实是否被引用证据支持、是否漏掉问题要求的事实。
5. 对拒答项目，判断拒答理由是否合理；不要因为系统语气保守就自动判为正确。
6. 选择严重度与错误分类，在备注中写出可复现依据后保存。

## 字段口径

- `问题表述`：问题本身及 gold 标注是否可用于评测。
- `gold / 引用证据`：预期文档和系统引用对问题的支持程度。
- `答案质量`：答案是否正确、完整、无超出证据的推断。
- `拒答是否合理`：只在应该拒答或系统实际拒答时使用。
- `严重度`：`high/critical` 应留给会明显误导科研判断、引用错误或安全边界失效的问题。
- `错误分类`：可多选，用于后续按根因聚合，而不是按表面措辞分类。

## 复核完成后的命令

```powershell
python -m adc_evidence.review.bad_cases
python -m adc_evidence.review.export_reviews
```

Bad Case 结果分别写入 `artifacts/evaluation/bad_case_report.json` 和 `docs/bad_case_report.md`。审核导出包含 JSONL、可用 Excel 打开的 UTF-8 BOM CSV，以及记录数量和 SHA-256 的 manifest。建议每完成一个审核批次就重新导出并备份。

新评测拥有独立 `run_id`，不会覆盖旧运行。如果使用相同 `run_id` 重跑并改变了输出，原审核会显示为“过期”，需要重新确认。

## 建议的首轮工作量

先复核自动规则标出的 4 条候选 Bad Case，再复核 4 条拒答样本，最后覆盖其余问题。单人首轮可按每条 2～5 分钟预留约 2～3 小时。若用于正式 benchmark，建议再增加一位独立复核者并计算一致性；当前 MVP 不伪造这一步。
