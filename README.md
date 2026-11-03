# 文镜 AI · PaperLens

让不同文献的观点，在同一面镜子里呈现。

上传 2～3 篇中英文文字型 PDF，围绕研究问题生成中文分析，查看逐项回答、独立观点、共识、分歧和原文证据。文献、任务进度与报告归属个人账号，刷新浏览器后仍可继续查看。

## 技术栈

- **前端**：React、TypeScript、Vite、React Router、TanStack Query、Tailwind CSS、基于 Radix 的 shadcn 风格组件。
- **后端**：FastAPI、Pydantic、SQLAlchemy、Alembic，Python 3.12～3.14。
- **后台分析**：Celery + RabbitMQ，PostgreSQL 保存任务、阶段检查点和报告。
- **文献与模型**：PyMuPDF、OpenAI Python SDK，支持 DeepSeek 等 Chat Completions 兼容服务。
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

账号分管理员和普通用户两种。管理员可以签发注册邀请码，普通用户只能使用自己的文献与分析。

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

浏览器打开 **http://127.0.0.1:5188**。前端开发服务代理 `/api` 到本机 API，无需跨域配置。域名必须和 `APP_ORIGIN` 一致。

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
```

`OPENAI_` 是兼容 SDK 的变量前缀，不代表一定调用 OpenAI。`BASE_URL` 使用 API 根地址，不追加 `/chat/completions`。系统环境变量优先于 `.env`。

DeepSeek 官方域名下明确关闭思考模式，拆解与单篇阶段最多输出 4,096 tokens，综合阶段最多 8,192 tokens；其他兼容服务不会收到这些专用参数。SDK 自动重试关闭，结构错误最多修复一次。更新配置后重启 API 和 Worker。

未配置模型时，页面会明确提示，不能创建分析任务，也不会生成模拟报告。测试响应仅存在于测试与浏览器测试脚本中。

## 使用

1. 登录账号，添加 PDF 到文献库，可按页检查提取正文。
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
