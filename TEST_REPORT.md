# PaperLens 迁移与生产验收

本轮从 Streamlit V0 迁为 React / FastAPI / PostgreSQL / Celery / RabbitMQ / Nginx，部署到 **https://paperlens.aktools.cn**。服务器为 `qqbot-server`，Ubuntu 24.04 / amd64，现有其他站点继续运行。

## 自动化检查

完整 GitHub Quality 已通过 Python、React、Playwright、API 契约、数据库迁移和真实容器验收。核心分析测试保留，Streamlit UI 测试已由 API / React / 浏览器测试替代。

- Python 覆盖 PDF 边界、引文冻结、问题覆盖、模型错误脱敏、检查点复用、账号认证、CSRF / Origin、账号归属、额度、提交幂等、队列补投、SSE、存储和发布控制流。
- 发布测试覆盖成功提升 / 失败恢复、国内源码构建、本机镜像 ID、归档 SHA、路径穿越、链接拒绝、非 root 用户读取源码目录和 CI SSH 命令限制。
- 2 项 React 测试覆盖报告草稿、来源、整页正文、章节、未匹配观点和 HTML 文本渲染。
- 2 项 Playwright 测试使用真实 API / PostgreSQL / RabbitMQ / Worker 与本机合成模型，验证上传 → 后台任务 → 报告 → 刷新 → 来源与整页正文、键盘焦点、错误文件和 320 / 375 / 768 / 1440 布局。
- Ruff、TypeScript、Vite、Prettier、OpenAPI 类型一致性、Alembic drift 和 shell 检查通过。
- 镜像实际构建，独立随机 Compose 项目的六项服务健康；测试清理自身临时卷。

S3 测试通过 botocore Stubber 核对协议与流关闭，未访问真实 Bucket。发布失败恢复使用隔离的 Docker / curl 替身，不代表已做生产故障切换。

## 生产服务与权限

- 创建 `paperlens` 项目组，`ntgmc`、`paperlens-dev1`、`paperlens-dev2`、`paperlens-dev3` 四个独立个人账号加入该组。
- 三个协作者不在 sudo 管理员组和宿主机 Docker 组，SSH 密码认证分别实测通过，首次登录要求改密。
- 协作者可共同读写 `/opt/paperlens/workspace`，实际核对源码文件读写和 Git 访问。
- `paperlens` 为锁定密码、nologin 的服务账号，使用独立 rootless Docker；不访问宿主机 Docker socket。
- 实际检查三个协作者和服务账号不能进入其他项目根目录、管理员主目录、Nginx / 证书目录，不能取得 root sudo。
- `paperlensctl` 仅允许状态、日志、重启和备份；三个协作者分别实测状态与日志可用，任意 shell 命令被拒绝。CI 专用 SSH 密钥也拒绝普通 shell 命令。
- 服务账号限制为最多 2 核 CPU、MemoryHigh=1800M、MemoryMax=2100M。容器另有限额，仅 `127.0.0.1:18090` 映射给宿主机 Nginx；数据库和队列不开放宿主端口。
- 原宿主机两个容器保持原运行状态，`aktools.cn` 和 `study-v4.aktools.cn` 返回 200。

## 发布与网络

境外大镜像下载和 GitHub Runner 向国内仓库上传均出现明显慢速，最终发布链路采用 GitHub 测试后传送小型 Git 归档，服务器用国内源构建。

实测约 197 KB 源码包通过 SSH 传送约 0.39 秒；首次国内构建时，后端 56 个依赖下载约 1.5 秒、安装约 0.7 秒，前端依赖安装约 7.5 秒，前端类型检查与编译约 6 秒。Docker 导出、解包和服务健康等待另计；这些是本机单轮结果，不代表生产 P95。

依赖版本与哈希仍来自锁文件。基础镜像使用腾讯云内网镜像源，Python 使用腾讯云 PyPI，npm 使用 npmmirror；应用镜像不再跨境传输，本机内容 ID 固定运行版本。

CI 使用四个仓库 Secrets 和受限 forced-command SSH 公钥。接收端验证 Git 归档 SHA 与路径 / 类型 / 体积。生产发布执行数据库备份、Alembic、等待 Worker、服务替换、HTTPS 双端 SHA 核对和失败恢复旧应用。

生产联调发现解包目录受 077 掩码影响，导致容器非 root 用户看不到迁移文件；已修复源码目录权限，增加真实构建中的迁移发现检查与回归测试。

## 正式 HTTPS 与浏览器

- 已申请 `paperlens.aktools.cn` 正式 Let's Encrypt 证书，HTTP 正确跳转 HTTPS。
- 宿主机 Nginx 新增独立虚拟主机，`nginx -t` 通过，平滑 reload。
- Certbot 针对此域名的 dry-run 续期成功，现有定时任务负责续期，部署 hook reload Nginx。
- 生产 API、Worker、Beat、PostgreSQL、RabbitMQ、Web 六项服务均健康，API 与前端提交 SHA 一致。
- 通过真实公网浏览器登录，检查 Secure / HttpOnly Cookie，上传合成 PDF 并刷新验证持久化；375px 无横向溢出，无 pageerror。已实际查看桌面与窄屏截图。
- 测试 PDF 已删除，测试浏览器会话已退出，保留初始网站账号供交接；公开注册关闭。
- 生产数据库备份已生成；迁移阶段还曾将合成数据库备份恢复到本机独立库核对数据。

## 尚未执行的检查

- 生产模型 API 密钥未配置，分析提交明确禁用；没有在生产调用付费模型。完整分析链在 CI 使用合成模型验证。
- 初始使用本地持久卷，未接真实 S3 Bucket；异机备份目的地与保留周期仍需配置。
- 未进行并发压测、读屏、整机故障或生产数据库恢复切换演练。

账号 / 域名 / CI 已落地不等于具备整机高可用。共用服务器仍共用内核和网络；Worker 在收费请求完成但保存检查点前异常退出，恢复可能重复收费。数据库回滚依赖兼容迁移，不自动降级。

生产验证日志、截图与状态位于本机忽略目录 `.cache/server/`。私密账号交接文件单独保存，不上传仓库。
