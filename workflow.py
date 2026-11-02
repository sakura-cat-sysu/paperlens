"""按固定步骤执行，不因页面重绘而发出请求；失败重试可复用已完成阶段。"""

import hashlib
import json
from collections.abc import Callable, MutableMapping
from contextlib import nullcontext
from dataclasses import replace
from datetime import datetime, timezone

from config import MAX_FILES, MAX_QUESTION_CHARS, MIN_FILES, Settings
from llm_service import AnalysisError, LLMService
from models import Document, Report
from validators import build_comparison, verified_claims


def input_signature(documents: tuple[Document, ...], question: str, settings: Settings) -> str:
    payload = {
        "documents": [(d.document_id, d.filename, d.sha256) for d in documents],
        "question": question.strip(), "model": settings.model, "base_url": settings.base_url,
        "credential_fingerprint": hashlib.sha256(settings.api_key.encode()).hexdigest(),
        "prompt_version": 3,
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def run_workflow(
    documents: tuple[Document, ...], question: str, settings: Settings, *,
    cache: MutableMapping | None = None, progress: Callable[[str], None] | None = None,
    service: LLMService | None = None, retry_incomplete: bool = False,
) -> Report:
    question = question.strip()
    if not question:
        raise AnalysisError("请输入研究问题后再开始分析。")
    if len(question) > MAX_QUESTION_CHARS:
        raise AnalysisError("研究问题请控制在 2,000 字符以内。")
    if not MIN_FILES <= len(documents) <= MAX_FILES:
        raise AnalysisError("请上传 2～3 篇有效的 PDF 文献。")
    if len({d.sha256 for d in documents}) != len(documents):
        raise AnalysisError("上传的文献中存在相同文件，请选择不同文献进行比较。")
    if len({d.document_id for d in documents}) != len(documents):
        raise AnalysisError("文献编号重复，请重新上传文件。")
    if settings.missing:
        raise AnalysisError("尚未配置 " + "、".join(settings.missing) + "。请填写项目的 .env 后重试。")

    cache = cache if cache is not None else {}
    emit = progress or (lambda _: None)
    signature = input_signature(documents, question, settings)
    if isinstance(cache.get(signature), Report):
        if not retry_incomplete or cache[signature].coverage_complete:
            emit("已恢复当前报告，未重复调用模型。")
            return cache[signature]
        del cache[signature]

    context = nullcontext(service) if service is not None else LLMService(settings)
    with context as llm:
        emit("正在拆解研究问题，建立逐项回答清单。")
        plan_key = "plan:" + signature
        if plan_key not in cache:
            cache[plan_key] = llm.plan_question(question)
        tasks = cache[plan_key]
        for task in tasks:
            emit(f"{task.task_id} · {task.title}")
        analyses = []
        for index, document in enumerate(documents, start=1):
            emit(f"正在提取核心观点（{index}/{len(documents)}）：{document.filename}")
            key = "document:" + input_signature((document,), question, settings)
            if key not in cache:
                cache[key] = llm.analyze_document(document, question, tasks)
            analyses.append(cache[key])
            emit(f"已完成 {document.document_id}，并校验对应页原文。")

        analyses = tuple(analyses)
        supported_documents = {claim.document_id for claim in verified_claims(analyses).values()}
        emit("正在逐项回答并比较文献：排除含有任何未匹配引文的观点。")
        if len(supported_documents) < MIN_FILES:
            comparison = build_comparison({"summary": None, "unresolved_questions": []}, analyses, tasks)
            comparison = replace(comparison, warnings=(
                "少于两篇文献提供了带有已匹配原文的观点，未调用综合比较。请查看证据不足提示，或调整问题。",
            ))
        else:
            comparison = llm.compare(analyses, question, tasks)
            excluded = [a.document_id for a in analyses if not any(c.supported for c in a.claims)]
            if excluded:
                comparison = replace(comparison, warnings=comparison.warnings + (
                    "以下文献没有可用观点，未参与综合分析：" + "、".join(excluded) + "。",
                ))
        emit("正在生成结果：整理观点、来源与尚待研究的问题。")
        report = Report(question, documents, analyses, comparison, settings.model,
                        datetime.now(timezone.utc).isoformat(timespec="seconds"), tasks)
        cache[signature] = report
        return report
