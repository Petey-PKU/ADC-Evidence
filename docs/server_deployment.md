# 京东云单机部署

本配置适用于一台已有公网 IPv4 的 Linux 云服务器。ADC-Evidence 只监听宿主机
`127.0.0.1:8501`，由 Nginx 或 Caddy 对外提供 80/443；不要在安全组开放 8501。
服务器上既有的 ZeroTier Moon 服务与本项目使用不同端口，不需要修改。

## 1. 服务器准备

建议至少 2 vCPU、2 GB RAM 和 10 GB 可用磁盘，安装 Docker Engine、Compose v2、
Git 和 curl。创建持久化目录，其中容器进程固定使用 UID/GID 10001：

```bash
sudo install -d -o 10001 -g 10001 \
  /srv/adc-evidence-data/processed \
  /srv/adc-evidence-data/vector_index \
  /srv/adc-evidence-data/evaluation
sudo install -d -o 10001 -g 10001 /srv/adc-evidence-backups
```

安全组仅保留：受限来源的 SSH、公开站点所需的 80/443，以及现有 ZeroTier Moon
规则。不要把公网 IP、SSH 私钥、GitHub 凭据或 API Key 写进仓库。

## 2. 首次安装

```bash
sudo git clone https://github.com/Petey-PKU/ADC-Evidence.git /opt/adc-evidence
sudo chown -R "$USER":"$USER" /opt/adc-evidence
cd /opt/adc-evidence
cp .env.example .env
```

首个公开版本保留以下安全默认值：

```text
ADC_LLM_BACKEND=extractive
ADC_PUBLIC_DEMO=true
ADC_HOST_PORT=8501
ADC_DATA_DIR=/srv/adc-evidence-data
ADC_BACKUP_DIR=/srv/adc-evidence-backups
```

不要在公开服务中填写模型 API Key。后续如要开放远程模型，应先增加身份验证、
请求频率限制、输入长度限制和供应商费用上限。

首次启动：

```bash
export ADC_GIT_SHA="$(git rev-parse --short=12 HEAD)"
export ADC_IMAGE_TAG="$ADC_GIT_SHA"
docker compose -f compose.prod.yaml config --quiet
docker compose -f compose.prod.yaml up -d --build
curl --fail http://127.0.0.1:8501/_stcore/health
```

无域名时，先从自己的电脑建立 SSH 隧道测试：

```bash
ssh -L 8501:127.0.0.1:8501 your-server-alias
```

然后访问 `http://localhost:8501`。稳定公开展示建议再配置域名、反向代理和 HTTPS。

## 3. 持续迭代

日常开发使用功能分支，通过测试后合并到 GitHub `main`。服务器只部署 `main`：

```bash
cd /opt/adc-evidence
bash scripts/deploy.sh
```

脚本会拒绝脏工作区和错误分支；在拉取新提交前创建事务一致的 SQLite 备份，随后
执行 fast-forward 更新、重建容器并检查健康状态。备份保存在
`/srv/adc-evidence-backups`，不会进入 Git。

查看状态与日志：

```bash
docker compose -f compose.prod.yaml ps
docker compose -f compose.prod.yaml logs --tail=100 adc-evidence
```

若部署失败，代码和数据仍是分离的。可切回前一个 Git 标签或提交重新构建；恢复数据库
前先停止容器，并保留当前数据库副本。
