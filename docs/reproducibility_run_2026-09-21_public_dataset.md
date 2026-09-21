# 公共数据集审计可复现记录（2026-09-21）

本记录把公共快照审计绑定到代码提交、数据库哈希和审计报告哈希，供数据集边界、实体关联和论文方法部分复核。记录只包含公开快照的运行元数据，不包含原始响应、私有数据库、评审身份或受限全文。

## 固定输入

| 项目 | 值 |
|---|---|
| 代码提交 | `fb4b1821bf34547fbde21872492bac6996cb3cb7` |
| 数据库 | `data/processed/adc_public_2026-09-30.db` |
| 数据库 SHA-256 | `sha256:8bae13afacf3fbb7a88bfb5720413a4e1e3524092bed59db1323a6f04f619f40` |
| 审计 schema | `public-adc-dataset-audit-v1` |
| as-of 日期 | `2026-09-30` |
| 带原始快照的审计报告 | `.test_tmp/public_dataset_audit_2026-09-21_with_raw.json` |
| 审计报告 SHA-256 | `d2c4da6fc481528a53649e0b702178b53c26216794cfdb38f33f5d5195758099` |

## 可复现命令

```powershell
$env:PYTHONPATH="src"
python scripts/audit_public_dataset.py `
  --database data/processed/adc_public_2026-09-30.db `
  --as-of 2026-09-30 `
  --raw-root data/raw/public_2026-09-30 `
  --output .test_tmp/public_dataset_audit_2026-09-21_with_raw.json
```

`data/raw/public_2026-09-30` 是本地校验输入，不提交到公共仓库。带 `--raw-root` 的运行只把原始文件哈希用于日期边界检查，不把原始正文或 XML 变成公开发布内容。

## 结果

数据库包含 23 个 ADC、3,503 条 ClinicalTrials.gov 试验、1,410 条 PubMed 文献和 6,754 条实体关联。实体完整性检查通过：没有未知 ADC、未匹配别名、重复逻辑关联或孤立关联；试验和文献记录均有 HTTPS 来源 URL，且每个 ADC 都有至少一条试验和文献关联。关联覆盖仍只描述当前抓取快照，不代表语义金标准或全集覆盖。

来源覆盖状态如下：

| 来源 | 运行状态 | 已采集 / 期望 | 覆盖状态 |
|---|---:|---:|---|
| ClinicalTrials.gov | `partial` | 2,000 / 13,978 | `partial`（`0.143082`） |
| PubMed | `partial` | 1,015 / 165,105 | `partial`（`0.006148`） |
| ADCdb | `skipped` | 0 / 未提供分母 | `unknown` |

记录字段的来源质量仍为 `needs_review`。当前事实字段虽然有候选来源 URL，但尚未完成逐字段、独立的一手来源人工核验，因此不能用于论文中的金标准统计。

日期审计发现 7 条文献的期刊卷期日期晚于 `2026-09-30`。原始快照校验显示其中 6 条有截止日前的电子发表日期，1 条只有截止日前的 PubMed/Entrez 入库日期并带有日期顺序警告；7 条均保留为 `candidate_pending_review`。这一步没有自动改变纳入状态，也没有把索引日期等同于正式发表日期。

## 解释边界

本轮数据集状态是 `partial`，ADCdb 是 `unknown`，字段来源是待复核状态。该运行证明审计程序能够重现当前快照的数量、关联完整性、来源 URL 和日期边界检查；它不能证明数据完整、字段正确、文献相关性成立，也不能替代独立人工评审。下一步仍需完成逐字段一级来源复核、明确历史时间点冻结规则，并将独立评审标签和访问受控 holdout 绑定到正式 benchmark。
