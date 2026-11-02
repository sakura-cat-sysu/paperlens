"""各阶段共享的数据结构；页码一律使用从 1 开始的 PDF 物理页码。"""

from dataclasses import dataclass


@dataclass(frozen=True)
class PDFPage:
    number: int
    text: str
    paragraphs: tuple[str, ...]


@dataclass(frozen=True)
class Document:
    document_id: str
    filename: str
    size_bytes: int
    pages: tuple[PDFPage, ...]
    sha256: str
    warnings: tuple[str, ...] = ()

    @property
    def text_chars(self) -> int:
        return sum(len(page.text) for page in self.pages)


@dataclass(frozen=True)
class Evidence:
    document_id: str
    page: int
    quote: str
    verified: bool
    reason: str = ""


@dataclass(frozen=True)
class Claim:
    claim_id: str
    document_id: str
    claim: str
    explanation: str
    evidence: tuple[Evidence, ...]

    @property
    def supported(self) -> bool:
        # 有一条失败引文就冻结整条观点，不能只删引文却保留其支持的细节。
        return bool(self.evidence) and all(e.verified for e in self.evidence)

    @property
    def pending_review(self) -> bool:
        return any(not e.verified for e in self.evidence)


@dataclass(frozen=True)
class DocumentAnalysis:
    document_id: str
    filename: str
    claims: tuple[Claim, ...]
    gaps: tuple[str, ...]
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class Finding:
    text: str
    claim_ids: tuple[str, ...]
    basis: str = "reported"


@dataclass(frozen=True)
class QuestionTask:
    task_id: str
    title: str
    kind: str


@dataclass(frozen=True)
class QuestionAnswer:
    task_id: str
    statements: tuple[Finding, ...]
    status: str
    limitations: str = ""
    caveats: str = ""


@dataclass(frozen=True)
class Comparison:
    summary: Finding | None
    agreements: tuple[Finding, ...]
    disagreements: tuple[Finding, ...]
    reasons: tuple[Finding, ...]
    unresolved_questions: tuple[str, ...]
    warnings: tuple[str, ...] = ()
    method_differences: tuple[Finding, ...] = ()
    answers: tuple[QuestionAnswer, ...] = ()


@dataclass(frozen=True)
class Report:
    question: str
    documents: tuple[Document, ...]
    analyses: tuple[DocumentAnalysis, ...]
    comparison: Comparison
    model: str
    generated_at: str
    tasks: tuple[QuestionTask, ...] = ()

    @property
    def coverage_complete(self) -> bool:
        """结构覆盖检查，不宣称回答在语义或科学意义上已经正确。"""
        answers = {answer.task_id: answer for answer in self.comparison.answers}
        return bool(self.tasks and self.comparison.summary) and all(
            task.task_id in answers and answers[task.task_id].status == "answered"
            and bool(answers[task.task_id].statements) for task in self.tasks
        )
