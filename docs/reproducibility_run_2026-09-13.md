# 可复现性运行记录（2026-09-13）

本记录对应公开仓库分支 `research/v0.6-freeze` 的提交
`e6299e95a7cfea62822b348036c1f8dca6cf0e5d`。记录只包含公开快照的运行元数据，不包含私有数据库、原始响应、评审身份或密钥。

## 验证命令与结果

在项目虚拟环境中运行：

```powershell
$env:PYTHONPATH="src"
python -m unittest discover -s tests -q
python scripts/verify_public_release.py artifacts/releases/adc-public-2026-09-30.zip
python scripts/audit_public_hygiene.py --output artifacts/evaluation/public_hygiene.json
python scripts/audit_paper_readiness.py --output artifacts/evaluation/paper_readiness.json
```

结果：194 项标准库测试通过；发布包 `status=verified`，检查 8 个文件，数据库绝对路径为 0；公开仓库卫生审计为 `clean`。论文就绪审计仍按设计返回 `not_ready_for_submission`，保留两个硬门槛：真实独立人工标签和访问受控的独立冻结测试集。

从发布包解压后设置 `ADC_OFFLINE_ONLY=true`、`ADC_LLM_BACKEND=extractive`，执行结构化问题：

```powershell
python -m adc_evidence.generation.answer "T-DXd 的靶点和载荷是什么？" --backend extractive
```

结果为 `status=answered`，返回 HER2 和 Dxd，并为两个结论绑定 FDA 来源；未调用远程模型 API。Streamlit 启动后访问 `/_stcore/health` 返回 HTTP 200、响应体 `ok`。

## 当前公开快照

| 项目 | 值 |
| --- | --- |
| 数据库 | 23 ADC、1,750 条试验、998 篇 PubMed 文献 |
| 数据库 SHA-256 | `sha256:1617c766ee793dc12b033c777cd53dd370cbfd0e9cbdeb0122aa7e1524d17921` |
| 检索语料版本 | `corpus_c0c5d4adf458371bddf8cc75ac62c2f58fae5fa73da7e1b8c1b66f7646f5f16c` |
| Benchmark | 98 道公开开发/烟雾测试题 |
| 发布包 SHA-256 | `sha256:12a39a6db1f76102a820aecf8ac28969c87c5cc8029e2e79fc9713258d67d5bd` |
| 数据审计状态 | `partial`；PubMed 达到计划上限，`adc_021` 仍缺少文献实体关联 |

`partial` 是覆盖状态而非失败：它禁止把当前快照当作完整文献全集。下一次完整抓取应使用目录别名检索，并重新生成数据库、索引、Benchmark、发布包及其哈希。

## GitHub 推送状态

通过 `http://127.0.0.1:7890` 代理执行 `git ls-remote` 成功，证明网络代理可用；`git push origin research/v0.6-freeze` 在 Git Credential Manager 认证阶段未完成，远端分支仍停留在旧提交 `8b02e7f20648a04cfebc1a1df2cb4089c7fdc995`。认证可用后，在本仓库目录执行：

```powershell
$env:HTTP_PROXY="http://127.0.0.1:7890"
$env:HTTPS_PROXY="http://127.0.0.1:7890"
git push origin research/v0.6-freeze
```

