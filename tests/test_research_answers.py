"""可信度、复杂问题覆盖和草稿重试的回归测试。"""

from contextlib import nullcontext
import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import config
import workflow
from conftest import comparison_result, plan_result, single_result
from models import Document, PDFPage, QuestionTask, Report
from pdf_utils import parse_pdf
from validators import (
    OutputError, build_comparison, build_document_analysis, build_question_plan,
    comparison_payload, validate_comparison_schema, validate_question_plan,
)
from workflow import run_workflow


def analyses():
    result = []
    for identifier in ('D1', 'D2'):
        document = Document(identifier, identifier + '.pdf', 100,
                            (PDFPage(1, 'Original evidence on this page.', ('Original evidence on this page.',)),), identifier)
        result.append(build_document_analysis(single_result('Original evidence on this page.'), document))
    return tuple(result)


def report_for(comparison, tasks):
    return Report('问题', (), analyses(), comparison, 'test-model', '2026-11-02', tasks)


def test_partial_quote_failure_freezes_whole_claim_and_explanation():
    analysis = analyses()[0]
    document = Document('D1', 'D1.pdf', 100, (PDFPage(1, 'Original evidence on this page.', ()),), 'D1')
    raw = single_result('Original evidence on this page.')
    raw['claims'][0]['claim'] = 'PARTIALLY UNSUPPORTED CLAIM'
    raw['claims'][0]['explanation'] = 'DETAIL SUPPORTED ONLY BY THE FAILED QUOTE'
    raw['claims'][0]['evidence'].append({'page': 1, 'quote': 'Fabricated second quotation.'})
    pending = build_document_analysis(raw, document)
    assert pending.claims[0].pending_review
    assert not pending.claims[0].supported
    assert comparison_payload((pending,)) == []
    assert comparison_payload((analysis,))  # 全部引文匹配的观点仍可使用
    data = comparison_result()
    compared = build_comparison(data, (pending, analyses()[1]))
    assert compared.summary is None
    assert not compared.agreements


def test_explicit_research_deliverables_survive_incomplete_question_plan():
    tasks = build_question_plan({'tasks': [{'title': '评估融合可行性', 'kind': 'synthesis'}]},
        '请给出动态决策策略，解释什么条件下适得其反，并设计消融实验和公平基线。')
    assert len(tasks) == 5
    assert [task.task_id for task in tasks] == ['Q1', 'Q2', 'Q3', 'Q4', 'Q5']
    for required in ('策略', '消融', '基线', '失效'):
        assert any(required in task.title for task in tasks)


@pytest.mark.parametrize('data', [{'tasks': []}, {'tasks': [{'title': '研究问题', 'kind': 'unsupported'}]}])
def test_invalid_question_plans_fail_validation(data):
    with pytest.raises(OutputError):
        validate_question_plan(data)


@pytest.mark.parametrize('question', [
    '这篇论文是否做过消融和基线对比？只需总结，不要设计实验。',
    '不要设计消融实验，只回答论文的结论。',
])
def test_plan_does_not_add_unrequested_experiment_design(question):
    assert len(build_question_plan(plan_result(), question)) == 1


def test_missing_answers_become_visible_unanswered_tasks():
    tasks = (QuestionTask('Q1', '直接回答', 'evidence'), QuestionTask('Q2', '消融实验', 'experiment'))
    data = comparison_result()
    compared = build_comparison(data, analyses(), tasks)
    assert compared.answers[0].status == 'answered'
    assert compared.answers[1].status == 'unanswered'
    assert not report_for(compared, tasks).coverage_complete


def test_unknown_source_downgrades_complete_answer():
    tasks = (QuestionTask('Q1', '直接回答', 'evidence'),)
    data = comparison_result()
    data['answers'][0]['statements'].append({'text': '没有真实出处的判断。', 'claim_ids': ['D99-C1'], 'basis': 'reported'})
    compared = build_comparison(data, analyses(), tasks)
    assert compared.answers[0].status == 'partial'
    assert len(compared.answers[0].statements) == 1
    assert not report_for(compared, tasks).coverage_complete


def test_research_design_requires_a_proposal_instead_of_only_literature_summary():
    tasks = (QuestionTask('Q1', '公平基线设计', 'experiment'),)
    data = comparison_result()
    data['answers'][0]['statements'][0]['basis'] = 'reported'
    compared = build_comparison(data, analyses(), tasks)
    assert compared.answers[0].status == 'partial'
    assert not report_for(compared, tasks).coverage_complete
    data['answers'][0]['statements'][0]['basis'] = 'proposal'
    compared = build_comparison(data, analyses(), tasks)
    assert report_for(compared, tasks).coverage_complete
    assert compared.answers[0].statements[0].basis == 'proposal'


def test_empty_answer_cannot_claim_completion():
    tasks = (QuestionTask('Q1', '直接回答', 'evidence'),)
    data = comparison_result()
    data['answers'][0]['statements'] = []
    compared = build_comparison(data, analyses(), tasks)
    assert compared.answers[0].status == 'unanswered'
    assert not report_for(compared, tasks).coverage_complete


