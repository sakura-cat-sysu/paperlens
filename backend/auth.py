import hashlib
import hmac
import os
import secrets
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.database import LoginAttempt, LoginSession, User, database, now
from backend.schemas import AuthView, Credentials, UserView
from backend.settings import settings

router = APIRouter(prefix="/auth", tags=["auth"])
DB = Annotated[Session, Depends(database)]
COOKIE = "paperlens_session"


def password_hash(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1)
    return salt.hex() + ":" + digest.hex()


def password_matches(password: str, encoded: str) -> bool:
    salt, expected = encoded.split(":")
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1)
    return hmac.compare_digest(digest.hex(), expected)


def digest(value: str):
    return hashlib.sha256(value.encode()).hexdigest()


DUMMY_PASSWORD_HASH = password_hash("unavailable-account")


def current_session(request: Request, db: DB) -> LoginSession:
    token = request.cookies.get(COOKIE, "")
    session = db.get(LoginSession, digest(token)) if token else None
    if session is None or session.expires_at <= now():
        raise HTTPException(401, "请先登录。")
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        if not hmac.compare_digest(request.headers.get("x-csrf-token", ""), session.csrf_token):
            raise HTTPException(403, "页面验证已失效，请刷新后重试。")
    return session


AuthSession = Annotated[LoginSession, Depends(current_session)]


def current_user(session: AuthSession, db: DB) -> User:
    user = db.get(User, session.user_id)
    if user is None:
        raise HTTPException(401, "请重新登录。")
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def login_response(user: User, response: Response, db: Session):
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_hex(32)
    db.execute(delete(LoginSession).where(LoginSession.expires_at < now()))
    db.add(
        LoginSession(
            token_hash=digest(token), user_id=user.id, csrf_token=csrf, expires_at=now() + timedelta(days=7)
        )
    )
    db.commit()
    response.set_cookie(
        COOKIE,
        token,
        httponly=True,
        secure=settings().secure_cookies,
        samesite="lax",
        max_age=7 * 86400,
        path="/",
    )
    return AuthView(user=UserView.model_validate(user), csrf_token=csrf)


def check_attempts(request: Request, email: str, db: Session):
    address = digest(request.client.host if request.client else "unknown")
    cutoff = now() - timedelta(minutes=15)
    db.execute(delete(LoginAttempt).where(LoginAttempt.created_at < cutoff))
    count = db.scalar(
        select(func.count())
        .select_from(LoginAttempt)
        .where(or_(LoginAttempt.address_hash == address, LoginAttempt.email == email))
    )
    if count >= 10:
        db.commit()
        raise HTTPException(429, "尝试次数过多，请在 15 分钟后重试。")
    db.add(LoginAttempt(address_hash=address, email=email))
    db.commit()


@router.post("/register", response_model=AuthView, status_code=201)
def register(credentials: Credentials, request: Request, response: Response, db: DB):
    if not settings().allow_registration:
        raise HTTPException(403, "当前未开放注册，请联系管理员开通账号。")
    check_attempts(request, credentials.email, db)
    user = User(email=credentials.email, password_hash=password_hash(credentials.password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "此邮箱无法注册，请登录或联系管理员。") from None
    return login_response(user, response, db)


@router.post("/login", response_model=AuthView)
def login(credentials: Credentials, request: Request, response: Response, db: DB):
    check_attempts(request, credentials.email, db)
    user = db.scalar(select(User).where(User.email == credentials.email))
    # 未知邮箱也做一次相同成本的校验。
    encoded = user.password_hash if user else DUMMY_PASSWORD_HASH
    valid = password_matches(credentials.password, encoded)
    if user is None or not valid:
        raise HTTPException(401, "邮箱或密码不正确。")
    db.execute(delete(LoginAttempt).where(LoginAttempt.email == credentials.email))
    return login_response(user, response, db)


@router.get("/me", response_model=AuthView)
def me(session: AuthSession, user: CurrentUser):
    return AuthView(user=UserView.model_validate(user), csrf_token=session.csrf_token)


@router.post("/logout", status_code=204)
def logout(session: AuthSession, response: Response, db: DB):
    db.delete(session)
    db.commit()
    response.delete_cookie(COOKIE, path="/")
