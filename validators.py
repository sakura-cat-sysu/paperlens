"""严格检查 JSON 结构、页内原文匹配与跨文献观点引用。"""

import json
import re
from typing import Any

from models import (
    Claim, Comparison, Document, DocumentAnalysis, Evidence, Finding,
    QuestionAnswer, QuestionTask,
)

BASES = ("reported", "inference", "proposal")
TASK_KINDS = ("evidence", "synthesis", "proposal", "experiment")


class OutputError(ValueError):
    """模型格式错误；允许上层进行一次有限修复。"""


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise OutputError("JSON 包含重复字段。")
        result[key] = value
    return result


def _invalid_constant(value):
    raise OutputError("JSON 不允许 NaN 或 Infinity。")


def parse_json_object(raw: str) -> dict[str, Any]:
    if not isinstance(raw, str) or len(raw) > 100_000:
        raise OutputError("模型输出为空或过长。")
    text = raw.strip().lstrip("\ufeff")
    fenced = re.fullmatch(r"```(?:json)?\s*\n?(.*?)\n?```", text, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        text = fenced.group(1).strip()
    try:
        data = json.loads(text, object_pairs_hook=_unique_object, parse_constant=_invalid_constant)
    except (json.JSONDecodeError, RecursionError):
        raise OutputError("模型未返回合法 JSON。") from None
    if not isinstance(data, dict):
        raise OutputError("JSON 顶层必须是对象。")
    return data


def _text(value, field: str, *, empty: bool = False, max_length: int = 4_000) -> str:
    if not isinstance(value, str) or (not empty and not value.strip()) or len(value) > max_length:
        raise OutputError(f"{field} 必须是长度合理的{'可为空' if empty else '非空'}字符串。")
    return value.strip()


def _array(value, field: str, limit: int = 12) -> list:
    if not isinstance(value, list) or len(value) > limit:
        raise OutputError(f"{field} 必须是数组，且最多 {limit} 项。")
    return value


def _object(value, field: str) -> dict:
    if not isinstance(value, dict):
        raise OutputError(f"{field} 必须是对象。")
    return value


def validate_document_schema(data: dict) -> dict:
    for item in _array(data.get("claims"), "claims", 6):
        item = _object(item, "claim")
        _text(item.get("claim"), "claim", max_length=2_000)
        _text(item.get("explanation"), "explanation", empty=True)
        for evidence in _array(item.get("evidence"), "evidence", 3):
            evidence = _object(evidence, "evidence")
            if type(evidence.get("page")) is not int:
                raise OutputError("evidence.page 必须是整数物理页码。")
            _text(evidence.get("quote"), "quote", max_length=3_000)
    for gap in _array(data.get("gaps"), "gaps"):
        _text(gap, "gap")
    return data


def normalize_whitespace(text: str) -> str:
    # 只忽略空白；不删除标点，不更改大小写，也不做模糊匹配。
    return re.sub(r"\s+", "", text)


def verify_evidence(raw: dict, document: Document) -> Evidence:
    page = raw["page"]
    quote = raw["quote"].strip()
    reason = ""
    if raw.get("document_id", document.document_id) != document.document_id:
        reason = "引用指向了其他文献。"
    elif not 1 <= page <= len(document.pages):
        reason = "页码不在该 PDF 的物理页范围内。"
    elif len(normalize_whitespace(quote)) < 8:
        reason = "原文片段过短，无法作为可靠的匹配依据（至少 8 个非空白字符）。"
    elif normalize_whitespace(quote) not in normalize_whitespace(document.pages[page - 1].text):
        reason = "在指定页未找到对应原文；仅允许忽略空白和换行。"
    return Evidence(document.document_id, page, quote, not reason, reason)


def build_document_analysis(data: dict, document: Document) -> DocumentAnalysis:
    validate_document_schema(data)
    claims = tuple(
        Claim(
            claim_id=f"{document.document_id}-C{index}", document_id=document.document_id,
            claim=item["claim"].strip(), explanation=item["explanation"].strip(),
            evidence=tuple(verify_evidence(e, document) for e in item["evidence"]),
        )
        for index, item in enumerate(data["claims"], start=1)
    )
    warnings = []
    if not claims:
        warnings.append("模型未识别到与问题相关的有效观点。")
    for claim in claims:
        if claim.pending_review:
            warnings.append(f"{claim.claim_id} 存在未匹配引用，整条观点待复核，已排除出综合分析。")
        elif not claim.supported:
            warnings.append(f"{claim.claim_id} 证据不足，已排除出综合比较。")
    return DocumentAnalysis(document.document_id, document.filename, claims,
                            tuple(s.strip() for s in data["gaps"]), tuple(warnings))


def verified_claims(analyses: tuple[DocumentAnalysis, ...]) -> dict[str, Claim]:
    return {c.claim_id: c for analysis in analyses for c in analysis.claims if c.supported}


def comparison_payload(analyses: tuple[DocumentAnalysis, ...]) -> list[dict]:
    """仅把带有已匹配原文的观点和已匹配证据传给第二次分析。"""
    result = []
    for analysis in analyses:
        claims = [
            {
                "claim_id": c.claim_id, "document_id": c.document_id, "claim": c.claim,
                "explanation": c.explanation,
                "evidence": [{"document_id": e.document_id, "page": e.page, "quote": e.quote}
                             for e in c.evidence if e.verified],
            }
            for c in analysis.claims if c.supported
        ]
        if claims:
            result.append({"document_id": analysis.document_id, "filename": analysis.filename,
                           "claims": claims})
    return result


def validate_question_plan(data: dict) -> dict:
    tasks = _array(data.get("tasks"), "tasks", 8)
    if not tasks:
        raise OutputError("问题拆解至少需要一项任务。")
    for task in tasks:
        task = _object(task, "task")
        _text(task.get("title"), "task.title", max_length=300)
        if task.get("kind") not in TASK_KINDS:
            raise OutputError("task.kind 必须是 evidence、synthesis、proposal 或 experiment。")
    return data


def build_question_plan(data: dict, question: str) -> tuple[QuestionTask, ...]:
    validate_question_plan(data)
    items, seen = [], set()
    for raw in data["tasks"]:
        title = raw["title"].strip()
        kind = raw["kind"]
        if kind == "experiment" and not re.search(r"设计|方案|消融|基线|验证|检验|design|protocol|ablat|baseline", title, re.IGNORECASE):
            # 说明既有实验的时间/结果，不应被强制要求再设计一套新实验。
            kind = "evidence"
        if title.casefold() not in seen:
            items.append((title, kind))
            seen.add(title.casefold())
    def is_format_task(title):
        return bool(re.search(r"区分|标注|标明|分层|distinguish|label", title, re.IGNORECASE)
                    and re.search(r"文献报告|推导|待验证|来源类型|引文|引用|出处|事实.*假设", title))
    # 分层与引用属于全部回答的约束，不在复合问题中重复占一个研究任务。
    if any(not is_format_task(title) for title, _ in items):
        items = [(title, kind) for title, kind in items if not is_format_task(title)]
    # 对明确点名的关键交付项作保底检查，避免拆解步骤漏掉用户要求。
    requirements = (
        (r"(?:设计|提出|给出|制定|design|propos\w*|devise)[^。？！?\n]{0,120}(?:消融|ablat)",
         r"消融|ablat", "消融实验设计", "experiment"),
        (r"(?:设计|提出|给出|制定|design|propos\w*|devise)[^。？！?\n]{0,120}(?:基线|baseline)",
         r"基线|baseline", "公平基线及比较条件", "experiment"),
        (r"(?:设计|提出|给出|制定|构建|propose|design|devise)[^。？！?\n]{0,120}(?:决策策略|动态.{0,8}策略|融合.{0,8}策略|decision.{0,12}(policy|strateg)|routing.{0,8}policy)",
         r"策略|policy|strateg", "动态决策策略与具体规则", "proposal"),
        (r"适得其反|失效|什么条件|何种条件|failure|under what conditions",
         r"适得其反|失效|收益|风险|failure|risk|benefit", "收益条件、失效条件与风险", "synthesis"),
    )
    for request_pattern, title_pattern, title, kind in requirements:
        requested = any(not re.search(
            r"(?:不要|不需要|不必|无需|不用|无须|do not|don't|no need to)\s*(?:再|额外|专门)?\s*$",
            question[max(0, match.start() - 20):match.start()], re.IGNORECASE,
        ) for match in re.finditer(request_pattern, question, re.IGNORECASE))
        if requested and not any(
            re.search(title_pattern, existing, re.IGNORECASE) for existing, _ in items
        ):
            items.append((title, kind))
    return tuple(QuestionTask(f"Q{i}", title, kind) for i, (title, kind) in enumerate(items, 1))


def validate_comparison_schema(data: dict) -> dict:
    def check_finding(item):
        item = _object(item, "finding")
        _text(item.get("text"), "text")
        for claim_id in _array(item.get("claim_ids"), "claim_ids", 18):
            _text(claim_id, "claim_id", max_length=40)
        if item.get("basis") not in BASES:
            raise OutputError("basis 必须为 reported（论文报告）、inference（推导）或 proposal（待验证方案）。")

    if data.get("summary") is not None:
        check_finding(data["summary"])
    for key in ("agreements", "disagreements", "method_differences", "reasons"):
        for item in _array(data.get(key, []), key):
            check_finding(item)
            if key == "disagreements" and item.get("relation") not in ("contradiction", "method_difference"):
                raise OutputError("分歧的 relation 必须为 contradiction 或 method_difference。")
    seen = set()
    for answer in _array(data.get("answers", []), "answers"):
        answer = _object(answer, "answer")
        task_id = _text(answer.get("task_id"), "answer.task_id", max_length=40)
        if task_id in seen:
            raise OutputError("同一问题任务不能重复回答。")
        seen.add(task_id)
        if answer.get("status") not in ("answered", "partial", "unanswered"):
            raise OutputError("answer.status 必须为 answered、partial 或 unanswered。")
        for missing in _array(answer.get("missing_requirements"), "answer.missing_requirements", 8):
            _text(missing, "missing_requirement")
        _text(answer.get("caveats", ""), "answer.caveats", empty=True)
        for statement in _array(answer.get("statements"), "answer.statements", 4):
            check_finding(statement)
    for item in _array(data.get("unresolved_questions"), "unresolved_questions"):
        _text(item, "unresolved_question")
    return data


def build_comparison(
    data: dict, analyses: tuple[DocumentAnalysis, ...], tasks: tuple[QuestionTask, ...] = (),
) -> Comparison:
    validate_comparison_schema(data)
    allowed = verified_claims(analyses)
    warnings = []

    def convert(raw, label, *, cross_document=False, reported_only=False):
        if raw is None:
            return None
        ids = tuple(dict.fromkeys(raw["claim_ids"]))
        # 任何一个 ID 无效都丢弃整条结论，不能丢掉坏 ID 后伪装成有出处。
        if not ids or any(key not in allowed for key in ids):
            warnings.append(f"{label}的一条内容无有效观点来源，已隐藏。")
            return None
        if cross_document and len({allowed[key].document_id for key in ids}) < 2:
            warnings.append(f"{label}的一条内容未关联至少两篇文献，已隐藏。")
            return None
        if reported_only and raw["basis"] != "reported":
            warnings.append(f"{label}的一条内容属于推导或方案，不能作为论文已有结论，已隐藏。")
            return None
        return Finding(raw["text"].strip(), ids, raw["basis"])

    def collect(key, label, **kwargs):
        items = (convert(raw, label, **kwargs) for raw in data.get(key, []))
        return tuple(item for item in items if item is not None)

    method_raw = list(data.get("method_differences", []))
    conflict_raw = []
    for raw in data.get("disagreements", []):
        if raw["relation"] == "method_difference":
            method_raw.append(raw)
            warnings.append("一条方法差异已移至“机制差异与互补性”，未作为结论冲突。")
        else:
            conflict_raw.append(raw)

    raw_answers = {a["task_id"]: a for a in data.get("answers", [])}
    task_ids = {task.task_id for task in tasks}
    if tasks and any(key not in task_ids for key in raw_answers):
        warnings.append("模型返回了不在问题清单内的回答，已忽略。")
    answers = []
    for task in tasks:
        raw = raw_answers.get(task.task_id)
        if raw is None:
            answers.append(QuestionAnswer(task.task_id, (), "unanswered", "模型未回答本项要求。"))
            continue
        converted = [convert(item, task.title) for item in raw["statements"]]
        statements = tuple(item for item in converted if item is not None)
        status = raw["status"]
        limitations = "；".join(item.strip() for item in raw["missing_requirements"])
        caveats = raw.get("caveats", "").strip()
        if not statements:
            status = "unanswered"
            limitations = limitations or "本项没有带有效出处的实质回答。"
        elif len(statements) != len(converted):
            status = "partial"
            limitations = "部分判断因来源无效被隐藏。" + limitations
        elif task.kind in ("proposal", "experiment") and not any(s.basis == "proposal" for s in statements):
            status = "partial"
            limitations = "本项要求具体方案或实验设计，但未给出标为待验证的方案。" + limitations
        elif limitations and status == "answered":
            status = "partial"
        if status == "partial" and not limitations:
            limitations = "模型标记本项仅部分回答，需人工复核是否有遗漏。"
        answers.append(QuestionAnswer(task.task_id, statements, status, limitations, caveats))

    def convert_many(items, label):
        result = (convert(raw, label, cross_document=True, reported_only=True) for raw in items)
        return tuple(item for item in result if item is not None)

    summary = convert(data.get("summary"), "综合结论")
    agreements = collect("agreements", "共识", cross_document=True, reported_only=True)
    disagreements = convert_many(conflict_raw, "结论冲突")
    reasons = collect("reasons", "差异原因", cross_document=True)
    method_differences = convert_many(method_raw, "机制差异")
    return Comparison(
        summary=summary, agreements=agreements, disagreements=disagreements, reasons=reasons,
        unresolved_questions=tuple(q.strip() for q in data["unresolved_questions"]),
        warnings=tuple(warnings),
        method_differences=method_differences,
        answers=tuple(answers),
    )
