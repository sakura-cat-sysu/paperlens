import pytest

from conftest import comparison_result, single_result
from models import Document, PDFPage
from validators import (OutputError, build_comparison, build_document_analysis, comparison_payload,
                        parse_json_object, validate_document_schema, verify_evidence)


def doc(identifier="D1"):
    return Document(identifier, f"{identifier}.pdf", 100, (
        PDFPage(1, "AI improved\n task completion time.", ("AI improved\n task completion time.",)),
        PDFPage(2, "Long-term retention was not measured.", ("Long-term retention was not measured.",)),
    ), identifier)


def test_json_fences():
    assert parse_json_object('```json\n{"claims": [], "gaps": []}\n```')["claims"] == []


@pytest.mark.parametrize("raw", ["not JSON", "[]", '{"x": 1, "x": 2}', '{"x": NaN}', '{"x": Infinity}',
                                'before {"x": 1} after', "", "{" * 2000])
def test_invalid_json(raw):
    with pytest.raises(OutputError):
        parse_json_object(raw)


def test_whitespace_only_normalization():
    e = verify_evidence({"page": 1, "quote": "AI improved task completion time."}, doc())
    assert e.verified


@pytest.mark.parametrize("evidence", [
    {"page": 2, "quote": "AI improved task completion time."},
    {"page": 0, "quote": "AI improved task completion time."},
    {"page": 3, "quote": "AI improved task completion time."},
    {"page": 1, "quote": "AI improved task completion time!"},
    {"page": 1, "quote": "ai improved task completion time."},
    {"page": 1, "quote": "improved" , "document_id": "D2"},
    {"page": 1, "quote": "AI"},
    {"page": 1, "quote": "AI improved...completion time."},
])
def test_reject_fabricated_quotes_and_wrong_pages(evidence):
    result = verify_evidence(evidence, doc())
    assert not result.verified
    assert result.reason


@pytest.mark.parametrize("page", [True, 1.0, "1", None])
def test_page_type_is_strict(page):
    with pytest.raises(OutputError):
        validate_document_schema(single_result("original quotation", page=page))


def test_unsupported_claims_never_reach_comparison():
    result = single_result("AI improved task completion time.")
    result["claims"].append({"claim": "NO EVIDENCE CLAIM", "explanation": "PRIVATE UNSUPPORTED",
                             "evidence": [{"page": 1, "quote": "FABRICATED QUOTATION"}]})
    result["claims"][0]["evidence"].append({"page": 2, "quote": "INVALID SECOND QUOTE"})
    result["claims"].append({"claim": "未测量长期保持效果。", "explanation": "仅限该篇研究。",
                             "evidence": [{"page": 2, "quote": "Long-term retention was not measured."}]})
    analysis = build_document_analysis(result, doc())
    assert not analysis.claims[0].supported
    assert analysis.claims[0].pending_review
    assert not analysis.claims[1].supported
    assert analysis.claims[2].supported
    payload = comparison_payload((analysis,))
    assert len(payload[0]["claims"]) == 1
    assert payload[0]["claims"][0]["claim_id"] == "D1-C3"
    assert "UNSUPPORTED" not in str(payload)
    assert "INVALID SECOND" not in str(payload)
    assert analysis.warnings


def analyses():
    return tuple(build_document_analysis(single_result("AI improved task completion time."), doc(i))
                 for i in ("D1", "D2"))


def test_valid_cross_document_finding():
    result = build_comparison(comparison_result(), analyses())
    assert result.summary.claim_ids == ("D1-C1", "D2-C1")
    assert len(result.agreements) == 1
    assert not result.warnings


def test_unknown_claim_id_hides_whole_finding():
    result = build_comparison(comparison_result(("D1-C1", "D9-C99")), analyses())
    assert result.summary is None
    assert not result.agreements
    assert len(result.warnings) == 2


def test_one_document_cannot_form_consensus():
    result = build_comparison(comparison_result(("D1-C1",)), analyses())
    assert result.summary
    assert not result.agreements
    assert result.warnings


def test_speculation_preserves_uncertain_label():
    data = comparison_result()
    data["reasons"] = [{"text": "推测：研究设计可能有差异，尚不确定。", "claim_ids": ["D1-C1", "D2-C1"],
                        "basis": "inference"}]
    assert build_comparison(data, analyses()).reasons[0].basis == "inference"


def test_no_claims_is_valid_insufficient_evidence():
    analysis = build_document_analysis({"claims": [], "gaps": ["未涉及该问题。"]}, doc())
    assert analysis.claims == ()
    assert analysis.warnings
    assert comparison_payload((analysis,)) == []
