# 文镜 AI · PaperLens

让不同文献的观点，在同一面镜子里呈现。

上传 2～3 篇中英文文字型 PDF，围绕研究问题生成中文分析，查看逐项回答、独立观点、共识、分歧和原文证据。文献、任务进度与报告归属个人账号，刷新浏览器后仍可继续查看。

## 在线体验

**体验站：[paperlens.aktools.cn](https://paperlens.aktools.cn/)** · [代码仓库](https://github.com/sakura-cat-sysu/paperlens)

点击「一键游客体验」，无需注册、邀请码或自行填写 API Key。选择一组中英文示例论文，使用预填的研究问题即可开始分析；也可上传自己的论文。每位游客每天可分析 **10 次**，预览文献与查看报告不消耗次数。服务器已配置模型，额度每天北京时间 08:00 重置。

报告会关联原文引文、PDF 物理页码与页面正文，便于人工核验。引文匹配只说明文字有出处，不保证模型解释、跨文献比较或论文结论本身正确；证据不足时可能只返回草稿，不能替代阅读全文和专业判断。

**团队：630** · 陈详、钟尚民、倪健琛、陈铭谦

## 技术栈

- **前端**：React、TypeScript、Vite、React Router、TanStack Query、Tailwind CSS、基于 Radix 的 shadcn 风格组件。
- **后端**：FastAPI、Pydantic、SQLAlchemy、Alembic，Python 3.12～3.14。
- **后台分析**：Celery + RabbitMQ，PostgreSQL 保存任务、阶段检查点和报告。
- **文献与模型**：PyMuPDF、OpenAI Python SDK 传输层，支持 Chat Completions、Responses、Anthropic Messages，以及普通 JSON 和 SSE 流式响应。
- **存储**：私有 S3 兼容对象存储，或单机持久卷；数据库保存解析正文与报告快照。
- **部署**：Nginx + HTTPS + Docker Compose；GitHub Actions 检查 `main` 后传送源码归档，服务器使用国内源构建并按本机镜像 ID 部署。

架构与可靠性边界见 [架构说明](docs/architecture.md)，服务器安装、域名、证书和 CI 配置见 [部署手册](docs/deployment.md)，个人账号与项目隔离见 [服务器权限](docs/server-access.md)，分析规则见 [证据与模型边界](docs/analysis.md)。

## 本地开发

需要 Docker Compose、Node.js 24 和 [uv](https://docs.astral.sh/uv/)。生产镜像使用 Python 3.13。

```bash
cp .env.example .env
uv sync --frozen
npm ci --prefix frontend
docker compose -f compose.dev.yaml up -d --wait
uv run alembic upgrade head
uv run python -m backend.cli create-admin you@example.com
```

管理员命令在终端交互读取密码，不把密码放入命令行参数。首个账号用 `create-admin` 创建；`create-user` 创建普通账号。默认关闭公开注册；开放注册时仍需邀请码，可在 `.env` 设置 `ALLOW_REGISTRATION=true`。

## 账号与邀请码

正式账号分管理员和普通用户两种。管理员可以签发注册邀请码，普通用户只能使用自己的文献与分析。

登录页提供「一键游客体验」，无需邮箱、密码或邀请码，直接进入可选用中英文示例的新建分析页。每位游客独立保存文献与报告，每天可分析 **10 次**，文献库最多 10 篇，同一时间最多运行 1 个任务；普通账号默认每天 20 次。额度由后端按账号计数，开始分析和手动重试各计一次，重复提交同一任务不会重复扣次；导入示例、预览原文和查看报告不扣次。额度每天 UTC 00:00（北京时间 08:00）重置。

同一浏览器通过独立的 HttpOnly 标识恢复游客身份，退出再进入不会重置当天额度。标识保存 30 天，再次进入时续期；清除浏览器数据或标识过期后可能无法找回资料。游客资料不会自动转入正式账号。游客使用与正式账号相同的会话、CSRF 和资源归属校验，只能操作自己的内容，不能管理邀请码。

生产默认开放游客体验，无需修改现有生产配置即可随部署启用。可设置 `ALLOW_GUESTS=false` 暂停游客入口和已登录游客的资源访问；`GUEST_DAILY_ANALYSES=10`、`GUEST_MAX_DOCUMENTS=10` 调整游客额度与容量，普通账号仍由 `DAILY_ANALYSES` 和 `MAX_DOCUMENTS` 控制。同一来源网络默认每 15 分钟最多创建 30 个新游客（`GUEST_ENTRIES_PER_WINDOW`），已有游客返回不占创建次数。来源地址由部署代理覆盖转发并由数据库锁共享计数；清除所有浏览器数据会丢失原标识，因此匿名额度不能等同实名防刷。共用网络的大规模评审可由管理员适当调高创建上限。

游客能在模型未配置时进入、选用和预览示例，但生成分析仍需要服务器配置模型；模型未配置时不会创建任务或扣减次数。

注册需要同时满足两个条件：`ALLOW_REGISTRATION=true`，且提交一个仍然可用的邀请码。邀请码只在数据库保存 SHA-256 摘要和 `XX****XX` 形式的掩码，明文仅在签发响应里返回一次，之后无法再次读取。单个邀请码可设置可用次数、有效期，以及注册后是否直接成为管理员；占用时使用行锁，并发注册不会超额使用。

管理员登录后在侧边栏「邀请码」页签发、查看用量和吊销。也可以在服务器终端操作：

```bash
# 签发：可用 1 次、7 天有效
uv run python -m backend.cli issue-invite --note "合作组成员" --days 7

# 可用 5 次、永不过期、注册后直接是管理员
uv run python -m backend.cli issue-invite --max-uses 5 --days 0 --admin

uv run python -m backend.cli list-invites
uv run python -m backend.cli grant-admin someone@example.com
uv run python -m backend.cli revoke-admin someone@example.com
```

`issue-invite` 打印的明文只显示一次，请及时转交。成员注册时填写该码，连字符和大小写都会自动归一化。

分别在三个终端启动：

```bash
# API
uv run uvicorn backend.app:app --host 127.0.0.1 --port 8000 --reload

# 分析 Worker
uv run celery -A backend.worker:celery worker --loglevel=WARNING --concurrency=2

# 前端
npm --prefix frontend run dev
```

浏览器打开 [本地开发地址](http://127.0.0.1:5188)。前端开发服务代理 `/api` 到本机 API，无需跨域配置。域名必须和 `APP_ORIGIN` 一致。

另开终端运行派发器，负责在队列临时断连后继续投递数据库中的待执行任务：

```bash
uv run celery -A backend.worker:celery beat --loglevel=WARNING --schedule=.cache/celerybeat-schedule
```

生产使用 Compose 同时管理以上服务。终止本地基础设施时运行 `docker compose -f compose.dev.yaml stop`，保留数据库卷。

## 模型配置

编辑 `.env`，配置服务端密钥与模型：

```dotenv
OPENAI_API_KEY=
OPENAI_BASE_URL=https://api.deepseek.com
OPENAI_MODEL=deepseek-flash
OPENAI_PROTOCOL=chat
OPENAI_STREAM=false
```

`OPENAI_` 是模型配置的统一前缀，不代表一定调用 OpenAI。系统环境变量优先于 `.env`；未填写新增配置时沿用 `chat` 和非流式请求。

| `OPENAI_PROTOCOL` | 接口 | 鉴权 | 未填写 `OPENAI_BASE_URL` 时的根地址 |
| --- | --- | --- | --- |
| `chat` | Chat Completions | Bearer API Key | `https://api.openai.com/v1` |
| `responses` | Responses | Bearer API Key | `https://api.openai.com/v1` |
| `messages` | Anthropic Messages | `x-api-key` | `https://api.anthropic.com/v1` |

`OPENAI_BASE_URL` 可填站点根地址、带网关前缀的根地址、含 `/v1` 的地址或完整接口地址。普通根地址自动补 `/v1`；完整地址去掉接口后缀再按所选协议拼接，保留原有路径。例如 `https://gateway.example/coding` 会请求 `/coding/v1/...`，`https://gateway.example/custom/messages` 保留 `/custom`。DeepSeek 官方根地址继续直接请求 `/chat/completions`，也支持 `/v1`。

`OPENAI_STREAM=true` 启用上游流式请求。服务会逐块接收 SSE，过滤思考内容，并在完整结束后执行 JSON、结构和引文校验；页面继续显示阶段进度。服务商即使返回与请求方式不同的 JSON / SSE，也可自动识别。流中错误、截断或未结束的回答不会作为阶段结果保存。

所有协议在拆解与单篇阶段最多输出 4,096 tokens，综合阶段最多输出 8,192 tokens。仅在 DeepSeek 官方域名的 Chat 接口下发送关闭思考的专用参数。Responses 请求设置 `store=false`。

SDK 自动重试关闭。只有服务明确以 HTTP 400 / 422 拒绝 `max_completion_tokens` 或要求流式时，才分别切换为 `max_tokens`、`stream=true`；每次请求最多两次兼容调整，其他 API 错误不重试。结构错误仍最多修复一次，引文不匹配不触发修复。切换协议会使用独立检查点，仅改变流式开关可复用已有结果。

本地开发修改 `.env` 后重启 API、Worker 和派发器。生产环境通过 Compose 注入环境变量，修改服务器配置后需重新创建 `api`、`worker`、`scheduler` 容器；单纯重启不会载入更新后的环境变量，操作方式见 [服务器权限与运维说明](docs/server-access.md)。密钥只由服务器管理员配置，不提交到仓库。

未配置模型时，页面会明确提示，不能创建分析任务，也不会生成模拟报告。测试响应仅存在于测试与浏览器测试脚本中。

## 使用

文献库与新建分析页提供两组开放授权示例，共四篇中英文真实论文。点击「使用这组示例」会将两篇原始 PDF 加入自己的文献库并预填研究问题；重复选用会复用相同文献，选用示例不调用模型，也不消耗分析次数。开始分析仍按普通任务计入额度。

示例按账号分别保存，预览和删除不会影响其他用户。论文原文、作者、出处、CC BY 4.0 许可与文件校验值保留在 [示例来源说明](backend/sample_assets/NOTICE.md)；界面也提供原文来源与授权链接。发布包随附 PDF，不依赖评委体验时再从外部网站下载。

1. 点击「一键游客体验」或登录正式账号，选用示例或添加 PDF，可按页检查提取正文。
2. 新建分析，选择 2～3 篇不同文献并输入研究问题。
3. 提交后拿到独立任务，离开或刷新页面不会重新创建任务。
4. 任务完成后查看综合结论、逐项回答、文献观点、共识与分歧。
5. 点击 `D1-C1` 等来源，查看引文、物理页码与整页正文。
6. 失败任务可继续分析；草稿可重试未完成回答，复用已保存阶段。

每篇最多 **10 MiB、50 页、100,000 个提取字符**；问题最多 2,000 字符。超限拒绝，不截断，不执行 OCR。并发任务、每日分析次数、文献库容量由服务器配置，UTC 零点重置每日额度。开始和显式重试各计一次，普通阅读与刷新不计次数。

文献正文只在分析时发送给模型服务。原始文件保存在私有存储，正文、阶段结果与报告保存在数据库；第三方模型服务的保存策略由该服务决定。删除文献会删除原始 PDF 与文献库正文，历史报告保留分析快照；若要清除相关证据，需要同时删除相关报告。备份和对象版本按管理员设置的保留周期到期。

## 验证

```bash
# 核心测试不访问模型；API 集成测试需要独立 PostgreSQL 测试数据库。
uv run pytest -q
uv run ruff check backend scripts tests/test_api.py tests/test_storage.py tests/test_deployment.py
npm --prefix frontend test
npm --prefix frontend run build
```

API 集成测试会清理 `TEST_DATABASE_URL` 指定数据库中的业务表，**只可指定独立测试库**。未提供该变量时，API 集成测试明确跳过。

```bash
export TEST_DATABASE_URL=postgresql+psycopg://paperlens:development-only@127.0.0.1:55432/paperlens_test
export CELERY_BROKER_URL=amqp://paperlens:development-only@127.0.0.1:5673//
uv run pytest -q
npm --prefix frontend run test:e2e
```

先在本地 PostgreSQL 创建 `paperlens_test` 数据库。Playwright 会启动真实 API、Worker 和前端，模型使用仅本机可见的合成响应，不产生费用。浏览器测试不复用已有服务，避免误测其他项目。首次运行需要 `cd frontend && npx playwright install --with-deps chromium`；可用 `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH` 指向已有 Chromium。

API 契约从后端生成，更新接口后运行：

```bash
npm --prefix frontend run generate:api
```

CI 会核对生成结果，防止前后端契约漂移。容器验收可运行：

```bash
docker build -t paperlens-api:ci .
docker build -f frontend/Dockerfile -t paperlens-web:ci .
uv run python scripts/check_containers.py
```

脚本使用独立随机 Compose 项目，完成后清理自己创建的容器和测试卷。需保留本机 8088、55433、5674 端口供验收使用。当前实际验收结果见 [TEST_REPORT.md](TEST_REPORT.md)。

## 项目结构

| 目录 / 文件 | 职责 |
| --- | --- |
| `frontend/` | React 工作台、类型契约、组件与浏览器测试 |
| `backend/` | API、账号会话、邀请码、文件存储、数据库与后台任务 |
| `migrations/` | 可追踪的 PostgreSQL 结构迁移 |
| `pdf_utils.py` / `validators.py` | PDF 解析和证据校验 |
| `models.py` / `llm_service.py` / `workflow.py` | 分析结构、模型调用和阶段编排 |
| `compose.yaml` / `deploy/` | 生产服务、Nginx、发布和备份脚本 |
| `.github/workflows/` | 自动检查与生产部署 |
| `tests/` | 核心与 API 集成测试 |

当前从 Streamlit V0 全量迁移，旧入口已经移除。V0 没有持久化数据库，原浏览器会话不具备可导入的历史记录。
