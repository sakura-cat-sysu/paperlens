"""管理员在服务器终端开通账号、重置密码、授予管理员或签发邀请码。

密码始终交互读取，不通过命令行参数传递。
"""

import argparse
from getpass import getpass

from sqlalchemy import delete, select

from backend.admin import generate_code, mask
from backend.auth import digest, password_hash
from backend.database import InviteCode, LoginSession, User, now, session_factory
from backend.schemas import Credentials

PASSWORD_ACTIONS = ("create-user", "create-admin", "reset-password")


def read_password(parser):
    password = getpass("密码（至少 12 个字符）: ")
    if password != getpass("再次输入密码: "):
        parser.error("两次密码不一致")
    return password


def main():
    parser = argparse.ArgumentParser(description="PaperLens 账号与邀请码管理")
    parser.add_argument(
        "action",
        choices=(*PASSWORD_ACTIONS, "grant-admin", "revoke-admin", "issue-invite", "list-invites"),
    )
    parser.add_argument("email", nargs="?", help="账号邮箱；issue-invite 和 list-invites 不需要")
    parser.add_argument("--max-uses", type=int, default=1, help="邀请码可用次数，默认 1")
    parser.add_argument("--days", type=int, default=14, help="邀请码有效天数，默认 14；0 表示永不过期")
    parser.add_argument("--note", default="", help="邀请码备注")
    parser.add_argument("--admin", action="store_true", help="邀请码注册后直接成为管理员")
    args = parser.parse_args()

    if args.action in ("issue-invite", "list-invites"):
        handle_invites(args, parser)
        return

    if not args.email:
        parser.error("该操作需要提供邮箱")

    password = read_password(parser) if args.action in PASSWORD_ACTIONS else None
    email = Credentials(email=args.email, password=password or "placeholder-password").email

    with session_factory()() as session:
        user = session.scalar(select(User).where(User.email == email))
        if args.action in ("create-user", "create-admin"):
            if user:
                parser.error("账号已存在")
            session.add(
                User(
                    email=email,
                    password_hash=password_hash(password),
                    is_admin=args.action == "create-admin",
                )
            )
            message = "管理员账号已创建。" if args.action == "create-admin" else "账号已创建。"
        elif args.action == "reset-password":
            if user is None:
                parser.error("账号不存在")
            user.password_hash = password_hash(password)
            session.execute(delete(LoginSession).where(LoginSession.user_id == user.id))
            message = "密码已更新，旧登录会话已撤销。"
        else:
            if user is None:
                parser.error("账号不存在")
            user.is_admin = args.action == "grant-admin"
            message = "已授予管理员权限。" if user.is_admin else "已移除管理员权限。"
        session.commit()
    print(message)


def handle_invites(args, parser):
    with session_factory()() as session:
        if args.action == "list-invites":
            invites = session.scalars(
                select(InviteCode).order_by(InviteCode.created_at.desc()).limit(50)
            ).all()
            if not invites:
                print("暂无邀请码。")
                return
            print(f"{'邀请码':<12}{'状态':<10}{'用量':<10}{'管理员':<8}备注")
            for invite in invites:
                flag = "是" if invite.grants_admin else "否"
                usage = f"{invite.used_count}/{invite.max_uses}"
                print(f"{invite.code_hint:<12}{invite.state():<10}{usage:<10}{flag:<8}{invite.note}")
            return

        if args.max_uses < 1:
            parser.error("--max-uses 必须大于 0")
        code = generate_code()
        from datetime import timedelta

        session.add(
            InviteCode(
                code_hash=digest(code),
                code_hint=mask(code),
                note=args.note.strip(),
                grants_admin=args.admin,
                max_uses=args.max_uses,
                expires_at=now() + timedelta(days=args.days) if args.days else None,
            )
        )
        session.commit()
    grouped = "-".join(code[i : i + 4] for i in range(0, len(code), 4))
    expiry = f"{args.days} 天后过期" if args.days else "永不过期"
    print(f"邀请码：{grouped}")
    print(f"可用 {args.max_uses} 次，{expiry}{'，注册后为管理员' if args.admin else ''}。")
    print("请妥善转交，此码不会再次显示。")


if __name__ == "__main__":
    main()
