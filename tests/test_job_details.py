"""Retry eligibility exposed by the API must agree with the POST retry guard."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from backend.jobs import job_detail
from backend.schemas import REPORT
from models import Claim, Comparison, DocumentAnalysis, Evidence, Report


def detail(status, eligibility=None):
    report = None
    if eligibility is not None:
        analyses = []
        for index, verified in enumerate(eligibility, 1):
            document_id = f"D{index}"
            evidence = tuple(Evidence(document_id, 1, "Original evidence", value) for value in verified)
            claim = Claim(f"{document_id}-C1", document_id, "Result", "", evidence)
            analyses.append(DocumentAnalysis(document_id, f"paper-{index}.pdf", (claim,), ()))
        value = Report("Question", (), tuple(analyses), Comparison(None, (), (), (), ()), "mock", "2026-11-03")
        report = REPORT.dump_python(value, mode="json")
    now = datetime.now(timezone.utc)
    job = SimpleNamespace(
        id="job-1", question="Question", document_ids=["doc-1", "doc-2"],
        status=status, progress="", error="", attempts=1, created_at=now,
        updated_at=now, report=report,
    )
    return job_detail(job)


@pytest.mark.parametrize("status", ["queued", "running", "completed"])
def test_non_retryable_states_are_explained(status):
    value = detail(status)
    assert not value.can_retry
    assert value.retry_reason == "此任务当前不需要重试。"


def test_failed_job_can_resume_without_a_report():
    value = detail("failed")
    assert value.can_retry
    assert value.retry_reason == ""


@pytest.mark.parametrize("eligibility", [None, [], [(True,)], [(True,), (True, False)], [(), (True,)]])
def test_draft_with_fewer_than_two_supported_documents_cannot_retry(eligibility):
    value = detail("draft", eligibility)
    assert not value.can_retry
    assert "可用证据不足" in value.retry_reason


@pytest.mark.parametrize("eligibility", [[(True,), (True,)], [(False,), (True,), (True,)]])
def test_draft_with_two_supported_documents_can_retry(eligibility):
    value = detail("draft", eligibility)
    assert value.can_retry
    assert value.retry_reason == ""
