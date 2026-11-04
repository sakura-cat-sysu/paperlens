"""部署配置。模型配置继续由 config.py 在服务端读取。"""

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv


@lru_cache
def settings():
    load_dotenv(override=False)
    return AppSettings()


class AppSettings:
    def __init__(self):
        self.database_url = os.getenv(
            "DATABASE_URL", "postgresql+psycopg://paperlens:paperlens@localhost:5432/paperlens"
        )
        self.broker_url = os.getenv("CELERY_BROKER_URL", "amqp://guest:guest@localhost:5672//")
        self.origin = os.getenv("APP_ORIGIN", "http://127.0.0.1:5188").rstrip("/")
        self.secure_cookies = self.origin.startswith("https://")
        self.allow_registration = os.getenv("ALLOW_REGISTRATION", "false").lower() == "true"
        self.allow_guests = os.getenv("ALLOW_GUESTS", "true").lower() == "true"
        self.daily_analyses = int(os.getenv("DAILY_ANALYSES", "20"))
        self.guest_daily_analyses = int(os.getenv("GUEST_DAILY_ANALYSES", "10"))
        self.guest_max_documents = int(os.getenv("GUEST_MAX_DOCUMENTS", "10"))
        self.guest_entries_per_window = int(os.getenv("GUEST_ENTRIES_PER_WINDOW", "30"))
        self.max_active_jobs = int(os.getenv("MAX_ACTIVE_JOBS", "2"))
        self.max_documents = int(os.getenv("MAX_DOCUMENTS", "100"))
        self.storage_backend = os.getenv("STORAGE_BACKEND", "local")
        self.storage_root = Path(os.getenv("STORAGE_ROOT", ".data/documents")).resolve()
        self.s3_bucket = os.getenv("S3_BUCKET", "")
        self.s3_endpoint = os.getenv("S3_ENDPOINT_URL") or None
        self.s3_region = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
        self.release = os.getenv("RELEASE_SHA", "development")
        if self.storage_backend not in ("local", "s3"):
            raise ValueError("STORAGE_BACKEND must be local or s3")
        if self.storage_backend == "s3" and not self.s3_bucket:
            raise ValueError("S3_BUCKET is required for S3 storage")
        if min(
            self.daily_analyses, self.max_active_jobs, self.max_documents,
            self.guest_daily_analyses, self.guest_max_documents, self.guest_entries_per_window,
        ) < 1:
            raise ValueError("Usage limits must be positive")


def analysis_limit(user):
    config = settings()
    return config.guest_daily_analyses if user.is_guest else config.daily_analyses


def document_limit(user):
    config = settings()
    return min(config.guest_max_documents, config.max_documents) if user.is_guest else config.max_documents
