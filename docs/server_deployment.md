# 京东云单机部署

本配置适用于一台已有公网 IPv4 的 Linux 云服务器。推荐链路是：

```text
访客 -> 域名/HTTPS -> 京东云安全组 443 -> Nginx -> 127.0.0.1:8501 -> Streamlit
```

ADC-Evidence 只监听宿主机 `127.0.0.1:8501`，由 Nginx 对外提供 80/443；不要在
安全组开放 8501。服务器上既有的 ZeroTier Moon 服务与本项目使用不同端口，不需要
修改。

## 0. 创建云资源

用于公开样例数据的轻量演示版建议从以下配置开始：

- 京东云轻量云主机或云主机 CVM，Linux（Ubuntu LTS）；
- 最低 2 vCPU、2 GB RAM、20 GB 系统盘；若构建完整 MiniLM/PyTorch 镜像，建议
  4 GB 以上 RAM 和更多磁盘；
- 公网 IPv4；
- 安全组入站仅允许 80/TCP、443/TCP，以及仅限本人固定 IP 的 22/TCP；
- 不添加 8501/TCP 公网入站规则。

京东云控制台中需要把安全组绑定到实例，再添加入站规则。域名展示时，添加一条指向
实例公网 IPv4 的 `A` 记录。中国大陆节点对外提供网站服务前，先按京东云指引确认域名
备案要求。可参考京东云官方的[安全组规则](https://docs.jdcloud.com/cn/virtual-machines/security-group-rules)、
[云解析 DNS](https://docs.jdcloud.com/cn/jd-cloud-dns/record-domain)和
[备案说明](https://docs.jdcloud.com/cn/iavm/configure_domain)。

## 1. 服务器准备

安装 Docker Engine、Compose v2、Git、curl 和 Nginx。安装完成后确认：

```bash
docker --version
docker compose version
git --version
nginx -v
```

Docker 应按所选 Linux 发行版的官方步骤安装，不要使用旧的 Compose v1。创建持久化
目录，其中容器进程固定使用 UID/GID 10001：

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
ADC_BUILD_NETWORK=host
```

不要在公开服务中填写模型 API Key。后续如要开放远程模型，应先增加身份验证、
请求频率限制、输入长度限制和供应商费用上限。

生产 Compose 默认只在构建镜像、下载 Python 依赖时使用 Linux 宿主网络，避免部分
云服务器的 BuildKit 默认网络访问 PyPI 时超时。运行中的应用容器仍使用独立 Docker
网络，且宿主机端口仍只绑定 `127.0.0.1`。如服务器不允许 host build network，可在
`.env` 中把 `ADC_BUILD_NETWORK` 改为 `default`。

首次启动：

```bash
export ADC_GIT_SHA="$(git rev-parse --short=12 HEAD)"
export ADC_IMAGE_TAG="$ADC_GIT_SHA"
docker compose -f compose.prod.yaml config --quiet
docker compose -f compose.prod.yaml up -d --build
curl --fail http://127.0.0.1:8501/_stcore/health
```

应看到 `ok`，且 `docker compose -f compose.prod.yaml ps` 中服务状态为 healthy。首次
启动会自动生成 10 条公开演示记录和轻量 hashing 索引，不会使用私有仓库数据。

无域名时，先从自己的电脑建立 SSH 隧道测试：

```bash
ssh -L 8501:127.0.0.1:8501 your-server-alias
```

然后访问 `http://localhost:8501`。稳定公开展示建议再配置域名、反向代理和 HTTPS。

## 3. 配置域名、Nginx 与 HTTPS

先在 DNS 服务商处将 `adc.example.com` 的 `A` 记录指向实例公网 IPv4。复制仓库提供的
反向代理模板，并把模板内的域名替换为自己的域名：

```bash
cd /opt/adc-evidence
sudo cp deploy/nginx/adc-evidence.conf.example \
  /etc/nginx/sites-available/adc-evidence.conf
sudo editor /etc/nginx/sites-available/adc-evidence.conf
sudo ln -s /etc/nginx/sites-available/adc-evidence.conf \
  /etc/nginx/sites-enabled/adc-evidence.conf
sudo nginx -t
sudo systemctl reload nginx
```

模板已经包含 Streamlit 需要的 WebSocket 转发和长连接超时。若服务器没有
`sites-available`/`sites-enabled` 目录，将配置放到该发行版 Nginx 默认加载的
`conf.d` 目录。

DNS 生效且备案条件满足后，用 Certbot 或其他 ACME 客户端为该域名签发证书。以
Ubuntu + Nginx 插件为例：

```bash
sudo apt-get update
sudo apt-get install -y certbot python3-certbot-nginx
sudo certbot --nginx -d adc.example.com
sudo certbot renew --dry-run
```

证书签发完成后访问 `https://adc.example.com`。若暂时没有域名，优先使用上一节的 SSH
隧道完成内部演示，不要为了省一步而把 8501 暴露到公网。

## 4. 上线验收

```bash
curl --fail http://127.0.0.1:8501/_stcore/health
curl --fail --head https://adc.example.com/_stcore/health
docker compose -f compose.prod.yaml ps
docker compose -f compose.prod.yaml logs --tail=100 adc-evidence
```

再从一台不在云服务器内网的电脑打开站点，检查首页、检索页、问答页，并确认“专家
复核”是只读状态。公开演示默认使用 `extractive` 后端，不产生模型 API 费用。

## 5. 持续迭代

日常开发使用功能分支，通过测试后合并到 GitHub `main`。服务器只部署 `main`：

```bash
cd /opt/adc-evidence
bash scripts/deploy.sh
```

脚本会拒绝脏工作区和错误分支；在拉取新提交前创建事务一致的 SQLite 备份，随后
执行 fast-forward 更新、重建容器并检查健康状态。备份保存在
`/srv/adc-evidence-backups`，不会进入 Git。健康检查从 Compose 的实际端口映射读取
端口，因此修改 `.env` 中的 `ADC_HOST_PORT` 后也能正确工作。

查看状态与日志：

```bash
docker compose -f compose.prod.yaml ps
docker compose -f compose.prod.yaml logs --tail=100 adc-evidence
```

若部署失败，代码和数据仍是分离的。可切回前一个 Git 标签或提交重新构建；恢复数据库
前先停止容器，并保留当前数据库副本。

## 6. 常见故障

- `curl 127.0.0.1:8501` 成功但公网打不开：检查 Nginx、80/443 安全组和主机防火墙，
  不要开放 8501。
- 页面能打开但一直显示连接中：确认 Nginx 模板中的 `Upgrade`、`Connection` 和
  `proxy_http_version 1.1` 未被删除。
- 容器反复重启：用 `docker compose -f compose.prod.yaml logs --tail=200` 查看错误，
  再检查 `/srv` 下挂载目录是否归 UID/GID 10001 所有。
- 首次构建很慢：默认 demo 镜像不下载 PyTorch；确认没有叠加 `compose.full.yaml`。
- HTTPS 证书无法签发：先确认 DNS 已指向本机、80 端口可达、域名满足所在地域的备案
  要求。
