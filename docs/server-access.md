# PaperLens 服务器权限

目标为 `ssh qqbot-server`，站点为 **https://paperlens.aktools.cn**。服务器还运行其他项目，PaperLens 不使用宿主机的 Docker socket。

| 账号 | 用途 | 权限 |
| --- | --- | --- |
| `ntgmc` | 服务器管理者 | 保留原有 sudo、Docker 和其他项目权限；加入 `paperlens` 组 |
| `paperlens-dev1` | 协作者 1 | 独立 SSH 登录、个人主目录、共享工作区、受限项目命令 |
| `paperlens-dev2` | 协作者 2 | 同上，凭据独立 |
| `paperlens-dev3` | 协作者 3 | 同上，凭据独立 |
| `paperlens` | 服务账号 | 锁定密码、`nologin`；拥有本项目 rootless Docker、运行文件和数据 |

四个个人账号共同加入 `paperlens` 项目组。三个协作者和服务账号另加入 `paperlens-isolated`，其他项目根目录、Nginx 与证书配置通过 ACL 对此组禁止访问。`ntgmc` 不在隔离组，原有访问不受影响。

协作者不属于 `sudo`、宿主机 `docker` 或其他项目用户组。受限 sudo 只允许切换为 `paperlens` 执行 root 拥有的 `paperlensctl`，不能执行任意 shell、Docker 或 systemctl。SSH 对隔离组关闭端口转发、Agent 转发、X11 和用户 rc。

## 登录与日常操作

```bash
ssh paperlens-dev1@paperlens.aktools.cn
```

初始密码单独交接，首次登录必须修改。三个账号互不共用密码，个人主目录不对其他账号开放。可以由管理员为每个人配置自己的 SSH 公钥，不要共用管理员私钥。

```bash
cd /opt/paperlens/workspace
paperlensctl status
paperlensctl logs
paperlensctl restart
paperlensctl backup
```

`workspace` 是可共同读写的工作目录，使用 setgid 和默认 ACL 保留项目组写权限。生产 release 由 CI 发布，编辑工作区不会直接改变运行中的容器。

| 路径 | 内容 |
| --- | --- |
| `/opt/paperlens/workspace` | 人工协作工作区 |
| `/opt/paperlens/releases/<SHA>` | 不可变发布包 |
| `/opt/paperlens/current` | 当前成功发布 |
| `/opt/paperlens/.env` | 仅服务账号可读的生产配置，由管理员修改 |
| `/opt/paperlens/backups` | 私密数据库备份 |
| `/var/lib/paperlens` | 服务账号主目录与独立 Docker 数据 |
| `/run/user/990/docker.sock` | 本机实际分配 UID 对应的 rootless socket，仅服务账号可用 |

## 管理员操作

查看项目服务账号的 Docker（990 是本服务器已分配的服务 UID）：

```bash
sudo -u paperlens env HOME=/var/lib/paperlens \
  DOCKER_HOST=unix:///run/user/990/docker.sock docker ps
```

查看 rootless daemon：

```bash
sudo -u paperlens env XDG_RUNTIME_DIR=/run/user/990 \
  DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/990/bus systemctl --user status docker
```

修改 `/opt/paperlens/.env` 后，需以服务账号运行对应 Compose `up -d --force-recreate`，普通 `restart` 不重新读取环境变量。管理员可执行：

```bash
sudo -u paperlens env HOME=/var/lib/paperlens \
  DOCKER_HOST=unix:///run/user/990/docker.sock bash -c '
    root=/opt/paperlens
    release=$(readlink -f "$root/current")
    source "$release/deploy/compose.sh"
    compose up -d --force-recreate --wait api worker scheduler
  '
```

不要把协作者加入宿主机 Docker 组，也不要授予 `sudo docker`、任意 `sudo -u paperlens bash` 或 root systemctl 权限。rootless Docker 的权限上限是服务账号，不能因此管理宿主机现有容器。

账号权限不等于完整的多租户隔离：服务器仍共用内核和部分网络。应用数据有额外的账号归属校验；对恶意租户的强隔离应采用独立虚拟机。
