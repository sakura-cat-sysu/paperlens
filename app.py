"""Streamlit 主页面。启动：streamlit run app.py。"""

import hashlib
import logging
import re

import streamlit as st

from config import MAX_FILES, MAX_PAGES, MAX_QUESTION_CHARS, MAX_TEXT_CHARS, MIN_FILES, load_settings
from llm_service import AnalysisError
from models import Claim, Document, Finding, Report
from pdf_utils import PDFError, parse_pdf
from workflow import input_signature, run_workflow


def escape_markdown(text: str) -> str:
    return re.sub(r"([\\`*_{}\[\]<>()#+\-.!|])", r"\\\1", text)


def plain(text: str) -> None:
    """把模型/文档内容当作文字，避免其中的 Markdown 链接或图片生效。"""
    st.markdown(escape_markdown(text))


def request_analysis() -> None:
    if not st.session_state.get("busy", False):
        st.session_state.busy = True
        st.session_state.analysis_requested = True


def render_sources(claim: Claim, documents: dict[str, Document]) -> None:
    for evidence in claim.evidence:
        if evidence.verified:
            document = documents[evidence.document_id]
            st.caption(escape_markdown(f"{claim.claim_id} · {document.filename} · PDF 第 {evidence.page} 页 · 原文已匹配"))
            st.code(evidence.quote, language=None, wrap_lines=True)


def render_finding(finding: Finding, claims: dict[str, Claim], documents: dict[str, Document]) -> None:
    labels = {"reported": "论文报告 · 限于原文设定", "inference": "证据推导 / 假设 · 未经实证",
              "proposal": "拟议方案 · 尚待实验验证"}
    st.caption(labels[finding.basis])
    plain(finding.text)
    if finding.basis == "proposal":
        st.caption("下列引用说明设计依据，不表示原论文已验证此方案有效。")
    with st.expander("查看支持原文 · " + " / ".join(finding.claim_ids)):
        for claim_id in finding.claim_ids:
            render_sources(claims[claim_id], documents)


