import asyncio
import json
from dataclasses import replace

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy.orm import load_only
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select

from backend.auth import CurrentUser, DB
from backend.database import AnalysisJob, StoredDocument, UsageDay, User, now, owned, session_factory
from backend.schemas import DOCUMENT, REPORT, JobCreate, JobDetail, JobView, UsageView
from backend.settings import settings
from config import load_settings

router = APIRouter(tags=["analyses"])


def usage_view(db, user_id):
    usage = db.get(UsageDay, (user_id, now().date()))
    used = usage.used if usage else 0
    limit = settings().daily_analyses
    return UsageView(used=used, limit=limit, remaining=max(0, limit - used))


def reserve_analysis(db, user):
    db.scalar(select(User).where(User.id == user.id).with_for_update())
    active = db.scalar(
        select(func.count())
        .select_from(AnalysisJob)
        .where(AnalysisJob.owner_id == user.id, AnalysisJob.status.in_(("queued", "running")))
    )
    if active >= settings().max_active_jobs:
        raise HTTPException(409, "已有任务正在进行，请等待完成后再开始。")
    if load_settings().missing:
        raise HTTPException(503, "模型服务尚未配置，请联系管理员。")
    day = now().date()
    usage = db.get(UsageDay, (user.id, day))
    if usage is None:
        usage = UsageDay(owner_id=user.id, day=day, used=0)
        db.add(usage)
    if usage.used >= settings().daily_analyses:
        raise HTTPException(429, "今日分析次数已用完，额度将在 UTC 零点重置。")
    usage.used += 1


def retry_block_reason(job, report):
    if job.status not in ("failed", "draft"):
        return "此任务当前不需要重试。"
    if job.status == "draft":
        eligible = (
            sum(any(claim.supported for claim in analysis.claims) for analysis in report.analyses)
            if report else 0
        )
        if eligible < 2:
            return "可用证据不足，请调整文献或问题后创建新分析。"
    return ""


def job_detail(job):
    report = REPORT.validate_python(job.report) if job.report else None
    retry_reason = retry_block_reason(job, report)
    return JobDetail(
        **JobView.model_validate(job).model_dump(),
        report=report,
        coverage_complete=report.coverage_complete if report else False,
        can_retry=not retry_reason,
        retry_reason=retry_reason,
    )


@router.get("/usage", response_model=UsageView)
def usage(user: CurrentUser, db: DB):
    return usage_view(db, user.id)


@router.get("/analyses", response_model=list[JobView])
def list_jobs(user: CurrentUser, db: DB, offset: int = Query(default=0, ge=0)):
    fields = [getattr(AnalysisJob, name) for name in JobView.model_fields]
    return db.scalars(
        select(AnalysisJob)
        .options(load_only(*fields))
        .where(AnalysisJob.owner_id == user.id)
        .order_by(AnalysisJob.created_at.desc(), AnalysisJob.id)
        .offset(offset)
        .limit(100)
    ).all()


@router.post("/analyses", response_model=JobView, status_code=202)
def create_job(payload: JobCreate, user: CurrentUser, db: DB):
    from backend.worker import publish_job

    db.scalar(select(User).where(User.id == user.id).with_for_update())
    duplicate = db.scalar(
        select(AnalysisJob).where(
            AnalysisJob.owner_id == user.id, AnalysisJob.submission_id == str(payload.submission_id)
        )
    )
    if duplicate:
        return duplicate
    ids = [str(value) for value in payload.document_ids]
    documents = [owned(db, StoredDocument, value, user.id) for value in ids]
    reserve_analysis(db, user)
    inputs = [
        DOCUMENT.dump_python(
            replace(DOCUMENT.validate_python(document.parsed), document_id=f"D{index}"), mode="json"
        )
        for index, document in enumerate(documents, 1)
    ]
    job = AnalysisJob(
        owner_id=user.id,
        submission_id=str(payload.submission_id),
        question=payload.question,
        document_ids=ids,
        input_documents=inputs,
    )
    db.add(job)
    db.commit()
    publish_job(job, db)
    return job


@router.get("/analyses/{job_id}", response_model=JobDetail)
def get_job(job_id: str, user: CurrentUser, db: DB):
    return job_detail(owned(db, AnalysisJob, job_id, user.id))


@router.post("/analyses/{job_id}/retry", response_model=JobView, status_code=202)
def retry_job(job_id: str, user: CurrentUser, db: DB):
    from backend.worker import publish_job

    db.scalar(select(User).where(User.id == user.id).with_for_update())
    job = owned(db, AnalysisJob, job_id, user.id)
    report = REPORT.validate_python(job.report) if job.status == "draft" and job.report else None
    retry_reason = retry_block_reason(job, report)
    if retry_reason:
        raise HTTPException(409, retry_reason)
    reserve_analysis(db, user)
    job.status = "queued"
    job.error = ""
    job.progress = "等待重试，已完成阶段会保留"
    job.dispatched_at = None
    job.attempts += 1
    db.commit()
    publish_job(job, db)
    return job


@router.delete("/analyses/{job_id}", status_code=204)
def delete_job(job_id: str, user: CurrentUser, db: DB):
    job = owned(db, AnalysisJob, job_id, user.id)
    if job.status in ("queued", "running"):
        raise HTTPException(409, "请等待任务结束后再删除。")
    db.delete(job)
    db.commit()


@router.get("/analyses/{job_id}/events")
def job_events(job_id: str, request: Request, user: CurrentUser, db: DB):
    owned(db, AnalysisJob, job_id, user.id)
    user_id = user.id
    db.close()

    async def events():
        previous = ""
        while not await request.is_disconnected():

            def snapshot():
                with session_factory()() as session:
                    job = owned(session, AnalysisJob, job_id, user_id)
                    return JobView.model_validate(job).model_dump_json()

            value = await asyncio.to_thread(snapshot)
            if value != previous:
                yield "data: " + value + "\n\n"
                previous = value
            else:
                yield ": heartbeat\n\n"
            if json.loads(value)["status"] not in ("queued", "running"):
                break
            await asyncio.sleep(2)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )
