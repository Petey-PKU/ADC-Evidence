# 2026-09-20 公共来源候选审计记录

本记录对应公共分支 `research/v0.6-freeze` 的提交
`54f4d87661acc7427885a10144b6f4f4bc323a60`。本轮只更新公开来源候选和复核包的边界，
没有写入人工 verdict，也没有把来源可访问性当作人工核验。

## 输入与哈希

| 项目 | 值 |
|---|---|
| 代码提交 | `54f4d87661acc7427885a10144b6f4f4bc323a60` |
| 目录 | `sha256:97a21b0f104ee530783c1aa367cc28f95643680e82c54e6e57f83d5f195e692c` |
| 来源候选 JSONL | `sha256:143b4a31abc949face0f3bc7a73d2f4ae242e01b31cc71e15c0453c396fac0d1` |
| 数据库 | `sha256:2f9a5c53f49bbc23a883b0863a1c5577510ac5004ca47cfad106d40794dc819a` |
| benchmark manifest | `sha256:41fd2884722e0c19516f13601df5bd82230dadd87e17c9044c42cb1ec364d7a9` |
| 检索语料版本 | `corpus_bf154bd752280b20b6ea0ad9cab8dde06e65062276209ae655bf27de49efc1ca` |
| 本轮离线 ZIP SHA-256 | `sha256:d2e7bc7cf3379619ddcc1b899ace2dbbe76ef56dda4b8120300a35d1feccc3fc` |

## 本轮数据审计决定

- 来源候选由 112 个 ADC-字段组合、114 条候选组成；每条仍为
  `pending_independent_primary_source_review`。
- SKB264 的字段候选补充了同行评议原始研究的结构定位；抗体名称没有从来源中推断为
  Sacituzumab 同义词。
- SHR-A1811 保留 DAR 5.7 和 DAR 6 两个来源值，并保留 `SHR169265`、`rezetecan`
  的名称差异。两组差异都留待一级来源复核和裁决。
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

- 本地测试：`213` 项通过，`4` 项因可选模型依赖未安装而跳过。
- 公共卫生扫描：`208` 个受跟踪文件，`status=clean`，无发现。
- 复核包：`299` 个字段项，`299` 个仍为 pending，`review_ready=false`；候选计数为 `114`。
- 发布包：`status=verified`，检查 `79` 个文件，数据库绝对本机路径计数为 `0`，
  benchmark 和候选来源文件均存在。

这些结果证明代码、数据清单和离线包的一致性；它们不证明字段已经过独立人工确认，
也不构成临床金标准或论文主结果。
