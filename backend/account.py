"""账号设置：查看状态、修改密码，管理多套模型配置。

管理员可以维护多套全局配置，每个账号也可以保存多套个人配置。
分析任务创建时选定用哪一条；没选时按「最新个人 > 最新全局 > .env」回退。
密钥加密后入库，接口只返回掩码。
"""

from fastapi import APIRouter, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.auth import (
    AuthSession,
    CurrentAdmin,
    CurrentUser,
    DB,
    password_hash,
    password_matches,
)
from backend.database import LoginSession, ModelConfig, User
from backend.jobs import usage_view
from backend.schemas import (
    AccountView,
    ModelConfigUpdate,
    ModelConfigView,
    PasswordChange,
    UserView,
)
from backend.secrets import SecretError, decrypt, encrypt, hint
from config import Settings, load_settings

router = APIRouter(tags=["account"])

GLOBAL_NAME = "全局配置"
ENVIRONMENT_NAME = "服务器 .env"
DEFAULT_MODEL = "deepseek-flash"


class ConfigNotFound(RuntimeError):
    """选定的配置不存在，或不属于当前账号。"""


class ConfigUnusable(RuntimeError):
    """配置存在但没有可用密钥。"""


def personal_configs(session: Session, user_id: str) -> list[ModelConfig]:
    return list(
        session.scalars(
            select(ModelConfig)
            .where(ModelConfig.owner_id == user_id)
            .order_by(ModelConfig.created_at, ModelConfig.name)
        )
    )


def global_configs(session: Session) -> list[ModelConfig]:
    return list(
        session.scalars(
            select(ModelConfig)
            .where(ModelConfig.owner_id.is_(None))
            .order_by(ModelConfig.created_at, ModelConfig.name)
        )
    )


def global_config(session: Session) -> ModelConfig | None:
    """回退时取最新的一条全局配置。"""
    rows = global_configs(session)
    return rows[-1] if rows else None


def _settings_from(row: ModelConfig) -> Settings:
    if not row.api_key_cipher:
        raise ConfigUnusable("所选模型配置还没有填写密钥，请先补全。")
    environment = load_settings()
    return Settings(
        api_key=decrypt(row.api_key_cipher),
        base_url=(row.base_url or "").strip() or environment.base_url,
        model=(row.model or "").strip() or environment.model,
        protocol=(row.protocol or "chat"),
    )


def settings_for(session: Session, user_id: str, config_id: str | None = None) -> Settings:
    """解析本次要用的模型配置。config_id 为空时按默认顺序回退。"""
    if config_id:
        row = session.get(ModelConfig, config_id)
        if row is None or row.owner_id not in (None, user_id):
            raise ConfigNotFound("所选模型配置不存在或无权使用，请重新选择。")
        return _settings_from(row)
    for row in reversed(personal_configs(session, user_id)):
        if row.api_key_cipher:
            return _settings_from(row)
    fallback = global_config(session)
    if fallback is not None and fallback.api_key_cipher:
        return _settings_from(fallback)
    return load_settings()


def has_any_config(session: Session, user_id: str) -> bool:
    try:
        return not settings_for(session, user_id).missing
    except (ConfigNotFound, ConfigUnusable, SecretError):
        return False


def _view(row: ModelConfig, scope: str) -> ModelConfigView:
    return ModelConfigView(
        id=row.id,
        scope=scope,
        name=row.name,
        configured=bool(row.api_key_cipher),
        api_key_hint=row.api_key_hint,
        base_url=row.base_url,
        model=row.model,
        protocol=row.protocol or "chat",
        updated_at=row.updated_at,
    )


def _environment_view() -> ModelConfigView:
    environment = load_settings()
    return ModelConfigView(
        id=None,
        scope="environment",
        name=ENVIRONMENT_NAME,
        configured=not environment.missing,
        api_key_hint="",
        base_url=environment.base_url,
        model=environment.model,
        protocol=environment.protocol,
    )


def options(session: Session, user_id: str) -> list[ModelConfigView]:
    """分析页可选的配置：全部全局配置、本人的个人配置，最后是服务器 .env。"""
    views = [_view(row, "global") for row in global_configs(session) if row.api_key_cipher]
    views += [
        _view(row, "personal")
        for row in personal_configs(session, user_id)
        if row.api_key_cipher
    ]
    if not load_settings().missing:
        views.append(_environment_view())
    return views


def _apply(row: ModelConfig, payload: ModelConfigUpdate) -> None:
    key = (payload.api_key or "").strip()
    if key:
        row.api_key_cipher = encrypt(key)
        row.api_key_hint = hint(key)
    row.base_url = (payload.base_url or "").strip()
    row.model = (payload.model or "").strip()
    row.protocol = payload.protocol or "chat"


