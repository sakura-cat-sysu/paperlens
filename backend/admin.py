"""管理员接口：签发、查看和吊销注册邀请码。"""

import secrets
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.auth import CurrentAdmin, digest
from backend.database import InviteCode, database, now
from backend.schemas import InviteCreate, InviteIssued, InviteView

router = APIRouter(prefix="/admin", tags=["admin"])
DB = Annotated[Session, Depends(database)]

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # 去掉易混淆的 I O 0 1


def generate_code() -> str:
    """生成 16 位邀请码，展示时按 4 位分组。"""
    return "".join(secrets.choice(ALPHABET) for _ in range(16))


def mask(code: str) -> str:
    """展示用掩码：保留前两位和后两位。"""
    return f"{code[:2]}****{code[-2:]}"


def view(invite: InviteCode) -> InviteView:
    return InviteView(
        id=invite.id,
        code_hint=invite.code_hint,
        note=invite.note,
        grants_admin=invite.grants_admin,
        max_uses=invite.max_uses,
        used_count=invite.used_count,
        state=invite.state(),
        expires_at=invite.expires_at,
        created_at=invite.created_at,
    )


@router.post("/invites", response_model=InviteIssued, status_code=201)
def issue_invite(payload: InviteCreate, admin: CurrentAdmin, db: DB):
    code = generate_code()
    invite = InviteCode(
        code_hash=digest(code),
        code_hint=mask(code),
        note=payload.note,
        issued_by=admin.id,
        grants_admin=payload.grants_admin,
        max_uses=payload.max_uses,
        expires_at=now() + timedelta(days=payload.expires_in_days) if payload.expires_in_days else None,
    )
    db.add(invite)
    db.commit()
    # 明文只在这一次响应中返回，之后数据库只保留摘要。
    return InviteIssued(**view(invite).model_dump(), code=code)


@router.get("/invites", response_model=list[InviteView])
def list_invites(admin: CurrentAdmin, db: DB):
    invites = db.scalars(select(InviteCode).order_by(InviteCode.created_at.desc()).limit(200)).all()
    return [view(invite) for invite in invites]


@router.post("/invites/{invite_id}/revoke", response_model=InviteView)
def revoke_invite(invite_id: str, admin: CurrentAdmin, db: DB):
    invite = db.get(InviteCode, invite_id)
    if invite is None:
        raise HTTPException(404, "邀请码不存在。")
    if invite.revoked_at is None:
        invite.revoked_at = now()
        db.commit()
    return view(invite)
