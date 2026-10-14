# 公共快照运行数据

v0.7 的默认运行时使用用户授权的 SQLite 公共快照。数据库以压缩归档形式直接跟踪在
公开仓库中，确保普通用户 clone 后可以直接复现；首次启动时自动校验并解压，生成的
向量索引仍是本地运行时产物。

## 默认文件

```text
data/processed/adc_public_2026-09-30.db
```

当前发布快照的校验信息：

- 文件大小：155,361,280 bytes
- SHA-256：`d28939138a67f1493553a24af49198f8115bc3026591f9a2b97c3e5568ef6482`
- ADC：23
- PubMed 文献：1,410（其中 1,366 篇含摘要）
- ClinicalTrials.gov 试验：3,503
- 原子事实：59,877
- 证据记录：6,754
- 来源快照：7,280

数据采集窗口是有边界的，以上数量不代表全球全量覆盖；详细来源边界见
[`data_sources.md`](data_sources.md)。

## Clone、启动和校验

clone 后直接启动即可；运行时会自动恢复数据库并校验：

```powershell
Get-FileHash data/processed/adc_public_2026-09-30.db -Algorithm SHA256
python -m adc_evidence.deploy
```

Docker Compose 会把仓库中的 `data/processed` 挂载到容器，并通过
`ADC_DATABASE_PATH=/app/data/processed/adc_public_2026-09-30.db` 使用该文件。生产部署使用
`/srv/adc-evidence-data/processed/` 的同名文件。

如果文件缺失或被替换为十条 seed 小库，v0.7 启动会直接失败并提示检查路径。开发测试如需
小库，必须使用独立路径显式初始化：

```bash
python -m adc_evidence.init_db --database data/processed/adc_demo.db
```

原始响应、模型缓存和向量索引仍不提交到 GitHub；只有本文件明确列出的用户授权公共
快照归档进入 `main`。如果部署环境无法使用仓库归档，可以使用仓库提供的校验发布包安装器。
