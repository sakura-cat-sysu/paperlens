"""PostgreSQL 保存任务与检查点，RabbitMQ 负责投递，Worker 独立执行。"""

import logging
from collections.abc import MutableMapping
from datetime import timedelta
from uuid import UUID

from celery import Celery
from sqlalchemy import or_, select, text
from sqlalchemy.orm import Session

from backend.database import AnalysisJob, engine, now, session_factory
from backend.schemas import ANALYSIS, DOCUMENT, PLAN, REPORT
from backend.settings import settings
from config import load_settings
from llm_service import AnalysisError
from workflow import run_workflow

logger = logging.getLogger(__name__)
celery = Celery("paperlens", broker=settings().broker_url)
celery.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    control_queue_exclusive=True,
    event_queue_exclusive=True,
    worker_cancel_long_running_tasks_on_connection_loss=True,
    task_ignore_result=True,
    task_publish_retry=False,
    broker_connection_timeout=3,
    broker_connection_retry_on_startup=True,
    broker_transport_options={"confirm_publish": True},
    task_soft_time_limit=1200,
    task_time_limit=1260,
    beat_schedule={"dispatch-pending": {"task": "paperlens.dispatch", "schedule": 15.0}},
)


class PersistentCache(MutableMapping):
    def __init__(self, job, session):
        self.job = job
        self.session = session

    def __getitem__(self, key):
        adapter = PLAN if key.startswith("plan:") else ANALYSIS if key.startswith("document:") else REPORT
        return adapter.validate_python(self.job.checkpoints[key])

    def __setitem__(self, key, value):
        adapter = PLAN if key.startswith("plan:") else ANALYSIS if key.startswith("document:") else REPORT
        self.job.checkpoints = {**self.job.checkpoints, key: adapter.dump_python(value, mode="json")}
        self.session.commit()

    def __delitem__(self, key):
        values = dict(self.job.checkpoints)
        del values[key]
        self.job.checkpoints = values
        self.session.commit()

    def __iter__(self):
        return iter(self.job.checkpoints)

    def __len__(self):
        return len(self.job.checkpoints)


def publish_job(job, session):
    try:
        execute.apply_async(args=[job.id], task_id=job.id)
    except Exception as exc:
        # 数据库中的 queued 任务由定时派发器继续投递。
        logger.warning("Job publication deferred: %s", type(exc).__name__)
        return
    job.dispatched_at = now()
    session.commit()


@celery.task(name="paperlens.dispatch")
def dispatch():
    with session_factory()() as session:
        jobs = session.scalars(
            select(AnalysisJob)
            .where(
                AnalysisJob.status == "queued",
                or_(
                    AnalysisJob.dispatched_at.is_(None),
                    AnalysisJob.dispatched_at < now() - timedelta(minutes=1),
                ),
            )
            .order_by(AnalysisJob.created_at)
            .limit(100)
        )
        for job in jobs:
            publish_job(job, session)


@celery.task(name="paperlens.analyze")
def execute(job_id: str):
    # Broker 可以重复投递；连接级锁防止同一任务同时调用模型，进程退出时锁自动释放。
    lock_id = int.from_bytes(UUID(job_id).bytes[:8], "big", signed=True)
    with engine().connect() as connection:
        locked = connection.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": lock_id})
        connection.commit()
        if not locked:
            return
        try:
            with Session(connection, expire_on_commit=False) as session:
                run_job(session, job_id)
        finally:
            connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": lock_id})
            connection.commit()


def run_job(session, job_id, *, service=None):
    job = session.get(AnalysisJob, job_id)
    if job is None or job.status not in ("queued", "running"):
        return
    job.status = "running"
    job.error = ""
    job.progress = "正在准备文献"
    session.commit()

    def progress(message):
        job.progress = message
        session.commit()

    try:
        documents = tuple(DOCUMENT.validate_python(value) for value in job.input_documents)
        report = run_workflow(
            documents,
            job.question,
            load_settings(),
            cache=PersistentCache(job, session),
            progress=progress,
            service=service,
            retry_incomplete=job.attempts > 1,
        )
        job.report = REPORT.dump_python(report, mode="json")
        job.status = "completed" if report.coverage_complete else "draft"
        job.progress = "逐项回答已生成" if report.coverage_complete else "报告草稿已保存"
    except AnalysisError as exc:
        job.status = "failed"
        job.error = str(exc)
        job.progress = "分析未完成，已保存完成的阶段"
    except Exception as exc:
        session.rollback()
        logger.error("Analysis failed job=%s type=%s", job_id, type(exc).__name__)
        job.status = "failed"
        job.error = "分析暂时无法完成，请重试；若持续失败，请联系管理员。"
        job.progress = "分析未完成"
    session.commit()