def _require_key(payload: ModelConfigUpdate, row: ModelConfig | None = None) -> None:
    """新建必须有密钥；编辑时留空表示沿用已保存的密钥。"""
    if (payload.api_key or "").strip():
        return
    if row is None or not row.api_key_cipher:
        raise HTTPException(400, "请填写 API Key。")


def account_view(session: Session, user: User) -> AccountView:
    environment = load_settings()
    return AccountView(
        user=UserView.model_validate(user),
        created_at=user.created_at,
        usage=usage_view(session, user),
        models=[_view(item, "personal") for item in personal_configs(session, user.id)],
        global_models=[_view(item, "global") for item in global_configs(session)],
        environment_configured=not environment.missing,
        default_model=environment.model or DEFAULT_MODEL,
        default_base_url=environment.base_url,
        default_protocol=environment.protocol or "chat",
    )


@router.get("/account", response_model=AccountView)
def read_account(user: CurrentUser, db: DB):
    return account_view(db, user)


@router.get("/models", response_model=list[ModelConfigView])
def list_models(user: CurrentUser, db: DB):
    return options(db, user.id)


@router.post("/account/password", status_code=204)
def change_password(payload: PasswordChange, session: AuthSession, user: CurrentUser, db: DB):
    if not password_matches(payload.current_password, user.password_hash):
        raise HTTPException(400, "当前密码不正确。")
    if payload.current_password == payload.new_password:
        raise HTTPException(400, "新密码不能与当前密码相同。")
    user.password_hash = password_hash(payload.new_password)
    # 改密后让其他设备上的会话失效，当前会话保留。
    db.execute(
        delete(LoginSession).where(
            LoginSession.user_id == user.id, LoginSession.token_hash != session.token_hash
        )
    )
    db.commit()


@router.post("/account/models", response_model=ModelConfigView, status_code=201)
def create_config(payload: ModelConfigUpdate, user: CurrentUser, db: DB):
    _require_key(payload)
    name = payload.name or f"配置 {len(personal_configs(db, user.id)) + 1}"
    row = ModelConfig(owner_id=user.id, name=name)
    _apply(row, payload)
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "配置备注已存在，请换一个。") from None
    return _view(row, "personal")


@router.put("/account/models/{config_id}", response_model=ModelConfigView)
def update_config(config_id: str, payload: ModelConfigUpdate, user: CurrentUser, db: DB):
    row = db.get(ModelConfig, config_id)
    if row is None or row.owner_id != user.id:
        raise HTTPException(404, "配置不存在。")
    _require_key(payload, row)
    if payload.name:
        row.name = payload.name
    _apply(row, payload)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "配置备注已存在，请换一个。") from None
    return _view(row, "personal")


@router.delete("/account/models/{config_id}", status_code=204)
def delete_config(config_id: str, user: CurrentUser, db: DB):
    row = db.get(ModelConfig, config_id)
    if row is None or row.owner_id != user.id:
        raise HTTPException(404, "配置不存在。")
    db.delete(row)
    db.commit()


@router.get("/admin/models", response_model=list[ModelConfigView])
def list_global_models(admin: CurrentAdmin, db: DB):
    return [_view(row, "global") for row in global_configs(db)]


@router.post("/admin/models", response_model=ModelConfigView, status_code=201)
def create_global_model(payload: ModelConfigUpdate, admin: CurrentAdmin, db: DB):
    _require_key(payload)
    existing = global_configs(db)
    name = payload.name or (
        GLOBAL_NAME if not existing else f"{GLOBAL_NAME} {len(existing) + 1}"
    )
    row = ModelConfig(owner_id=None, name=name)
    _apply(row, payload)
    db.add(row)
    db.commit()
    return _view(row, "global")


@router.put("/admin/models/{config_id}", response_model=ModelConfigView)
def update_global_model(config_id: str, payload: ModelConfigUpdate, admin: CurrentAdmin, db: DB):
    row = db.get(ModelConfig, config_id)
    if row is None or row.owner_id is not None:
        raise HTTPException(404, "配置不存在。")
    _require_key(payload, row)
    if payload.name:
        row.name = payload.name
    _apply(row, payload)
    db.commit()
    return _view(row, "global")


@router.delete("/admin/models/{config_id}", status_code=204)
def delete_global_model(config_id: str, admin: CurrentAdmin, db: DB):
    row = db.get(ModelConfig, config_id)
    if row is None or row.owner_id is not None:
        raise HTTPException(404, "配置不存在。")
    db.delete(row)
    db.commit()
