# 大模型 API 配置与单题验证

## 当前推荐配置

本项目已支持三种答案生成后端：

- `extractive`：确定性离线摘录，不使用大模型，不产生 API 费用；
- `siliconflow`：硅基流动的 OpenAI 兼容 Chat Completions 接口；
- `openai`：OpenAI Responses API。

当前研究优先使用 `extractive` 离线后端。若经批准使用远程模型，才选择
`siliconflow` 和 `deepseek-ai/DeepSeek-V4-Flash`。大模型只负责把检索出的证据组织成带
`[S1]` 等编号的回答；检索、证据截取、拒答前置检查和引用校验仍由项目代码完成。

[硅基流动官方快速开始](https://docs.siliconflow.cn/en/userguide/quickstart)同样使用
OpenAI Python 客户端并指定自有 `base_url`；其
[Chat Completions 文档](https://docs.siliconflow.com/en/api-reference/chat-completions/chat-completions)
给出的接口为 `/v1/chat/completions`，模型列表包含
[`deepseek-ai/DeepSeek-V4-Flash`](https://www.siliconflow.com/models/deepseek-v4-flash)。
本项目因此使用独立适配器，而不是把现有 OpenAI Responses API 后端直接改 URL。

## 1. 创建本地配置文件

在项目根目录运行：

```powershell
Copy-Item .env.example .env
notepad .env
```

把 `.env` 中相关部分改为：

```text
ADC_LLM_BACKEND=siliconflow
ADC_OFFLINE_ONLY=false
SILICONFLOW_API_KEY=在这里填写你的真实Key
SILICONFLOW_BASE_URL=https://api.siliconflow.cn/v1
SILICONFLOW_MODEL=deepseek-ai/DeepSeek-V4-Flash
```

注意：

- 不要在 Key 两侧添加引号或空格；
- 不要把真实 Key 发到聊天、截图、README、源代码或 GitHub；
- `.env` 已在 `.gitignore` 中排除，只供本机读取；
- `.env.example` 只能保留空 Key，不能写入真实值；
- `ADC_LLM_BACKEND` 只控制 `--backend auto` 的默认路由，命令行显式指定
  `--backend siliconflow` 时不依赖这一项。
- `.env.example` 默认设置 `ADC_OFFLINE_ONLY=true`；只有明确批准远程模型实验时才改为 `false`。

可以用下面的命令确认 `.env` 会被 Git 忽略；它不会打印 Key：

```powershell
git check-ignore .env
```

输出 `.env` 即表示忽略规则生效。

## 2. 安装生成后端依赖

如果当前环境尚未安装生成依赖，运行：

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[generation]"
```

硅基流动适配器复用 `openai` Python 包，不需要另装厂商 SDK。

## 3. 只运行一道测试题

先不要运行 16 题全量评测。执行：

```powershell
.\.venv\Scripts\python.exe -m adc_evidence.generation.answer `
  "T-DXd 的靶点、载荷和 DAR 是什么？" `
  --backend siliconflow `
  --retrieval-mode sparse `
  --top-k 5
```

成功时 JSON 结果应重点满足：

- `status` 为 `answered`；
- `generator_backend` 为 `siliconflow`；
- `model` 为硅基流动实际返回的模型名；
- `answer` 的每条事实均含 `[S1]` 等引用；
- `validation.valid` 为 `true`；
- `usage` 包含 `input_tokens`、`output_tokens` 和 `total_tokens`；
- `response_id` 非空。

如果模型给出了没有引用的答案，系统会按设计返回
`citation_validation_failed`，这说明 API 已经接通，但回答没有通过项目的引用护栏。

## 4. 在 Streamlit 中使用

配置 `.env` 后重启页面：

```powershell
streamlit run src/adc_evidence/app.py
```

“带引用问答”页的“生成后端”中将出现“硅基流动 Chat Completions”。页面只在
实际点击“生成带引用回答”时调用 API。

## 5. 单题通过后再运行完整评测

单题确认无误后，才运行 16 题生成与拒答评测，并写入独立报告：

```powershell
.\.venv\Scripts\python.exe -m adc_evidence.generation.evaluate_generation `
  --backend siliconflow `
  --retrieval-mode sparse `
  --output artifacts/evaluation/generation_report_siliconflow.json

.\.venv\Scripts\python.exe -m adc_evidence.review.prepare_review `
  --generation-report artifacts/evaluation/generation_report_siliconflow.json
```

报告会保存实际模型名、逐题 token 用量、response ID 和运行级 token 汇总；新的
`run_id` 不会覆盖离线基线或既有人工复核。

## 常见错误

- `SILICONFLOW_API_KEY is not configured`：`.env` 不在项目根目录、变量名拼错，
  或填写后没有保存；
- HTTP 401：Key 无效、已撤销，或复制时带入额外字符；
- HTTP 404：通常是 `SILICONFLOW_BASE_URL` 或模型 ID 拼错；
- HTTP 429：账户额度、速率限制或并发限制；
- `SiliconFlow returned an empty answer`：服务返回了空内容，保留错误信息并稍后重试；
- `citation_validation_failed`：连接成功，但模型输出不符合逐条引用要求，需要作为
  Bad Case 复核，而不是绕过校验。

任何排障截图都应遮住 Key。若 Key 曾出现在聊天、日志或 Git 历史中，应立即在控制台
撤销并重新生成。

## 可选：继续使用 OpenAI 后端

现有 OpenAI Responses API 路径没有被删除。需要时可在 `.env` 中配置：

```text
ADC_LLM_BACKEND=openai
ADC_OFFLINE_ONLY=false
OPENAI_API_KEY=在这里填写你的真实Key
OPENAI_MODEL=gpt-5-mini
```

并把单题命令改为 `--backend openai`。两个供应商使用各自独立的 Key 和模型变量，
不会相互覆盖。
