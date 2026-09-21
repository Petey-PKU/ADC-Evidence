# 再分发许可 attestation

离线包只有在所有被打包的来源内容都完成许可核查后，才能使用
`--redistribution-attestation`。当前公开快照仍未满足这一条件，默认只能使用
`--research-only`；本文件描述的是未来批准文件的格式，不是许可批准本身。

证明文件必须是内容无关的 JSON，不得包含摘要、全文、原始 API 响应、评审身份或本机路径。
脚本要求 `schema_version=public-redistribution-attestation-v2`、`status=approved`，以及每个
来源范围一条 `source_licenses` 记录。每条记录至少包含：

```json
{
  "source_id": "pubmed_metadata",
  "content_scope": "PubMed identifiers, titles, dates and metadata",
  "license_url": "https://example.org/source-license",
  "permission_basis": "documented permission or applicable public-data terms",
  "review_status": "approved"
}
```

`source_id` 必须唯一，`license_url` 必须是 HTTPS，`review_status` 必须为 `approved`。
实际 attestation 还应列出目录结构化字段、ClinicalTrials.gov 元数据、PubMed 元数据、
PubMed 摘要（若包内包含）和其他随包发布的内容范围；如果某一范围没有明确许可，不能
将它写成 `approved`，也不能发布 GitHub Release。打包时只把证明文件的哈希、范围、日期
和来源 ID 数量写入 manifest，证明文件本身不会进入 ZIP。

可用以下命令验证格式（不会替代法律或来源方许可审查）：

```powershell
$env:PYTHONPATH="src"
python scripts/package_public_release.py `
  --redistribution-attestation D:\review\redistribution_attestation.json `
  --database data/processed/adc_public_2026-09-30.db `
  --index-path artifacts/vector_index/public_2026-09-30 `
  --catalog data/public/marketed_adc_catalog.csv `
  --benchmark-manifest data/annotations/public_benchmark_v1.manifest.json `
  --output .test_tmp/adc-public-approved.zip `
  --as-of 2026-09-30
```
