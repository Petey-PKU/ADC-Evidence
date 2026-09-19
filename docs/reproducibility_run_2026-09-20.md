# 2026-09-20 公共离线发布包复现记录

这份记录对应公共分支 `research/v0.6-freeze` 的提交
`f9031962de5ebf3336412948cb287ab3d9610772`。它记录本地构建和解压验证结果，不能替代
GitHub Release，也不能把当前 partial 数据集解释为完整覆盖或人工金标准。

## 输入与哈希

| 项目 | 值 |
|---|---|
| 代码提交 | `f9031962de5ebf3336412948cb287ab3d9610772` |
| 数据库 | `sha256:2f9a5c53f49bbc23a883b0863a1c5577510ac5004ca47cfad106d40794dc819a` |
| 目录 | `sha256:2fb354cda6cfc8ebb119e9f145cca1c50978ccaebb7877516f42bab8ec503278` |
| benchmark manifest | `sha256:41fd2884722e0c19516f13601df5bd82230dadd87e17c9044c42cb1ec364d7a9` |
| benchmark JSONL | `sha256:7169601cf37bfd61ca3e9d36a417ba419ff8f38c829351475dae8884449efc5f` |
| 检索语料版本 | `corpus_bf154bd752280b20b6ea0ad9cab8dde06e65062276209ae655bf27de49efc1ca` |
| 本地 ZIP SHA-256 | `sha256:3c88f3bd10a20418cf1ef4e9abf51444467c526c6b49d33fdaae6e56a40899d7` |

ZIP 中的数据库、目录、benchmark 和索引文件还分别受 `RELEASE_MANIFEST.json` 的逐文件
SHA-256 清单约束。上表的 ZIP 哈希是本次本地构建产物的哈希；重新打包时 ZIP 元数据可能
改变，因此应以新包内清单为准。

## 构建和验证命令

```powershell
$env:PYTHONPATH="src"
python scripts/package_public_release.py `
  --database data/processed/adc_public_2026-09-30.db `
  --index artifacts/vector_index/public_2026-09-30 `
  --catalog data/public/marketed_adc_catalog.csv `
  --catalog-audit data/public/marketed_adc_catalog.audit.json `
  --scope-policy data/public/catalog_scope_policy.json `
  --candidate-locators data/public/catalog_source_locator_candidates.jsonl `
  --benchmark-manifest data/annotations/public_benchmark_v1.manifest.json `
  --benchmark-questions data/annotations/public_benchmark_v1.jsonl `
  --output .test_tmp/adc-public-f903196-locators.zip

python scripts/verify_public_release.py .test_tmp/adc-public-f903196-locators.zip
python -m zipfile -e .test_tmp/adc-public-f903196-locators.zip .test_tmp/release-smoke-f903196
python -I .test_tmp/release-smoke-f903196/scripts/run_public_release.py --check
python -I .test_tmp/release-smoke-f903196/scripts/run_public_release.py `
  --question "T-DXd 的靶点和载荷是什么？"
```

## 结果

- 发布清单验证：`status=verified`，检查 79 个文件，数据库绝对本机路径计数为 0；字段级来源候选文件已包含在包内。
- 解压后的独立启动器：`offline_only=true`，`backend=extractive`。
- 示例查询：返回 `status=answered`、`route=structured_fact`，靶点为 HER2、载荷为 Dxd，
  两条结构化结论均有来源引用和支持校验。
- 完整本地测试：211 项通过。
- GitHub CI：该提交的 Python 3.11/3.12、base/generation 矩阵检查通过。

## 仍未完成的门禁

数据库采集仍为 partial；公开 benchmark 的 98 道题仍是开发/公开 smoke 集；299 个目录
字段仍等待真实独立人工复核；独立访问受控测试集和 GitHub Release 尚未建立。因此，这份
记录只证明离线程序包的可复现性，不支持专家验证、临床金标准或论文主结果结论。
