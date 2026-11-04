import hashlib
import hmac
import os
import secrets
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from backend.database import (
    GuestEntryRate, GuestIdentity, InviteCode, LoginAttempt, LoginSession, User,
    database, identifier, now,
)
from backend.schemas import AuthView, Credentials, RegistrationRequest, UserView
from backend.settings import settings

router = APIRouter(prefix="/auth", tags=["auth"])
DB = Annotated[Session, Depends(database)]
COOKIE = "paperlens_session"
GUEST_COOKIE = "paperlens_guest"
GUEST_DAYS = 30


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
    if user.is_guest and not settings().allow_guests:
        raise HTTPException(403, "游客体验已暂停，请使用正式账号登录。")
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def current_admin(user: CurrentUser) -> User:
    if not user.is_admin:
        raise HTTPException(403, "需要管理员权限。")
    return user


CurrentAdmin = Annotated[User, Depends(current_admin)]


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


def normalize_code(value: str) -> str:
    return value.strip().replace("-", "").replace(" ", "").upper()


def reserve_guest_entry(request: Request, db: Session):
    """数据库行锁限制同一来源创建身份，所有 API 进程共同计数。"""
    current = now()
    address = digest(request.client.host if request.client else "unknown")
    db.execute(delete(GuestEntryRate).where(
        GuestEntryRate.window_started_at < current - timedelta(days=1)
    ))
    db.execute(insert(GuestEntryRate).values(
        address_hash=address, window_started_at=current, created=0
    ).on_conflict_do_nothing(index_elements=[GuestEntryRate.address_hash]))
    rate = db.scalar(select(GuestEntryRate).where(
        GuestEntryRate.address_hash == address
    ).with_for_update())
    if rate.window_started_at <= current - timedelta(minutes=15):
        rate.window_started_at = current
        rate.created = 0
    if rate.created >= settings().guest_entries_per_window:
        raise HTTPException(429, "当前网络创建游客过于频繁，请稍后再试或使用已有账号登录。")
    rate.created += 1


@router.post("/guest", response_model=AuthView)
def guest(request: Request, response: Response, db: DB):
    if not settings().allow_guests:
        raise HTTPException(403, "游客体验暂未开放，请使用账号登录。")
    # 已登录时返回当前身份，不覆盖正式账号，也不创建额外游客。
    login_token = request.cookies.get(COOKIE, "")
    session = db.get(LoginSession, digest(login_token)) if login_token else None
    if session is not None and session.expires_at > now():
        user = db.get(User, session.user_id)
        if user is not None:
            return AuthView(user=UserView.model_validate(user), csrf_token=session.csrf_token)

    token = request.cookies.get(GUEST_COOKIE, "")
    identity = db.get(GuestIdentity, digest(token)) if token else None
    user = db.get(User, identity.user_id) if identity and identity.expires_at > now() else None
    if user is None or not user.is_guest:
        reserve_guest_entry(request, db)
        token = secrets.token_urlsafe(32)
        user = User(
            id=identifier(),
            email=f"guest-{identifier()}@guest.invalid",
            password_hash="!guest-password-login-disabled",
            is_guest=True,
            is_admin=False,
        )
        db.add(user)
        db.flush()
        identity = GuestIdentity(token_hash=digest(token), user_id=user.id, expires_at=now())
        db.add(identity)
    identity.expires_at = now() + timedelta(days=GUEST_DAYS)
    result = login_response(user, response, db)
    # 独立于登录会话保存，退出后再次进入仍复用文献与当天额度。
    response.set_cookie(
        GUEST_COOKIE, token, httponly=True, secure=settings().secure_cookies,
        samesite="lax", max_age=GUEST_DAYS * 86400, path="/",
    )
    return result


def claim_invite(code: str, db: Session) -> InviteCode:
    """校验并占用一次邀请码。行锁避免并发超额使用。"""
    invite = db.scalar(
        select(InviteCode).where(InviteCode.code_hash == digest(normalize_code(code))).with_for_update()
    )
    if invite is None or not invite.usable():
        raise HTTPException(403, "邀请码无效或已失效，请向管理员索取新的邀请码。")
    invite.used_count += 1
    return invite


@router.post("/register", response_model=AuthView, status_code=201)
def register(payload: RegistrationRequest, request: Request, response: Response, db: DB):
    if not settings().allow_registration:
        raise HTTPException(403, "当前未开放注册，请联系管理员开通账号。")
    check_attempts(request, payload.email, db)
    invite = claim_invite(payload.invite_code, db)
    user = User(
        email=payload.email,
        password_hash=password_hash(payload.password),
        is_admin=invite.grants_admin,
    )
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
    encoded = user.password_hash if user and not user.is_guest else DUMMY_PASSWORD_HASH
    valid = password_matches(credentials.password, encoded)
    if user is None or user.is_guest or not valid:
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
