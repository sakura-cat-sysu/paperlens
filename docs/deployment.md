# 生产部署

当前部署目标是 `ssh qqbot-server`，域名 **https://paperlens.aktools.cn**。DNS 已指向服务器。该服务器承载多个项目，采用宿主机 Nginx + 项目专用 rootless Docker，不接管原有 80 / 443 监听或 Docker daemon。

账号、目录和日常操作见 [服务器权限](server-access.md)。

## 服务与入口

宿主机 Nginx 使用 `deploy/nginx/host.conf`，负责 Let's Encrypt 证书和 HTTP → HTTPS 跳转，代理到 **127.0.0.1:18090**。应用容器中的 Nginx 托管 React 并代理 API / SSE。

生产叠加 `compose.yaml` 与 `compose.shared.yaml`。PostgreSQL、RabbitMQ、API 都不映射宿主机公网端口。容器由不可登录的 `paperlens` 账号管理，服务器原有容器不受项目发布命令控制。

4 GB 共用服务器的 Worker 使用一个 prefork 进程，任务进入持久队列依次执行；不减少分析阶段或证据检查。各容器设定内存上限，服务账号 slice 另设 MemoryHigh=1800M、MemoryMax=2100M，避免本项目无限占用其他项目的内存。

`/opt/paperlens/shared-host` 标记启用此部署模式。默认 Compose 仍支持专用服务器，由容器 Nginx 直接负责 HTTPS；不要在当前共用服务器直接执行该默认模式占用 80 / 443。

## 自动部署

仓库配置 `DEPLOY_HOST`、`DEPLOY_USER`、`DEPLOY_SSH_KEY` 和 `DEPLOY_KNOWN_HOSTS` 四个 Actions Secrets。SSH 主机公钥来自已核验的本机 known_hosts，未关闭主机校验。

CI 专用公钥安装在 `ntgmc` 的 authorized_keys，配置 `restrict` 和 forced command。此密钥只接受 `paperlens-deploy <40位SHA>` 和 `paperlens-registry-auth`，不能打开 shell、SCP、端口转发或执行任意管理员命令。

服务端 root 拥有的 `/usr/local/libexec/paperlens-ssh-entry` 校验命令，再切换为 `paperlens` 调用 `/usr/local/libexec/paperlens-receive`。接收器校验发布包路径、类型、体积、提交 SHA 与镜像仓库 / 摘要，只写入项目目录。

镜像存放在 `ccr.ccs.tencentyun.com/ntgmc/paperlens-api` 与 `paperlens-web` 两个私有仓库。服务器上的仓库域名解析到腾讯云内网 `169.254.0.42`，应用更新不从境外镜像仓库下载。公共 PostgreSQL / RabbitMQ 镜像使用服务器已有的腾讯云 Docker Hub 镜像源。

`paperlens-registry-auth` 通过 root 拥有的固定脚本，用服务器现有腾讯云仓库身份签发有效期约 2 小时、仅限两个 PaperLens 仓库的令牌。管理员的完整仓库密码不进入 CI；签发脚本核对仓库范围与有效期。工作流使用标准 Docker `registrytoken` 配置推送镜像，再通过 SSH 标准输入传送同一个短期令牌和发布包。临时配置在任务结束后清理，不保存个人 GitHub 令牌。

发布顺序：

1. push `main`，Quality 执行 Python、前端、契约、Playwright 和实际容器检查。
2. 检查成功后，Deploy production 从同一提交构建 API / Web 镜像并推送腾讯云私有仓库。
3. 镜像使用固定 digest；提交 SHA、Compose 和脚本打包，经受限 SSH 入口发送。
4. 服务端获取部署锁，拉取镜像，备份数据库，执行 Alembic 迁移。
5. 等待旧 Worker 完成，替换 API / Worker / Beat / Web。
6. 通过真实 HTTPS 入口核对 API 与前端 SHA，成功后提升 `current`。

Quality 失败、PR 和过时的 main 提交不部署。部署串行执行，失败恢复上一应用 release；数据库不自动降级，结构迁移必须与上一版本兼容。

## 配置与模型

生产配置位于 `/opt/paperlens/.env`，权限 0600，归服务账号所有。数据库 / 队列各使用独立随机密码，公开注册关闭，初始文件存储使用私有持久卷。

模型需要管理员配置：

```dotenv
OPENAI_API_KEY=
OPENAI_BASE_URL=https://api.deepseek.com
OPENAI_MODEL=deepseek-flash
```

没有密钥时页面明确显示模型尚未配置，不能提交分析，不生成虚假结果。修改配置后按服务器权限文档重建 API / Worker / Beat。密钥不写入仓库或 Actions 日志。

## 证书

证书使用 webroot `/var/www/paperlens-acme`，宿主机现有 Certbot 定时任务负责续期，成功后 reload Nginx。此模式不运行容器内的证书续期脚本。

```bash
sudo certbot renew --cert-name paperlens.aktools.cn --dry-run
```

不要切换成 standalone 占用 80 端口。新增域名配置经过 `nginx -t` 后平滑 reload，不停止其他站点。

## 检查与备份

```bash
paperlensctl status
paperlensctl logs
paperlensctl backup
curl --fail https://paperlens.aktools.cn/api/health/ready
curl --fail https://paperlens.aktools.cn/release.json
```

两端 release 应与预期提交相同。readiness 验证 API 与数据库结构可读，Worker / RabbitMQ 由容器健康检查验证。应用账号、上传和报告还需真实任务验收。

部署前和 `paperlensctl backup` 会生成 PostgreSQL 自定义格式备份，位于私密目录 `/opt/paperlens/backups`。数据库包含提取正文、任务、报告和账号，备份也需要保密。数据库备份不包含原始 PDF 字节；本地文件卷需要一起备份。

异机备份目的地与保留周期需由管理员配置；不自动删除生产数据或备份。恢复先对独立空库执行 `pg_restore --no-owner`，检查账号、文献、报告和文件读取后再安排正式切换。正式恢复前停止写入并保留当前数据副本。

单机发布会短暂重建连接，数据库和文件卷保留。不要将 `docker compose down -v`、清空数据库或删除卷作为发布步骤。模型已完成但检查点尚未保存时进程异常退出，恢复可能重复执行该请求。
