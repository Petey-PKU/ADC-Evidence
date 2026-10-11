# 部署说明

## 一键本地部署

项目提供轻量演示镜像和完整检索镜像。首个项目建议先构建默认演示版：

```powershell
docker compose up --build
```

浏览器访问 `http://localhost:8501`。停止服务：

```powershell
docker compose down
```

`compose.yaml` 将外部公共数据库和评测报告挂载到宿主机，并将 hashing 索引保存在 Docker volume，因此容器重建不会删除数据或评测记录。

## 两种启动状态

### 公共快照运行时

启动前先将 `adc_public_2026-09-30.db` 放入 `data/processed/`，或在 `.env` 中将
`ADC_DATABASE_PATH` 指向挂载路径。启动脚本会：

1. 校验公共快照存在且不是空库；
2. 在快照缺少检索切片时构建切片；
3. 在向量索引与快照版本不匹配时重建轻量 hashing 索引；
4. 启动 Streamlit。

公共快照缺失时会直接报错，不会自动创建 10 条 seed 小库。10 条 seed 仅供显式开发测试，
可使用 `python -m adc_evidence.init_db --database data/processed/adc_demo.db` 创建独立 fixture。

hashing 只保证部署流程可跑通，不代表正式语义检索效果。默认镜像不安装 PyTorch，构建时间和镜像体积更适合演示。

### 当前完整数据

默认 Compose 会使用当前数据库，并在独立 volume 中建立 hashing 索引。若要使用宿主机上的 MiniLM 索引，构建完整 CPU 版：

```powershell
docker compose -f compose.yaml -f compose.full.yaml up --build
```

完整配置先从 PyTorch 官方 CPU wheel 源安装 `torch`，避免通用 Linux wheel 带入不需要的 CUDA 运行库；随后安装 sentence-transformers，并挂载 `artifacts/vector_index` 和模型缓存。完整镜像更大，只在需要 dense/hybrid 演示时使用。

## 可选远程模型后端

离线摘录后端无需密钥。若要启用硅基流动生成，在本地 `.env` 中设置：

```text
ADC_LLM_BACKEND=siliconflow
SILICONFLOW_API_KEY=your_key_here
SILICONFLOW_BASE_URL=https://api.siliconflow.cn/v1
SILICONFLOW_MODEL=deepseek-ai/DeepSeek-V4-Flash
```

生产 Compose 默认设置 `ADC_OFFLINE_ONLY=true`，保证部署不会调用网络模型。若要进行经批准的远程模型实验，
必须显式设置 `ADC_OFFLINE_ONLY=false`，再注入对应 Key；密钥只通过容器环境变量注入，不写入镜像。不要提交 `.env`。
完整步骤见 `docs/api_configuration.md`。

## 验证与健康检查

```powershell
docker compose config
docker compose ps
docker compose logs adc-evidence
```

镜像健康检查访问 Streamlit 的 `/_stcore/health`。GitHub Actions 会在 push 和 pull request 时执行编译检查与全部单元测试。

2026-10-11 本地验证结果：公共快照包含 23 个 ADC、1,410 条 PubMed 记录和 3,503 条临床试验；容器健康检查返回 `HTTP 200 / ok`。完整 CPU 配置已通过 Compose 合并解析，但首次构建仍需下载较大的 PyTorch CPU 依赖。

## 上云时的最小改动

首版适合部署到能运行 Docker 的单实例平台。需要持久化挂载 `data/processed` 和 `artifacts`，并在平台密钥管理中设置所选供应商的 Key。SQLite 适合单实例演示；如果出现多副本并发写入，应先迁移到 PostgreSQL，再增加身份验证与审计日志。

京东云单机的生产配置使用独立的 `compose.prod.yaml`：端口只绑定到
`127.0.0.1`，持久化数据位于代码目录外，公开页面关闭专家复核写入，并在每次升级前
备份 SQLite。首次安装和持续部署步骤见 `docs/server_deployment.md`。
