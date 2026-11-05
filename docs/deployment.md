# 生产部署

当前部署目标为 `ssh qqbot-server`，域名 **https://paperlens.aktools.cn**。DNS 已指向服务器。该服务器承载多个项目，采用宿主机 Nginx + 项目专用 rootless Docker，不接管原有 80 / 443 监听或 Docker daemon。

账号、目录和日常操作见 [服务器权限](server-access.md)。

## 发布链路

```text
push main → GitHub Quality → 传送约 200 KB 的 Git 源码归档
          → 服务账号使用国内源在本机构建 → 备份与迁移
          → 更新服务 → 经公网 HTTPS 核对前后端提交 SHA
```

服务器境外网络慢，采用源码传输与国内构建：

- Python / uv：腾讯云 PyPI 镜像，依赖从 `uv.lock` 导出并校验哈希，版本保持锁定。
- npm：`registry.npmmirror.com`，使用 `npm ci` 和锁文件完整性校验。
- Python / Node / Nginx / PostgreSQL / RabbitMQ 基础镜像：rootless Docker 配置服务器原有的腾讯云镜像源，通过内网下载。
- 应用镜像保存在服务器本机，不上传或拉取境外仓库，也不跨境传输整个应用镜像。

首次构建需要下载依赖，后续复用 Docker 层缓存。构建与运行共同受服务账号 slice 的 CPU / 内存上限限制，不能无限占用其他项目资源。

## 自动部署与权限

仓库有四项 Actions Secrets：`DEPLOY_HOST`、`DEPLOY_USER`、`DEPLOY_SSH_KEY` 和 `DEPLOY_KNOWN_HOSTS`。SSH 主机公钥来自已核验的本机 known_hosts，未关闭主机校验。

CI 公钥安装在 `ntgmc` 的 authorized_keys，配置 `restrict` 和 forced command，只接受 `paperlens-deploy <40位SHA>`，不能打开 shell、SCP、端口转发或执行任意管理员命令。服务器不保存 GitHub 令牌，CI 也不取得服务器现有镜像仓库的密码。

root 拥有的 `/usr/local/libexec/paperlens-ssh-entry` 校验命令，再切换为不可登录的 `paperlens` 账号调用 `/usr/local/libexec/paperlens-receive`。接收器校验 Git 归档中的提交 SHA、文件类型、路径和体积，只写入项目 release 目录。归档由 `git archive` 生成，不包含未跟踪的 `.env`、凭据或缓存。

部署使用 `compose.yaml` + `compose.shared.yaml`：

1. Quality 运行 Python、前端、契约、Playwright 和真实容器检查。
2. 仅 main 的 push 检查成功触发 Deploy production；PR、失败检查与过时提交不部署。
3. 服务器取得部署锁，使用国内源构建 API / Web；构建失败保留上一应用。
4. 将两个本机镜像的内容 ID 写入 `images.env`，避免 tag 被改写影响已发布版本。
5. 检查数据库 / 队列，执行数据库备份和 Alembic 迁移。
6. 等待旧 Worker 完成，替换 API / Worker / Beat / Web，核对两端 SHA后提升 `current`。

发布串行执行，失败恢复上一应用镜像；数据库不自动降级，迁移必须保持与上一版本兼容。回滚所需的镜像与 release 不会自动删除，不要清理仍需回滚的镜像。

## 服务与入口

宿主机 Nginx 使用 `deploy/nginx/host.conf`，负责 Let's Encrypt 证书和 HTTP → HTTPS 跳转，代理到 **127.0.0.1:18090**。应用容器内的 Nginx 托管 React 并代理 API / SSE。

PostgreSQL、RabbitMQ、API 不映射宿主机公网端口。服务由 `paperlens` 的独立 rootless Docker 管理；服务器原有容器不受项目发布命令控制。

4 GB 共用服务器使用一个 prefork Worker，任务进入持久队列依次执行；不减少分析阶段或证据检查。容器各有内存上限，服务账号 slice 另设 CPUQuota=200%、MemoryHigh=1800M、MemoryMax=2100M。这些上限覆盖构建和运行进程。

`/opt/paperlens/shared-host` 标记启用国内构建与宿主机代理模式。默认 Compose 仍支持专用服务器的独立 HTTPS 入口；不要在当前共用服务器直接执行默认模式占用 80 / 443。

## 配置与模型

生产配置为 `/opt/paperlens/.env`，0600，归服务账号所有。数据库与队列使用不同随机密码，公开注册关闭，初始文件存储为私有持久卷。

游客体验默认开启，由新增数据库迁移建立独立游客身份及来源创建限流表，原有账号保持普通账号属性。生产未配置新变量时按游客每天 10 次、普通账号每天 20 次运行；`ALLOW_GUESTS=false` 可关闭游客体验，`GUEST_DAILY_ANALYSES`、`GUEST_MAX_DOCUMENTS` 与 `GUEST_ENTRIES_PER_WINDOW` 可分别调整游客分析次数、文献容量和每来源 15 分钟新建游客上限。额度在 UTC 零点重置。部署流程先执行迁移，再启动新版 API；不要直接启动尚未迁移数据库的新版服务。

模型需要管理员配置：

```dotenv
OPENAI_API_KEY=
OPENAI_BASE_URL=https://api.deepseek.com
OPENAI_MODEL=deepseek-flash
OPENAI_PROTOCOL=chat
OPENAI_STREAM=false
```

`OPENAI_PROTOCOL` 支持 `chat`、`responses`、`messages`，分别对应 Chat Completions、Responses、Anthropic Messages；均使用 `OPENAI_API_KEY` 和 `OPENAI_MODEL`。`OPENAI_STREAM=true` 启用上游 SSE，完整接收后再校验和保存。根地址与完整接口地址均可填写，网关前缀会保留；具体地址规则和兼容重试见 [模型配置](../README.md#模型配置)。新增变量不填时保持原有 Chat 非流式方式。

没有密钥时页面明确提示模型尚未配置，不能提交分析，不生成模拟结果。修改配置后按服务器权限文档重建 API / Worker / Beat。密钥不写入仓库或 Actions 日志。

## 证书、检查与备份

证书使用 webroot `/var/www/paperlens-acme`，宿主机现有 Certbot 定时续期，成功后 reload Nginx。不要使用 standalone 抢占 80 端口，也不运行容器内续期脚本。

```bash
sudo certbot renew --cert-name paperlens.aktools.cn --dry-run --no-random-sleep-on-renew
paperlensctl status
paperlensctl logs
paperlensctl backup
curl --fail https://paperlens.aktools.cn/api/health/ready
curl --fail https://paperlens.aktools.cn/release.json
```

两端 release 应与预期提交相同。readiness 检查 API 与数据库结构，Worker / RabbitMQ 由容器健康检查验证，应用功能还需真实登录与任务验收。

部署前和 `paperlensctl backup` 会生成 PostgreSQL 自定义格式备份，位于 `/opt/paperlens/backups`。备份包含正文、任务、报告与账号，需要保密。数据库备份不含原始 PDF，持久文件卷需要一起备份。

异机备份目的地与保留周期仍需由管理员配置，不自动删除生产数据或备份。恢复先对独立空库执行 `pg_restore --no-owner`，核对账号、文献、报告和文件读取，再安排正式切换。正式恢复前停止写入并保留当前数据副本。

单机发布会短暂重建连接，数据库和文件卷保留。不要将 `docker compose down -v`、清空数据库或删除卷作为更新步骤。模型已完成但检查点未保存时异常退出，恢复可能重复执行该请求。
