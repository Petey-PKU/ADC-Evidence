# 2026-09-20 公共来源候选审计记录

本记录对应公共分支 `research/v0.6-freeze` 的提交
`54f4d87661acc7427885a10144b6f4f4bc323a60`。本轮只更新公开来源候选和复核包的边界，
没有写入人工 verdict，也没有把来源可访问性当作人工核验。

## 输入与哈希

| 项目 | 值 |
|---|---|
| 代码提交 | `54f4d87661acc7427885a10144b6f4f4bc323a60` |
| 目录 | `sha256:97a21b0f104ee530783c1aa367cc28f95643680e82c54e6e57f83d5f195e692c` |
| 来源候选 JSONL（统一 LF 后） | `sha256:f7ae2435215948d1d56cae7b35ba4b9523851f64aac0d6cbc4c61bbf697a1a81` |
| 包内数据库（去除本机路径后） | `sha256:2f9a5c53f49bbc23a883b0863a1c5577510ac5004ca47cfad106d40794dc819a` |
| benchmark manifest | `sha256:41fd2884722e0c19516f13601df5bd82230dadd87e17c9044c42cb1ec364d7a9` |
| 检索语料版本 | `corpus_bf154bd752280b20b6ea0ad9cab8dde06e65062276209ae655bf27de49efc1ca` |
| 本轮离线 ZIP SHA-256 | `sha256:d2e7bc7cf3379619ddcc1b899ace2dbbe76ef56dda4b8120300a35d1feccc3fc` |

## 本轮数据审计决定

- 来源候选由 112 个 ADC-字段组合、114 条候选组成；每条仍为
  `pending_independent_primary_source_review`。
- SKB264 的字段候选补充了同行评议原始研究的结构定位；抗体名称没有从来源中推断为
  Sacituzumab 同义词。
- SHR-A1811 保留目录 DAR 5.7 和原始研究 DAR 6 的差异；5.7 尚未在所列摘要中获得支持。
  `SHR169265`、`rezetecan` 和目录 `SHR9265` 的对应关系也留待复核，不直接等同。
  来源定位见 [PLOS 原始研究](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0326691)
  与 [NCI 药物词典](https://www.cancer.gov/publications/dictionaries/cancer-drug/def/trastuzumab-rezetecan)。
- 复核包的 Python API 默认不加载公共候选文件；只有显式传入候选路径时才绑定候选，
  且候选文件中的 ADC 与字段必须属于传入目录。这样测试目录不会误接真实公共线索。

## 验证结果

```powershell
$env:PYTHONPATH="src"
python -m unittest discover -s tests
python scripts/audit_public_hygiene.py --output .test_tmp/hygiene-source-audit.json
python scripts/package_public_release.py `
  --database data/processed/adc_public_2026-09-30.db `
  --index artifacts/vector_index/public_2026-09-30 `
  --catalog data/public/marketed_adc_catalog.csv `
  --catalog-audit data/public/marketed_adc_catalog.audit.json `
  --scope-policy data/public/catalog_scope_policy.json `
  --candidate-locators data/public/catalog_source_locator_candidates.jsonl `
  --benchmark-manifest data/annotations/public_benchmark_v1.manifest.json `
  --benchmark-questions data/annotations/public_benchmark_v1.jsonl `
  --output .test_tmp/adc-public-54f4d87.zip
python scripts/verify_public_release.py .test_tmp/adc-public-54f4d87.zip
```

- 初次全量验证：执行 `213` 项，其中 `209` 项通过，`4` 项因可选模型依赖未安装而跳过；
  当时尚未加入随后补充的缺失文件和错配候选回归测试。最终工作区测试结果见下文。
- 公共卫生扫描：`208` 个受跟踪文件，`status=clean`，无发现。
- 复核包：`299` 个字段项，`299` 个仍为 pending，`review_ready=false`；候选计数为 `114`。
- 发布包：`status=verified`，检查 `79` 个文件，数据库绝对本机路径计数为 `0`，
  benchmark 和候选来源文件均存在。

这些结果证明代码、数据清单和离线包的一致性；它们不证明字段已经过独立人工确认，
也不构成临床金标准或论文主结果。

## 实体关联审计

使用同一数据库运行：

```powershell
$env:PYTHONPATH="src"
python scripts/audit_public_dataset.py `
  --database data/processed/adc_public_2026-09-30.db `
  --output artifacts/evaluation/public_dataset_audit.json
```

本次审计得到 23 个 ADC、3,503 条试验、1,410 篇文献和 6,754 条实体关联；23 个 ADC
均有至少一条试验和文献关联，孤立试验/文献关联均为 `0`。这只说明当前快照中的
链接完整性，不等于领域全集覆盖。

来源运行仍是 `partial`：ClinicalTrials.gov 最新运行抓取 2,000/13,978 条，PubMed
抓取 1,015/165,105 条；ADCDB 本次为 `skipped`。因此报告状态保持 `partial`，不计算
“文献覆盖率”或“试验覆盖率”作为全集比例；后续需在固定日期窗口下补齐或明确受限来源，
并保留每次运行的去重、时间窗口和实体链接清单。

审计还会验证实体别名是否存在于 `entity_aliases`、逻辑记录是否有重复链接、以及试验/文献
来源 URL 和日期字段。当前快照的别名校验通过，逻辑重复链接为 `0`，3,503 条试验和
1,410 篇文献的来源 URL 均为 HTTPS；文献日期有 `7` 条晚于 `2026-09-30`，所以日期范围
状态为 `needs_review`。这些晚日期记录不能被静默纳入目标窗口，需在下一次固定窗口重建或
逐条标注为超出窗口。

## 收尾校正与复验

收尾检查纠正了上表候选文件重排后的哈希，并明确数据库哈希指包内去除本机路径后的版本。
原始本地数据库 SHA-256 为 `8bae13afacf3fbb7a88bfb5720413a4e1e3524092bed59db1323a6f04f619f40`。
这些字节哈希与审核包统一换行后的文本哈希有不同用途，不应混用。

命令行入口也已实施目录隔离：公共默认目录自动加载公共候选，其他目录需显式指定匹配文件。
新增回归测试覆盖相同 ADC ID 的自定义目录不会加载公共线索，以及显式候选正常加载。
SKB264 候选备注同时改为指向“先前候选名称”，避免误称目录抗体字段就是 Sacituzumab。
本次候选文件统一 LF 后 SHA-256 为
`8d7c1b048995c29565b9b79c6c136ace87ac9b404ef48cdf49faaf7ea430aeb2`。

最终本地全量执行 `216` 项：`212` 项通过、`4` 项跳过、`0` 项失败。
重新生成并校验公共复核包得到 `299` 个待复核项、`114` 条候选，`review_ready=false`。
上表 ZIP 是 `54f4d87` 的历史验证包，未包含本节的后续改动；正式发布仍需重新构建和许可核查。
