import logging
from typing import Annotated

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import select, text

from backend import account, admin, auth, documents, jobs, samples
from backend.account import has_any_config
from backend.auth import COOKIE, DB, digest
from backend.database import LoginSession, User, now
from backend.schemas import Capabilities
from backend.settings import settings
from config import MAX_FILE_BYTES, MAX_PAGES, MAX_QUESTION_CHARS, MAX_TEXT_CHARS, load_settings

app = FastAPI(title="PaperLens API", version="1.0.0", docs_url=None, redoc_url=None)
logger = logging.getLogger(__name__)


def optional_user(request: Request, db: DB) -> User | None:
    """未登录时返回 None，供公开接口判断「当前访问者」的模型配置。"""
    token = request.cookies.get(COOKIE, "")
    session = db.get(LoginSession, digest(token)) if token else None
    if session is None or session.expires_at <= now():
        return None
    return db.get(User, session.user_id)


OptionalUser = Annotated[User | None, Depends(optional_user)]


@app.middleware("http")
async def boundaries(request: Request, call_next):
    origin = request.headers.get("origin")
    if request.method not in ("GET", "HEAD", "OPTIONS") and origin and origin != settings().origin:
        return JSONResponse({"detail": "请求来源不受信任。"}, status_code=403)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    errors = exc.errors()
    # 不把密码、研究问题或上传内容随验证错误返回。
    message = "提交内容不符合要求，请检查邮箱、密码、文献数量或问题长度。"
    if errors and errors[0].get("ctx", {}).get("error"):
        message = str(errors[0]["ctx"]["error"])
    return JSONResponse({"detail": message}, status_code=422)


@app.exception_handler(Exception)
async def unexpected_error(request: Request, exc: Exception):
    logger.error("API failed method=%s type=%s", request.method, type(exc).__name__)
    return JSONResponse({"detail": "服务暂时不可用，请稍后重试。"}, status_code=503)


@app.get("/api/health/live", tags=["health"])
def live():
    return {"status": "ok", "release": settings().release}


@app.get("/api/health/ready", tags=["health"])
def ready(db: DB):
    db.execute(text("SELECT 1"))
    db.execute(select(User.id).limit(1))
    return {"status": "ready", "release": settings().release}


@app.get("/api/capabilities", response_model=Capabilities, tags=["configuration"])
def capabilities(db: DB, user: OptionalUser):
    config = settings()
    # 已登录时按该账号实际可用的配置判断；未登录只能看服务器 .env。
    model_configured = (
        has_any_config(db, user.id) if user is not None else not load_settings().missing
    )
    return Capabilities(
        allow_registration=config.allow_registration,
        invite_required=True,
        model_configured=model_configured,
        max_file_bytes=MAX_FILE_BYTES,
        max_pages=MAX_PAGES,
        max_text_chars=MAX_TEXT_CHARS,
        max_question_chars=MAX_QUESTION_CHARS,
        daily_analyses=config.daily_analyses,
        max_documents=config.max_documents,
    )


app.include_router(auth.router, prefix="/api")
app.include_router(account.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(documents.router, prefix="/api")
app.include_router(samples.router, prefix="/api")
app.include_router(jobs.router, prefix="/api")
