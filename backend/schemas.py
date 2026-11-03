import re
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator

from models import Document, DocumentAnalysis, PDFPage, QuestionTask, Report

DOCUMENT = TypeAdapter(Document)
REPORT = TypeAdapter(Report)
ANALYSIS = TypeAdapter(DocumentAnalysis)
PLAN = TypeAdapter(tuple[QuestionTask, ...])


class Credentials(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(min_length=12, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value):
        value = value.strip().lower()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("请输入有效的邮箱地址。")
        return value


class RegistrationRequest(Credentials):
    invite_code: str = Field(min_length=1, max_length=64)

    @field_validator("invite_code")
    @classmethod
    def normalize_invite_code(cls, value):
        value = value.strip().replace("-", "").replace(" ", "").upper()
        if not value:
            raise ValueError("请输入邀请码。")
        return value


class InviteCreate(BaseModel):
    note: str = Field(default="", max_length=200)
    max_uses: int = Field(default=1, ge=1, le=100)
    expires_in_days: int | None = Field(default=14, ge=1, le=365)
    grants_admin: bool = False

    @field_validator("note")
    @classmethod
    def clean_note(cls, value):
        return value.strip()


class InviteView(BaseModel):
    id: str
    code_hint: str
    note: str
    grants_admin: bool
    max_uses: int
    used_count: int
    state: str
    expires_at: datetime | None
    created_at: datetime


class InviteIssued(InviteView):
    """签发结果。code 为明文，只在这一次响应中出现。"""

    code: str


class UserView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    email: str
    is_admin: bool


class AuthView(BaseModel):
    user: UserView
    csrf_token: str


class DocumentView(BaseModel):
    id: str
    filename: str
    size_bytes: int
    page_count: int
    text_chars: int
    warnings: list[str]
    created_at: datetime


class DocumentDetail(DocumentView):
    pages: list[PDFPage]


class SamplePaperView(BaseModel):
    id: str
    title: str
    authors: str
    year: int
    language: str
    filename: str
    page_count: int
    source_url: str
    license: str
    license_url: str


class SampleCollectionView(BaseModel):
    id: str
    title: str
    description: str
    question: str
    papers: list[SamplePaperView]


class SampleImportResult(BaseModel):
    document_ids: list[str]
    question: str
    imported_count: int
    existing_count: int


class JobCreate(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    document_ids: list[UUID] = Field(min_length=2, max_length=3)
    submission_id: UUID

    @field_validator("question")
    @classmethod
    def clean_question(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("请输入研究问题。")
        return value

    @field_validator("document_ids")
    @classmethod
    def distinct_documents(cls, value):
        if len(set(value)) != len(value):
            raise ValueError("请选择不同的文献。")
        return value


class JobView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    question: str
    document_ids: list[str]
    status: str
    progress: str
    error: str
    attempts: int
    created_at: datetime
    updated_at: datetime


class JobDetail(JobView):
    report: Report | None
    coverage_complete: bool
    can_retry: bool
    retry_reason: str


class Capabilities(BaseModel):
    allow_registration: bool
    invite_required: bool
    model_configured: bool
    max_file_bytes: int
    max_pages: int
    max_text_chars: int
    max_question_chars: int
    daily_analyses: int
    max_documents: int


class UsageView(BaseModel):
    used: int
    limit: int
    remaining: int