def test_method_differences_are_not_displayed_as_conflicting_conclusions():
    data = comparison_result()
    data['disagreements'] = [{'text': '两篇论文采用不同的路由信号。', 'claim_ids': ['D1-C1', 'D2-C1'],
                              'basis': 'reported', 'relation': 'method_difference'}]
    compared = build_comparison(data, analyses())
    assert not compared.disagreements
    assert len(compared.method_differences) == 1
    assert any('机制差异' in warning for warning in compared.warnings)


def test_inference_cannot_masquerade_as_reported_consensus():
    data = comparison_result()
    data['agreements'][0]['basis'] = 'proposal'
    compared = build_comparison(data, analyses())
    assert not compared.agreements
    assert compared.warnings


def test_unknown_epistemic_labels_and_duplicate_answers_are_rejected():
    data = comparison_result()
    data['summary']['basis'] = 'proven'
    with pytest.raises(OutputError):
        validate_comparison_schema(data)
    data = comparison_result()
    data['answers'].append(dict(data['answers'][0]))
    with pytest.raises(OutputError):
        validate_comparison_schema(data)


def test_retry_incomplete_report_only_reissues_comparison(settings, mock_service, english_pdf, chinese_pdf):
    documents = (parse_pdf(english_pdf, 'en.pdf', 'D1'), parse_pdf(chinese_pdf, 'zh.pdf', 'D2'))
    draft = comparison_result()
    draft['answers'] = []
    service, calls = mock_service([plan_result()] + [single_result(d.pages[0].text) for d in documents]
                                   + [draft, comparison_result()])
    cache = {}
    first = run_workflow(documents, '研究问题', settings, service=service, cache=cache)
    assert not first.coverage_complete
    assert len(calls) == 4
    assert run_workflow(documents, '研究问题', settings, service=service, cache=cache) is first
    assert len(calls) == 4
    second = run_workflow(documents, '研究问题', settings, service=service, cache=cache, retry_incomplete=True)
    assert second.coverage_complete
    assert len(calls) == 5
    assert 'documents' in json.loads(calls[-1]['messages'][1]['content'])


def test_ui_marks_draft_and_retry_reuses_completed_stages(monkeypatch, settings, mock_service, english_pdf, chinese_pdf):
    documents = (parse_pdf(english_pdf, 'en.pdf', 'D1'), parse_pdf(chinese_pdf, 'zh.pdf', 'D2'))
    draft = comparison_result()
    draft['answers'] = []
    service, calls = mock_service([plan_result()] + [single_result(d.pages[0].text) for d in documents]
                                   + [draft, comparison_result()])
    monkeypatch.setattr(config, 'load_settings', lambda: settings)
    monkeypatch.setattr(workflow, 'LLMService', lambda cfg: nullcontext(service))
    path = str(Path(__file__).resolve().parents[1] / 'app.py')
    at = AppTest.from_file(path, default_timeout=15).run()
    at.file_uploader(key='uploads').set_value([
        ('en.pdf', english_pdf, 'application/pdf'), ('zh.pdf', chinese_pdf, 'application/pdf')]).run()
    at.text_area(key='question').set_value('研究问题').run()
    at.button(key='analyze').click().run()
    assert not at.exception
    assert not at.session_state['report'].coverage_complete
    assert any('报告草稿' in item.value for item in at.warning)
    assert at.button(key='analyze').label == '重试未完成回答'
    assert not at.button(key='analyze').disabled
    at.run()
    assert len(calls) == 4
    at.button(key='analyze').click().run()
    assert not at.exception
    assert at.session_state['report'].coverage_complete
    assert at.button(key='analyze').disabled
    assert len(calls) == 5


def test_reporting_time_is_not_forced_into_new_experiment_design():
    tasks = build_question_plan({'tasks': [{'title': '说明时间变化幅度与测量范围', 'kind': 'experiment'}]},
                                '说明时间变化幅度与测量范围。')
    assert tasks[0].kind == 'evidence'


def test_format_constraints_do_not_duplicate_research_tasks():
    data = {'tasks': [{'title': '提出具体决策策略', 'kind': 'proposal'},
                      {'title': '区分文献报告、推导与待验证方案并标注来源类型', 'kind': 'synthesis'}]}
    assert len(build_question_plan(data, '提出策略并区分文献报告与推导。')) == 1
    only_format = {'tasks': [data['tasks'][1]]}
    assert len(build_question_plan(only_format, '区分文献报告、推导与待验证方案。')) == 1


def test_calibration_caveat_does_not_turn_answered_proposal_into_missing_task():
    tasks = (QuestionTask('Q1', '动态决策策略', 'proposal'),)
    data = comparison_result()
    data['answers'][0]['statements'][0]['basis'] = 'proposal'
    data['answers'][0]['caveats'] = '具体阈值仍需在验证集校准，方案未经实证。'
    compared = build_comparison(data, analyses(), tasks)
    assert report_for(compared, tasks).coverage_complete
    assert compared.answers[0].caveats
    assert not compared.answers[0].limitations


def test_declared_missing_requirement_prevents_complete_status():
    tasks = (QuestionTask('Q1', '直接回答', 'evidence'),)
    data = comparison_result()
    data['answers'][0]['missing_requirements'] = ['尚未回答指定的失效条件。']
    compared = build_comparison(data, analyses(), tasks)
    assert compared.answers[0].status == 'partial'
    assert not report_for(compared, tasks).coverage_complete
