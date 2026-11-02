from io import BytesIO
from pathlib import PurePosixPath
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select

from backend import storage
from backend.auth import CurrentUser, DB
from backend.database import AnalysisJob, StoredDocument, User, identifier, owned
from backend.schemas import DOCUMENT, DocumentDetail, DocumentView
from backend.settings import settings
from config import MAX_FILE_BYTES
from pdf_utils import PDFError, parse_pdf

router = APIRouter(prefix="/documents", tags=["documents"])


def document_view(document: StoredDocument):
    parsed = DOCUMENT.validate_python(document.parsed)
    return DocumentView(
        id=document.id,
        filename=document.filename,
        size_bytes=document.size_bytes,
        page_count=len(parsed.pages),
        text_chars=parsed.text_chars,
        warnings=list(parsed.warnings),
        created_at=document.created_at,
    )


@router.get("", response_model=list[DocumentView])
def list_documents(user: CurrentUser, db: DB):
    documents = db.scalars(
        select(StoredDocument)
        .where(StoredDocument.owner_id == user.id)
        .order_by(StoredDocument.created_at.desc())
    )
    return [document_view(document) for document in documents]


@router.post("", response_model=DocumentView, status_code=201)
def upload_document(file: UploadFile, user: CurrentUser, db: DB):
    content = file.file.read(MAX_FILE_BYTES + 1)
    filename = PurePosixPath((file.filename or "document.pdf").replace("\\", "/")).name[:255]
    try:
        parsed = parse_pdf(content, filename, "D1")
    except PDFError as exc:
        raise HTTPException(422, str(exc)) from None
    db.scalar(select(User).where(User.id == user.id).with_for_update())
    duplicate = db.scalar(
        select(StoredDocument).where(
            StoredDocument.owner_id == user.id, StoredDocument.sha256 == parsed.sha256
        )
    )
    if duplicate:
        return document_view(duplicate)
    count = db.scalar(
        select(func.count()).select_from(StoredDocument).where(StoredDocument.owner_id == user.id)
    )
    if count >= settings().max_documents:
        raise HTTPException(409, "文献库已满，请删除不再需要的文献后重试。")
    document_id = identifier()
    key = f"{user.id}/{document_id}.pdf"
    storage.put(key, content)
    document = StoredDocument(
        id=document_id,
        owner_id=user.id,
        filename=filename,
        size_bytes=len(content),
        sha256=parsed.sha256,
        storage_key=key,
        parsed=DOCUMENT.dump_python(parsed, mode="json"),
    )
    db.add(document)
    try:
        db.commit()
    except Exception:
        db.rollback()
        storage.remove(key)
        raise
    return document_view(document)


@router.get("/{document_id}", response_model=DocumentDetail)
def document_detail(document_id: str, user: CurrentUser, db: DB):
    document = owned(db, StoredDocument, document_id, user.id)
    return DocumentDetail(**document_view(document).model_dump(), pages=document.parsed["pages"])


@router.get("/{document_id}/file")
def download_document(document_id: str, user: CurrentUser, db: DB):
    document = owned(db, StoredDocument, document_id, user.id)
    content = storage.get(document.storage_key)
    return StreamingResponse(
        BytesIO(content),
        media_type="application/pdf",
        headers={
            "Content-Disposition": "attachment; filename=paper.pdf; filename*=UTF-8''"
            + quote(document.filename, safe=""),
            "Cache-Control": "private, no-store",
        },
    )


@router.delete("/{document_id}", status_code=204)
def delete_document(document_id: str, user: CurrentUser, db: DB):
    document = owned(db, StoredDocument, document_id, user.id)
    db.scalar(select(User).where(User.id == user.id).with_for_update())
    active = db.scalars(
        select(AnalysisJob).where(
            AnalysisJob.owner_id == user.id, AnalysisJob.status.in_(("queued", "running"))
        )
    )
    if any(document_id in job.document_ids for job in active):
        raise HTTPException(409, "此文献正在分析，任务结束后才能删除。")
    storage.remove(document.storage_key)
    db.delete(document)
    db.commit()
