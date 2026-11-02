"""管理员在服务器终端开通账号或重置密码，不通过命令行参数传密码。"""

import argparse
from getpass import getpass

from sqlalchemy import delete, select

from backend.auth import password_hash
from backend.database import LoginSession, User, session_factory
from backend.schemas import Credentials


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("create-user", "reset-password"))
    parser.add_argument("email")
    args = parser.parse_args()
    password = getpass("密码（至少 12 个字符）: ")
    if password != getpass("再次输入密码: "):
        parser.error("两次密码不一致")
    credentials = Credentials(email=args.email, password=password)
    with session_factory()() as session:
        user = session.scalar(select(User).where(User.email == credentials.email))
        if args.action == "create-user":
            if user:
                parser.error("账号已存在")
            session.add(User(email=credentials.email, password_hash=password_hash(password)))
        else:
            if user is None:
                parser.error("账号不存在")
            user.password_hash = password_hash(password)
            session.execute(delete(LoginSession).where(LoginSession.user_id == user.id))
        session.commit()
    print("账号已创建。" if args.action == "create-user" else "密码已更新，旧登录会话已撤销。")


if __name__ == "__main__":
    main()
