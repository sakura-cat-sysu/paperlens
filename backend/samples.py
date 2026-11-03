"""开放授权示例：从随版本发布的固定文件导入，不在线抓取用户提供的 URL。"""

import hashlib
import json
import logging
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select

from backend import storage
from backend.auth import CurrentUser, DB
from backend.database import StoredDocument, User, identifier
from backend.schemas import DOCUMENT, SampleCollectionView, SampleImportResult, SamplePaperView
from backend.settings import settings
from pdf_utils import parse_pdf

router = APIRouter(prefix="/samples", tags=["samples"])
ASSETS = Path(__file__).with_name("sample_assets")
logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def catalog():
    return json.loads((ASSETS / "catalog.json").read_text(encoding="utf-8"))


def collection_view(collection):
    papers = {paper["id"]: paper for paper in catalog()["papers"]}
    return SampleCollectionView(
        **{key: collection[key] for key in ("id", "title", "description", "question")},
        papers=[SamplePaperView.model_validate(papers[paper_id]) for paper_id in collection["paper_ids"]],
    )


def read_paper(paper):
    path = ASSETS / paper["asset"]
    if path.resolve().parent != ASSETS.resolve():
        raise ValueError("Invalid sample path")
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != paper["sha256"]:
        raise ValueError("Sample checksum mismatch")
    parsed = parse_pdf(content, paper["filename"], "D1")
    return content, parsed


@router.get("", response_model=list[SampleCollectionView])
def list_samples(user: CurrentUser):
    return [collection_view(collection) for collection in catalog()["collections"]]


@router.post("/{collection_id}/import", response_model=SampleImportResult)
def import_samples(collection_id: str, user: CurrentUser, db: DB):
    collection = next((item for item in catalog()["collections"] if item["id"] == collection_id), None)
    if collection is None:
        raise HTTPException(404, "未找到这组示例文献。")
    papers = {paper["id"]: paper for paper in catalog()["papers"]}
    try:
        sources = [read_paper(papers[paper_id]) for paper_id in collection["paper_ids"]]
    except (OSError, ValueError) as exc:
        logger.error("Sample unavailable type=%s", type(exc).__name__)
        raise HTTPException(503, "示例文献暂时无法读取，请稍后重试。") from None

    # 与普通上传使用同一用户行锁；并发导入不会绕过容量和去重约束。
    db.scalar(select(User).where(User.id == user.id).with_for_update())
    hashes = [parsed.sha256 for _, parsed in sources]
    existing = db.scalars(
        select(StoredDocument).where(
            StoredDocument.owner_id == user.id, StoredDocument.sha256.in_(hashes)
        )
    ).all()
    by_hash = {document.sha256: document for document in existing}
    pending = [(content, parsed) for content, parsed in sources if parsed.sha256 not in by_hash]
    count = db.scalar(
        select(func.count()).select_from(StoredDocument).where(StoredDocument.owner_id == user.id)
    )
    if count + len(pending) > settings().max_documents:
        raise HTTPException(409, "文献库剩余空间不足，请至少腾出这组示例所需的位置后重试。")

    written = []
    try:
        for content, parsed in pending:
            document_id = identifier()
            key = f"{user.id}/{document_id}.pdf"
            # 写入异常时也尝试清理当前键，避免留下部分上传的对象。
            written.append(key)
            storage.put(key, content)
            document = StoredDocument(
                id=document_id,
                owner_id=user.id,
                filename=parsed.filename,
                size_bytes=len(content),
                sha256=parsed.sha256,
                storage_key=key,
                parsed=DOCUMENT.dump_python(parsed, mode="json"),
            )
            db.add(document)
            by_hash[parsed.sha256] = document
        db.commit()
    except Exception:
        db.rollback()
        for key in written:
            try:
                storage.remove(key)
            except Exception as exc:
                logger.error("Sample cleanup failed type=%s", type(exc).__name__)
        raise
    return SampleImportResult(
        document_ids=[by_hash[sha].id for sha in hashes],
        question=collection["question"],
        imported_count=len(pending),
        existing_count=len(sources) - len(pending),
    )
