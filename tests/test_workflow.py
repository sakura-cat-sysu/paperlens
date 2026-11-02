import httpx
import pytest

from config import Settings
from conftest import comparison_result, make_pdf, plan_result, single_result
from llm_service import AnalysisError
from pdf_utils import parse_pdf
from workflow import input_signature, run_workflow


@pytest.mark.parametrize("texts,chinese,question", [
    (["生成式人工智能能够提高任务完成效率。", "学生使用人工智能后缩短了完成任务的时间。"], [True, True], "AI 是否提高效率？"),
    (["生成式人工智能能够提高任务完成效率。", "AI improved task completion time in a small sample."], [True, False], "AI 是否提高效率？"),
    (["AI improved task completion time.", "No improvement in retention was observed.", "Student outcomes varied by task."],
     [False, False, False], "Does AI help students?"),
])
def test_complete_chinese_mixed_and_three_document_workflows(texts, chinese, question, settings, mock_service):
    documents = tuple(parse_pdf(make_pdf([text], chinese=is_chinese), f"study-{i}.pdf", f"D{i}")
                      for i, (text, is_chinese) in enumerate(zip(texts, chinese), 1))
    outputs = [plan_result()] + [single_result(doc.pages[0].text) for doc in documents]
    ids = tuple(f"D{i}-C1" for i in range(1, len(documents) + 1))
    service, calls = mock_service(outputs + [comparison_result(ids)])
    events = []
    report = run_workflow(documents, question, settings, service=service, progress=events.append)
    assert len(report.analyses) == len(documents)
    assert all(a.claims[0].supported for a in report.analyses)
    assert report.comparison.summary.claim_ids == ids
    assert len(calls) == len(documents) + 2
    assert report.coverage_complete
    assert len(events) >= 2 * len(documents) + 2


def pair(english_pdf, chinese_pdf):
    return (parse_pdf(english_pdf, "en.pdf", "D1"), parse_pdf(chinese_pdf, "中文.pdf", "D2"))


def test_workflow_cache_and_failure_resume(english_pdf, chinese_pdf, settings, mock_service):
    documents = pair(english_pdf, chinese_pdf)
    service, calls = mock_service([plan_result(), single_result(documents[0].pages[0].text), httpx.ReadTimeout("timeout"),
                                   single_result(documents[1].pages[0].text), comparison_result()])
    cache = {}
    with pytest.raises(AnalysisError, match="超时"):
        run_workflow(documents, "问题", settings, cache=cache, service=service)
    assert len(calls) == 3
    report = run_workflow(documents, "问题", settings, cache=cache, service=service)
    assert len(calls) == 5
    assert run_workflow(documents, "问题", settings, cache=cache, service=service) is report
    assert len(calls) == 5


def test_unverified_quotes_never_enter_second_stage(english_pdf, chinese_pdf, settings, mock_service):
    documents = pair(english_pdf, chinese_pdf)
    service, calls = mock_service([plan_result(), single_result("FABRICATED NOT IN PDF"), single_result(documents[1].pages[0].text)])
    report = run_workflow(documents, "问题", settings, service=service)
    assert report.comparison.summary is None
    assert report.comparison.warnings
    assert len(calls) == 3
    assert not report.coverage_complete
    assert report.comparison.answers[0].status == "unanswered"


@pytest.mark.parametrize("question", ["", "   ", "\n\t"])
def test_empty_question_never_calls_api(question, english_pdf, chinese_pdf, settings, mock_service):
    service, calls = mock_service([])
    with pytest.raises(AnalysisError, match="研究问题"):
        run_workflow(pair(english_pdf, chinese_pdf), question, settings, service=service)
    assert calls == []


def test_missing_key_never_calls_api(english_pdf, chinese_pdf):
    with pytest.raises(AnalysisError, match="OPENAI_API_KEY"):
        run_workflow(pair(english_pdf, chinese_pdf), "问题", Settings(model="test"))


def test_duplicate_pdf_rejected(english_pdf, settings):
    documents = (parse_pdf(english_pdf, "a.pdf", "D1"), parse_pdf(english_pdf, "b.pdf", "D2"))
    with pytest.raises(AnalysisError, match="相同文件"):
        run_workflow(documents, "问题", settings)


def test_input_signature_includes_question_and_model(english_pdf, chinese_pdf, settings):
    documents = pair(english_pdf, chinese_pdf)
    assert input_signature(documents, "问题", settings) == input_signature(documents, " 问题 ", settings)
    assert input_signature(documents, "问题", settings) != input_signature(documents, "新问题", settings)
    assert input_signature(documents, "问题", settings) != input_signature(documents, "问题", Settings(api_key="different", model=settings.model))