def render_report(report: Report) -> None:
    documents = {d.document_id: d for d in report.documents}
    claims = {c.claim_id: c for a in report.analyses for c in a.claims}
    comparison = report.comparison
    st.divider()
    st.caption("ANALYSIS / 文献分析报告")
    answered = sum(a.status == "answered" and bool(a.statements) for a in comparison.answers)
    if report.coverage_complete:
        st.success(f"逐项回答已生成：{answered}/{len(report.tasks)} 项。内容仍需结合原文复核。")
    else:
        st.warning(f"当前为报告草稿：{answered}/{len(report.tasks)} 项已有完整结构的回答，仍有未完成项或缺少综合结论。")
    st.caption("完成状态仅检查问题清单和有效出处，不等于语义正确或事实认证。")
    st.subheader("综合结论")
    with st.container(border=True):
        if comparison.summary:
            render_finding(comparison.summary, claims, documents)
        else:
            st.info("证据不足，未形成可追溯的综合结论。请查看单篇观点与校验提示。")
        st.caption("研究问题")
        plain(report.question)
        st.caption(escape_markdown(f"基于 {len(report.documents)} 篇文献 · 模型：{report.model}"))
    for warning in comparison.warnings:
        st.warning(warning)

    st.subheader("按问题逐项回答")
    answers = {a.task_id: a for a in comparison.answers}
    status_labels = {"answered": "已回答 · 待人工复核", "partial": "部分回答", "unanswered": "未完成"}
    for task in report.tasks:
        with st.container(border=True):
            st.caption(task.task_id)
            plain(task.title)
            answer = answers.get(task.task_id)
            if answer is None:
                st.warning("未完成：模型没有回答此项要求。")
                continue
            st.caption(status_labels[answer.status])
            for statement in answer.statements:
                render_finding(statement, claims, documents)
            if answer.limitations:
                st.warning(escape_markdown(answer.limitations))
            if answer.caveats:
                st.caption("适用限制 / 待验证条件")
                plain(answer.caveats)

    st.subheader("文献观点")
    for analysis in report.analyses:
        with st.container(border=True):
            st.caption(analysis.document_id + " / 独立分析")
            plain(analysis.filename)
            if not analysis.claims:
                for warning in analysis.warnings:
                    st.warning(warning)
            for claim in analysis.claims:
                st.markdown(f"**{claim.claim_id}**")
                plain(claim.claim)
                if claim.explanation:
                    plain(claim.explanation)
                if claim.supported:
                    st.caption("论文报告 · 引文全部通过页内匹配，语义仍需复核")
                    with st.expander("原文已匹配 · 查看证据与页码"):
                        render_sources(claim, documents)
                elif claim.pending_review:
                    st.warning("待复核：存在未匹配引用，整条观点和解释均未进入综合分析。")
                    if any(e.verified for e in claim.evidence):
                        with st.expander("已匹配片段 · 仅供人工复核，不代表整条观点已通过"):
                            render_sources(claim, documents)
                else:
                    st.warning("证据不足：此观点未进入综合比较。")
                rejected = [e for e in claim.evidence if not e.verified]
                if rejected:
                    with st.expander("未通过匹配的引用 · 不作为已核实证据"):
                        for evidence in rejected:
                            st.caption(f"模型声明的页码：{evidence.page}（未核实）")
                            st.warning(evidence.reason)
                            st.code(evidence.quote, language=None, wrap_lines=True)
            if analysis.gaps:
                st.caption("文献未充分涉及")
                for gap in analysis.gaps:
                    plain("• " + gap)

    st.subheader("共识与分歧")
    left, right = st.columns(2)
    with left, st.container(border=True):
        st.markdown("#### 共同观点")
        for finding in comparison.agreements:
            render_finding(finding, claims, documents)
        if not comparison.agreements:
            st.info("未识别到有充分来源的跨文献共识。")
    with right, st.container(border=True):
        st.markdown("#### 结论冲突（可比条件下）")
        for finding in comparison.disagreements:
            render_finding(finding, claims, documents)
        if not comparison.disagreements:
            st.info("未识别到有充分来源的结论冲突。方法不同或未研究同一事项不视为冲突。")
    st.markdown("#### 机制差异与互补性")
    for finding in comparison.method_differences:
        render_finding(finding, claims, documents)
    if not comparison.method_differences:
        st.caption("未形成带有充分来源的机制差异分析。")
    if comparison.reasons:
        st.markdown("#### 可能的差异原因")
        for reason in comparison.reasons:
            with st.container(border=True):
                if reason.basis != "reported":
                    st.warning("推测 / 不确定：以下解释需要更多证据。")
                else:
                    st.caption("模型判断为证据中明确讨论的解释；请结合原文复核。")
                render_finding(reason, claims, documents)

    st.subheader("证据来源")
    matched = [c for c in claims.values() if c.supported]
    if not matched:
        st.info("当前没有通过页内原文匹配的证据。")
    for claim in matched:
        with st.expander(escape_markdown(f"{claim.claim_id} · {documents[claim.document_id].filename}")):
            render_sources(claim, documents)
    st.caption("页码按 PDF 物理页序号计算，从 1 开始。原文匹配只确认片段存在，不等于观点或事实认证。")

    st.subheader("尚待研究的问题")
    if comparison.unresolved_questions:
        for question in comparison.unresolved_questions:
            plain("• " + question)
    else:
        st.caption("未提出额外问题，可参考上方各篇文献未充分涉及的部分。")


def prepare_documents(uploads) -> tuple[tuple[Document, ...], tuple[str, ...]]:
    """只在上传内容或限制变化时解析，缓存限定在当前会话内。"""
    raw_files = [(file.name, file.getvalue()) for file in uploads]
    fingerprint = (MAX_PAGES, MAX_TEXT_CHARS,
                   tuple((name, hashlib.sha256(data).hexdigest()) for name, data in raw_files))
    if fingerprint != st.session_state.get("upload_fingerprint"):
        documents, errors = [], []
        if len(raw_files) > MAX_FILES:
            errors.append("一次最多上传 3 篇 PDF，请移除多余文件。")
        elif raw_files:
            with st.status("正在解析文献", expanded=True) as status:
                for index, (name, data) in enumerate(raw_files, start=1):
                    try:
                        documents.append(parse_pdf(data, name, f"D{index}"))
                        st.write(escape_markdown(f"已解析 D{index}：{name}"))
                    except PDFError as exc:
                        errors.append(f"{name}：{exc}")
                status.update(label="文献解析完成" if not errors else "部分文献无法读取",
                              state="complete" if not errors else "error", expanded=False)
        if len({d.sha256 for d in documents}) < len(documents):
            errors.append("检测到相同文件，请选择不同文献进行比较。")
        st.session_state.upload_fingerprint = fingerprint
        st.session_state.documents = tuple(documents)
        st.session_state.upload_errors = tuple(errors)
    return st.session_state.documents, st.session_state.upload_errors


