# PaperLens 全量迁移验证

验证环境：Linux / WSL，Python 3.14.4、Node.js 24.22.1、Docker Engine 29.1.2、Compose 2.40.3。生产 Python 镜像使用 3.13，已实际构建和启动。

本轮由 Streamlit V0 迁为 React / FastAPI / PostgreSQL / Celery / RabbitMQ / Nginx。V0 的真实 DeepSeek 联调仅是核心逻辑的历史验证，本报告只记录新架构实际完成的检查，不将历史结果当作本轮线上验收。

## 自动化

- 109 项原有核心测试通过：中英文 PDF、大小 / 页数 / 字符边界、扫描页与加密拒绝、引文整体冻结、问题覆盖、结构修复、错误脱敏和阶段复用。
- 10 项真实 PostgreSQL API 集成测试通过：登录 / 注册开关 / 会话撤销、CSRF / Origin、登录次数限制、验证错误脱敏、文献与报告归属、下载 / 删除、文献去重与容量、任务提交幂等 / 额度、队列补投、草稿与失败续试、SSE 和重复消费互斥。
- 2 项存储测试通过：本地文件完整读写删除；S3 客户端通过 botocore Stubber 检查操作契约与流关闭，未访问真实 Bucket。
- 2 项发布脚本测试通过：执行真实 shell 发布脚本，隔离 Docker / curl 后验证备份、迁移、版本核对、成功提升和失败恢复旧 release。
- 2 项前端组件测试通过：草稿状态、来源弹窗、整页正文、章节切换、未匹配观点标记与 HTML 文本安全渲染。
- Python Ruff、前端 TypeScript / 生产构建、API 类型生成、Alembic schema drift 检查与 shell 语法检查通过。

原 Streamlit 页面测试已由 API / React / Playwright 测试替代，核心校验用例保留。

## 浏览器完整流程

Playwright 使用真实 FastAPI、PostgreSQL、RabbitMQ 和 Celery Worker；模型为仅本机运行的人工合成响应，不访问付费模型，不使用私人论文。

2 项浏览器测试通过：

- 注册并登录 → 上传两份合成 PDF → 勾选文献 → 填写问题 → 创建后台任务 → 生成带原文的报告。
- 刷新报告继续读取，未重新提交分析。
- 打开观点来源、查看引文与整页正文，Escape 关闭弹窗。
- 报告删除确认可以取消。
- 文献库无效 PDF 显示可操作错误。
- 320、375、768 和 1440 CSS px 检查页面与报告；无横向溢出。窄屏导航采用 Radix 模态抽屉。
- 320px 登录页键盘 Enter 提交并显示正确鉴权错误。
- 主流程无 pageerror。

已实际查看桌面工作台、桌面报告、375px 报告、新建分析、文献库与320px登录截图，修复窄屏导航遮挡、密码标签含帮助文字和小文件大小显示为 0.00 MB 等问题。截图在本地 `artifacts/ui-review/`，不提交测试账号和运行证据。

## 容器与 Nginx

- 实际构建 Python API / Worker 镜像和 React / Nginx 镜像。
- 继承生产 Compose 的本机覆盖部署，PostgreSQL / RabbitMQ / API / Worker / Beat / Nginx 全部启动并通过健康检查。
- 真实 Nginx 提供前端路由 fallback，同域代理 API；经 Nginx 完成注册、会话读取和退出。
- 核对入口 CSP、安全头与鉴权状态；`nginx -t` 通过。
- 使用临时本机测试证书验证生产 HTTPS 模板：证书校验通过、API readiness 正常、HTTP 正确跳转 HTTPS。没有申请公网证书。
- PostgreSQL `pg_dump -Fc` 备份已恢复到独立 `paperlens_restore` 库，账号数量与原库一致。

发现 RabbitMQ 新版拒绝临时非独占控制队列，已配置 Celery 独占控制 / 事件队列并完成真实 Worker 回归。发现 Compose `--wait` 对未配置健康检查的 Beat 报错，已补进程健康检查并复验。

## 未完成的外部验收

- 未提供目标服务器、域名、SSH 访问与对象存储信息，因此没有执行线上迁移、DNS / 公网证书配置或真实 Bucket 读写。
- 未提交或推送本轮变更，GitHub Actions 工作流尚未在远端运行；本地测试不等于远端 CI 和生产发布成功。
- 未新增真实 DeepSeek 费用调用、并发压力测试或机器故障演练。
- 发布控制流的失败恢复使用隔离替身测试，未在真实生产环境执行故障切换。
- 未做真实读屏测试；自动化与键盘验收不代表完整 WCAG 认证。

单机仍有整机故障风险。Worker 在模型完成但检查点未保存时异常退出，恢复可能重复收费；正常发布等待 Worker 完成，已保存阶段可以复用。数据库应用回滚以兼容迁移为前提，不自动降级数据库。
