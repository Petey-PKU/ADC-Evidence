# 可复现性运行记录（2026-09-13）

本记录对应公开仓库分支 `research/v0.6-freeze` 的提交
`fd070ab`（PubMed 长查询与覆盖补采修复）；随后合并最新 `origin/main` 形成 `887c060`，解决了公开 benchmark、目录审计和数据集文档的分支冲突。记录只包含公开快照的运行元数据，不包含私有数据库、原始响应、评审身份或密钥。

## 验证命令与结果

在项目虚拟环境中运行：

```powershell
$env:PYTHONPATH="src"
python -m unittest discover -s tests -q
python scripts/verify_public_release.py artifacts/releases/adc-public-2026-09-30.zip
python scripts/audit_public_hygiene.py --output artifacts/evaluation/public_hygiene.json
python scripts/audit_paper_readiness.py --output artifacts/evaluation/paper_readiness.json
```

结果：197 项标准库测试通过；发布包 `status=verified`，检查 8 个文件，数据库绝对路径为 0；公开仓库卫生审计为 `clean`。论文就绪审计仍按设计返回 `not_ready_for_submission`，保留两个硬门槛：真实独立人工标签和访问受控的独立冻结测试集。

从发布包解压后设置 `ADC_OFFLINE_ONLY=true`、`ADC_LLM_BACKEND=extractive`，执行结构化问题：

```powershell
python -m adc_evidence.generation.answer "T-DXd 的靶点和载荷是什么？" --backend extractive
```

结果为 `status=answered`，返回 HER2 和 Dxd，并为两个结论绑定 FDA 来源；未调用远程模型 API。Streamlit 启动后访问 `/_stcore/health` 返回 HTTP 200、响应体 `ok`。

## 当前公开快照

| 项目 | 值 |
| --- | --- |
| 数据库 | 23 ADC、3,503 条试验、1,410 篇 PubMed 文献 |
| 数据库 SHA-256 | `sha256:d75250c76ebd319dbbf03b92313ae8b52f65913f707ebfa98f09121b567d3ca1` |
| 检索语料版本 | `corpus_935c87b85da21bb4da43f671a339c5adb46a805b4dc90beb8ecb467615702d95` |
| Benchmark | 98 道公开开发/烟雾测试题 |
| 发布包 SHA-256 | `sha256:2c6fbbbc0c30118f43a6f7aa06e97ae5e9949c81648d1fe5e6be6aa98a287364` |
| 数据审计状态 | `partial`；两类来源均有计划上限，但 23 个 ADC 均已有至少一条文献和试验实体关联 |

`partial` 是覆盖状态而非失败：它禁止把当前快照当作完整文献全集。长 PubMed 查询现在自动使用 POST；首轮结果缺少某个规范 ADC 时，会执行最多 50 条记录的精确名称补充。下一次完整抓取仍应重新生成数据库、索引、Benchmark、发布包及其哈希。

字段级主来源复核包已生成 299 条（23 个 ADC × 13 个关键字段），状态为
`awaiting_independent_primary_source_review`；JSONL SHA-256 为
`sha256:ebe6e64cb0a105d61543933dcfb815c6ed783976c9f757462f9a70bc7f81f717`，manifest
SHA-256 为 `sha256:6a1dfb9b24015743b17b32bd7adf31aa3419f71b7e49803be0a03e324ce7af33a`。
包中不含评审身份，且明确拒绝把 AI 或自动标签计入论文主结果。

本轮曾用每页 100 条、最多 140 页尝试扩大 ClinicalTrials.gov 覆盖。代理在读取分页响应时长时间无终止结果，人工中断；该次运行已在 SQLite 中标记为 `failed`，没有新试验写入，失败信息和参数保留在 `ingestion_runs`/`ingestion_source_runs`。因此当前发布包仍明确是 3,503 条试验的 `partial` 快照。

## GitHub 推送状态

通过 `http://127.0.0.1:7890` 代理执行 `git ls-remote` 成功，证明网络代理可用；`git push origin research/v0.6-freeze` 在 Git Credential Manager 认证阶段未完成，远端分支仍停留在旧提交 `8b02e7f20648a04cfebc1a1df2cb4089c7fdc995`。认证可用后，在本仓库目录执行：

```powershell
$env:HTTP_PROXY="http://127.0.0.1:7890"
$env:HTTPS_PROXY="http://127.0.0.1:7890"
git push origin research/v0.6-freeze
```

