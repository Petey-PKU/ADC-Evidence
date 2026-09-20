# 2026-09-20 离线包再分发门禁记录

当前数据库和 PubMed 摘要尚未完成逐项再分发许可核查，因此本轮没有生成可公开再分发
的 GitHub Release。打包脚本现在要求显式选择一种模式：

- `--research-only`：生成仅用于本地研究验证的包，manifest 标记
  `redistribution_allowed=false`；
- `--redistribution-attestation FILE`：只有内容无关的许可核查证明文件为
  `schema_version=public-redistribution-attestation-v2`、`status=approved`，并且逐项列出
  每个来源范围的唯一 HTTPS 许可链接、许可依据和 `review_status=approved`，才允许生成
  可再分发模式。证明文件本身不进入 ZIP，只记录哈希、范围、日期和来源 ID 数量。

没有模式参数时命令直接失败，避免“可运行”被误解为“可以上传”。

## 本地研究包验证

```powershell
$env:PYTHONPATH="src"
python scripts/package_public_release.py `
  --research-only `
  --database data/processed/adc_public_2026-09-30.db `
  --index-path artifacts/vector_index/public_2026-09-30 `
  --catalog data/public/marketed_adc_catalog.csv `
  --catalog-audit data/public/marketed_adc_catalog.audit.json `
  --scope-policy data/public/catalog_scope_policy.json `
  --candidate-locators data/public/catalog_source_locator_candidates.jsonl `
  --benchmark-manifest data/annotations/public_benchmark_v1.manifest.json `
  --benchmark-questions data/annotations/public_benchmark_v1.jsonl `
  --output .test_tmp/adc-public-research-only-current.zip `
  --as-of 2026-09-30
python scripts/verify_public_release.py .test_tmp/adc-public-research-only-current.zip
```

结果（代码提交 `656b9de7f7001e1666041e1a30ceb43f3ca270b6`）：79 个文件、数据库绝对路径计数为 0、`status=verified`，manifest 的
`redistribution.status=research_only`，`redistribution.redistribution_allowed=false`；解压后
`run_public_release.py --check` 和结构化 T-DXd 查询均成功。ZIP 大小为 42,149,006 字节，
SHA-256 为
`c2a41969614e3473ffa43bedab7553a1da08010148bc31e12a9be4b9ab72bb7d`。

这只是本地复现制品，不应上传到 GitHub Release、作为公共数据下载附件或用于声称文献可
再分发。完整论文门禁仍包括字段级一手来源复核、独立测试集和真实人工评分。
