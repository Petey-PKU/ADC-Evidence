# 独立离线发布包验证（2026-09-13）

v1 发布包只提供数据和索引，运行时还依赖另行取得的代码仓库。v2 将查询程序和必要配置
一并打包，新增 `scripts/run_public_release.py`，使用户在独立目录解压后安装基础 Python
依赖即可查询。此次未扩大数据覆盖、修改原始公开数据库或调用模型 API。

## 制品与版本

发布包生成于提交 `4309a6ff9d0d499e08652a01823fae6644ca29eb`，打包时
`code_worktree_dirty=false`。文件为忽略路径下的
`artifacts/releases/adc-public-2026-09-30-standalone.zip`，大小 42,099,721 字节。
后续对 CI 安装矩阵和可选 SDK 测试条件的调整不改变此包的程序内容。

| 制品 | SHA-256（未加前缀） |
| --- | --- |
| v2 ZIP | `7827c23b563b422926043de33fe04c42e20687423e4c8ec79407664fe45adc29` |
| 原始公开 SQLite | `62995d3eb0180c8952b93d5c6fb3d5f2fccd3e9762ad25f4d8a08697edc3ff48` |
| 包内脱敏 SQLite | `8fcfcd227be0b9c32ba866cb086d86830ac6ec2f2ef9bd4ec04477656967b4d7` |
| Benchmark JSONL 原始字节 | `284e222ca2b6b557db15a3a531197917781355b8833e26ec57de8fc609ddb831` |
| Benchmark JSONL 规范化换行 | `2ee7a9f5029ff9303d4b1f3e44487cee2a986ba0ce9e0cb1c36d0d58fc09ea74` |
| Benchmark question set | `af98dc6c050131ae89fb6ee9cf7e322f9e2ba5b62afe1c86a16177997435bdab` |
| 索引 manifest | `070adb47988e410ff0e065cac2f237e037ea0ea816c7b598d44462a18360db7e` |
| 干净环境依赖记录 JSON | `7742b80a8c6de6ba380237cdb219370fff32dc972b41707cc6619fff1a6f0fe0` |

检索语料版本仍为
`corpus_935c87b85da21bb4da43f671a339c5adb46a805b4dc90beb8ecb467615702d95`。
公开快照仍有 23 个 ADC、3,503 条试验、1,410 篇文献及 6,754 条实体关联；状态为
`partial`。目录字段仍需一手来源内容核验，未来目标日期尚未完成收录。

## 验证结果

- 标准开发环境：203 项测试全部通过；调整 SDK 测试条件后，相关 27 项生成测试再次全部通过。
- 全新 Python 3.12.4 基础环境：发现 203 项测试，199 项通过，4 项可选 SDK 测试明确跳过。
  未安装 `openai` 和 `sentence-transformers`。CI 新增 base/generation 两种安装方式，均覆盖
  Python 3.11/3.12；generation 环境继续执行全部适配测试，远端结果尚需推送后核验。
- ZIP 校验：77 个有哈希的文件（其中 69 个程序/配置文件），包内数据库绝对路径计数为 0。
- 解压目录查询：`--check` 成功；“T-DXd 的靶点和载荷是什么？”返回 `answered`、
  `generator_backend=structured`、HER2 和 Dxd，两个结论均有来源引用。
- 集成测试：使用公开演示数据，在隔离 Python 子进程中屏蔽 socket 连接，覆盖外部 API
  后端环境变量，并确认导入的是解压目录内的程序；结构化查询成功。
- Streamlit：AppTest 的应用异常数为 0，标题数为 1；独立启动器启动服务后，
  `/_stcore/health` 返回 HTTP 200 和 `ok`；验证结束后已停止临时服务。
- `pip check` 无依赖冲突；compileall、公开题集校验和 20/120 题分离校验通过。
  公开卫生检查未发现问题。投稿门禁仍要求真实独立人工标签和受控冻结测试集。
- 候选来源内容预核验脚本对 23 条目录 URL 的实际结果为 21 条 HTTP 200、1 条 HTTP 403、
  1 条 HTTP 412；
  16 条响应文本出现 ADC 名称/别名，161 个结构字段仍没有字段级来源。该脚本只生成
  `triage_only_pending_human_source_locator_review` 队列，不改变 `primary_check_pending`。

## 复现命令

在公开源码仓库的开发环境执行打包与校验：

```powershell
$env:PYTHONPATH="src"
python -m unittest discover -s tests -q
python scripts/package_public_release.py --output artifacts/releases/adc-public-2026-09-30-standalone.zip
python scripts/verify_public_release.py artifacts/releases/adc-public-2026-09-30-standalone.zip
python scripts/validate_public_benchmark.py --questions data/annotations/public_benchmark_v1.jsonl --manifest data/annotations/public_benchmark_v1.manifest.json --catalog data/public/marketed_adc_catalog.csv
python scripts/validate_public_holdout.py
```

将 ZIP 解压到新目录，在该目录中执行：

```powershell
python -m venv .venv
.venv/Scripts/python -m pip install -e .
.venv/Scripts/python -m pip check
.venv/Scripts/python scripts/run_public_release.py --check
.venv/Scripts/python scripts/run_public_release.py --question "T-DXd 的靶点和载荷是什么？"
.venv/Scripts/python scripts/run_public_release.py
```

程序从 manifest 选择包内数据库和索引，强制离线抽取式设置；首次依赖安装需联网或
使用自备 wheel。包内未捆绑 Python、依赖 wheel、模型缓存或原始采集响应。

## 失败记录和剩余事项

初次全新环境创建因受限执行环境的临时目录权限而使 `ensurepip` 失败；在授权执行环境
重试后创建和安装成功。AppTest 执行无应用异常，但退出时仍有临时目录清理权限提示，
另有既有 `use_container_width` 弃用提示；它们不能算作应用渲染失败，也未被静默省略。
基础环境首次完整测试因缺少可选 SDK 而有 4 项错误，现已按上述安装方式区分执行。

本轮默认执行环境中的 Git 推送退出码为 1，没有返回诊断信息；这不能单独证明具体认证
失败原因。随后在受限环境之外使用现有凭据推送成功，远端研究分支从 `8b02e7f` 更新到
`d02bf561dd3bc3429614539b7bf3514f5948fd4f`；本地与远端差异为 `0/0`。
该提交的 [GitHub CI](https://github.com/Petey-PKU/ADC-Evidence/actions/runs/34764068361)
已由 GitHub API 确认 `completed/success`。后续提交和 PR 的检查结果需绑定各自的 head SHA，
不能沿用这个成功状态。

本包是本地可用候选制品，尚未证明各来源记录均可再分发，尚未上传公共下载附件。
数据覆盖、一手来源内容核验、独立测试题和真实人工评审仍是投稿前待完成工作。