def main() -> None:
    st.set_page_config(page_title="文镜 AI · PaperLens", page_icon="📖", layout="wide")
    st.markdown("""<style>
        .block-container {max-width: 1140px; padding-top: 2.5rem; padding-bottom: 3rem;}
        h1 {letter-spacing: -.035em;}
        [data-testid="stVerticalBlockBorderWrapper"] {border-radius: 12px;}
        div[data-testid="stFileUploader"] {border-radius: 10px;}
        [data-testid="stSidebar"] .block-container {padding-top: 2rem;}
        </style>""", unsafe_allow_html=True)
    for key, default in (("busy", False), ("stage_cache", {}), ("report", None),
                         ("last_error", ""), ("documents", ()), ("upload_errors", ())):
        if key not in st.session_state:
            st.session_state[key] = default
    settings = load_settings()

    with st.sidebar:
        st.markdown("### PL / 文镜 AI")
        st.caption("科研与知识挖掘 · V0")
        st.divider()
        st.markdown("**一次分析，五个步骤**")
        st.write("01　读取文献与页码")
        st.write("02　拆解研究问题")
        st.write("03　提取观点并校验引用")
        st.write("04　逐项回答与文献比较")
        st.write("05　检查遗漏与证据边界")
        st.divider()
        if settings.is_deepseek:
            st.caption("当前模型服务：DeepSeek")
        if settings.missing:
            st.warning("模型配置未完成")
            st.caption("缺少：" + "、".join(settings.missing))
        else:
            st.success("模型配置已读取")
            st.caption("配置状态不代表已验证接口连通性。")
            st.text(settings.model)
        with st.expander("本地配置说明", expanded=bool(settings.missing)):
            if settings.is_deepseek:
                st.write("DeepSeek 地址和模型已配置，请在本地 .env 填写你的 DeepSeek API Key。")
                st.code("OPENAI_API_KEY=\nOPENAI_BASE_URL=https://api.deepseek.com\nOPENAI_MODEL=deepseek-flash", language="bash")
                st.caption("OPENAI_ 是兼容 SDK 的变量名；这里填写 DeepSeek 的密钥。")
            else:
                st.write("将 .env.example 复制为 .env，填入密钥和模型名称。")
                st.code("OPENAI_API_KEY=\nOPENAI_BASE_URL=\nOPENAI_MODEL=", language="bash")
                st.caption("BASE_URL 可留空。密钥仅在服务端读取。")
        st.button("重新读取配置", disabled=st.session_state.busy)
        st.caption("仅支持文字型 PDF；不进行 OCR。")

    st.caption("PAPERLENS / 跨语言多文献观点分析")
    st.title("文镜 AI · PaperLens")
    st.markdown("### 让不同文献的观点，在同一面镜子里呈现。")
    st.write("上传 2～3 篇中英文文献，提出一个研究问题，获得可追溯原文的中文分析。")
    st.divider()

    upload_column, question_column = st.columns([1.1, 1], gap="large")
    with upload_column:
        st.subheader("01 / 上传文献")
        uploads = st.file_uploader("选择 2～3 份 PDF", type=["pdf"], accept_multiple_files=True,
                                   key="uploads", disabled=st.session_state.busy,
                                   help=f"每份不超过 10 MB、{MAX_PAGES} 页和 {MAX_TEXT_CHARS:,} 个提取字符。")
        st.caption(f"每份 ≤ 10 MB · ≤ {MAX_PAGES} 页 · ≤ {MAX_TEXT_CHARS:,} 字符 · 中文 / 英文")
        documents, errors = prepare_documents(uploads or [])
        for error in errors:
            st.error(escape_markdown(error))
        for document in documents:
            with st.container(border=True):
                st.text(f"{document.document_id} · {document.filename}")
                st.caption(f"{document.size_bytes / 1024:.1f} KB · {len(document.pages)} 页 · {document.text_chars:,} 字符")
                for warning in document.warnings:
                    st.warning(warning)
                with st.expander("查看按页提取的文本"):
                    number = st.selectbox("PDF 物理页码", range(1, len(document.pages) + 1),
                                          key="page_" + document.document_id, disabled=st.session_state.busy)
                    st.code(document.pages[number - 1].text or "（此页没有可提取文字）",
                            language=None, wrap_lines=True)
        if len(documents) < MIN_FILES:
            st.caption("准备好至少两篇不同文献后，即可开始。")

    with question_column:
        st.subheader("02 / 提出研究问题")
        question = st.text_area("你的研究问题", key="question", height=160,
                                max_chars=MAX_QUESTION_CHARS, disabled=st.session_state.busy,
                                placeholder="生成式 AI 是否能显著提高大学生的学习效率？")
        st.caption("聚焦一个可比较的问题，分析结果用中文呈现，引用保留原语言。")
        st.info("点击分析后，文献文本会发送给你配置的模型服务。文件和结果仅保留在当前会话，不主动保存到磁盘。")

        signature = input_signature(documents, question, settings)
        if signature != st.session_state.get("active_input"):
            st.session_state.active_input = signature
            st.session_state.stage_cache = {}
            st.session_state.report = None
            st.session_state.last_error = ""
        current_report = st.session_state.report
        has_report = current_report is not None
        complete = has_report and current_report.coverage_complete
        can_retry = has_report and sum(any(c.supported for c in a.claims) for a in current_report.analyses) >= MIN_FILES
        ready = MIN_FILES <= len(documents) <= MAX_FILES and not errors and bool(question.strip()) and not settings.missing
        label = "正在分析…" if st.session_state.busy else (
            "当前逐项回答已生成" if complete else ("重试未完成回答" if can_retry else (
                "证据不足，请调整问题" if has_report else "开始智能分析")))
        st.button(label, type="primary", key="analyze", width="stretch", on_click=request_analysis,
                  disabled=not ready or st.session_state.busy or complete or (has_report and not can_retry))
        if settings.missing:
            st.caption("请先在本地 .env 中配置 API Key 和模型，再点击左侧重新读取配置。")
        if complete:
            st.success("逐项回答已生成；展开原文或切换页码不会重复调用模型。")
        elif has_report:
            st.warning("报告有未完成部分，详见下方问题清单。")
            if can_retry:
                st.caption("重试仅重新生成综合回答，复用已完成的问题拆解和文献提取；会产生一次新的模型请求。")
        if st.session_state.last_error:
            st.error(st.session_state.last_error)
            st.caption("可再次点击开始分析；已完成的文献分析会被复用。")

    if st.session_state.pop("analysis_requested", False):
        try:
            if not ready:
                raise AnalysisError("请检查文献、研究问题和模型配置后重试。")
            with st.status("正在拆解研究问题", expanded=True) as status:
                report = run_workflow(documents, question, settings, cache=st.session_state.stage_cache,
                                      progress=lambda message: status.write(escape_markdown(message)),
                                      retry_incomplete=has_report)
                st.session_state.report = report
                st.session_state.last_error = ""
                status.update(label="逐项回答已生成" if report.coverage_complete else "报告草稿已生成，仍有未完成项",
                              state="complete", expanded=False)
        except AnalysisError as exc:
            st.session_state.last_error = str(exc)
        except Exception as exc:
            # 不记录异常正文/请求，避免供应商异常中可能带有密钥或文档内容。
            logging.getLogger(__name__).error("Unexpected analysis error: %s", type(exc).__name__)
            st.session_state.last_error = "分析暂时无法完成，请重试；若持续失败，请检查模型服务的接口兼容性。"
        finally:
            st.session_state.busy = False
        st.rerun()

    if st.session_state.report is not None:
        render_report(st.session_state.report)
    else:
        st.divider()
        st.caption("有出处的观点，才进入比较。")
        st.caption("分析仅依据本次上传的文献。证据不足时会明确提示，不强行生成共识或分歧。")


if __name__ == "__main__":
    main()
