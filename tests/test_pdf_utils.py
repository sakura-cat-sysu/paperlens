import pymupdf
import pytest

import pdf_utils
from conftest import make_pdf
from pdf_utils import PDFError, parse_pdf
from validators import verify_evidence


def test_extract_pages_and_paragraphs(english_pdf):
    doc = parse_pdf(english_pdf, "research.pdf", "D1")
    assert doc.document_id == "D1"
    assert doc.size_bytes == len(english_pdf)
    assert [p.number for p in doc.pages] == [1, 2]
    assert "completion time" in doc.pages[0].text
    assert "retention" in doc.pages[1].paragraphs[0]


def test_chinese_text(chinese_pdf):
    doc = parse_pdf(chinese_pdf, "中文文献.PDF", "D1")
    assert "提高任务完成效率" in doc.pages[0].text
    assert "长期学习效果" in doc.pages[1].text


@pytest.mark.parametrize("data,name,message", [
    (b"", "empty.pdf", "文件为空"),
    (b"not a PDF", "fake.pdf", "不是有效的 PDF"),
    (b"%PDF-1.7 broken", "broken.pdf", "解析失败"),
    (b"hello", "text.txt", "只支持"),
    (b"x" * (10 * 1024 * 1024 + 1), "large.pdf", "超过 10 MB"),
])
def test_bad_files(data, name, message):
    with pytest.raises(PDFError, match=message):
        parse_pdf(data, name, "D1")


def test_page_limit():
    with pytest.raises(PDFError, match="超过 50 页"):
        parse_pdf(make_pdf(["text"] * 51), "long.pdf", "D1")


def test_ten_pages_allowed():
    assert len(parse_pdf(make_pdf(["text"] * 10), "ten.pdf", "D1").pages) == 10


@pytest.mark.parametrize("page_count", [11, 25, 50])
def test_long_papers_allowed(page_count):
    data = make_pdf([f"Evidence on physical page {i}." for i in range(1, page_count + 1)])
    document = parse_pdf(data, "long-study.pdf", "D1")
    assert len(document.pages) == page_count
    assert document.pages[-1].number == page_count
    assert str(page_count) in document.pages[-1].text
    evidence = verify_evidence({"page": page_count, "quote": f"Evidence on physical page {page_count}."}, document)
    assert evidence.verified


@pytest.mark.parametrize("user_password", ["secret", ""])
def test_encrypted_pdf(user_password):
    data = make_pdf(["secret text"], encryption=pymupdf.PDF_ENCRYPT_AES_256,
                    user_pw=user_password, owner_pw="owner")
    with pytest.raises(PDFError, match="加密"):
        parse_pdf(data, "encrypted.pdf", "D1")


def test_blank_pdf():
    with pytest.raises(PDFError, match="空白"):
        parse_pdf(make_pdf([""]), "blank.pdf", "D1")


def test_blank_page_preserves_physical_number():
    doc = parse_pdf(make_pdf(["first page", "", "third page"]), "blank-middle.pdf", "D1")
    assert doc.pages[2].number == 3
    assert doc.pages[1].text == ""
    assert "第 2 页" in doc.warnings[0]


def test_image_only_pdf():
    with pymupdf.open() as pdf:
        page = pdf.new_page()
        pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 40, 40), False)
        pixmap.clear_with(255)
        page.insert_image(page.rect, stream=pixmap.tobytes("png"))
        data = pdf.tobytes()
    with pytest.raises(PDFError, match="扫描页"):
        parse_pdf(data, "scan.pdf", "D1")


def test_text_limit_is_not_silent_truncation(monkeypatch):
    monkeypatch.setattr(pdf_utils, "MAX_TEXT_CHARS", 30)
    with pytest.raises(PDFError, match="未截断"):
        parse_pdf(make_pdf(["a" * 20, "b" * 20]), "chars.pdf", "D1")


def test_filename_is_display_name_only(english_pdf):
    assert parse_pdf(english_pdf, r"C:\fakepath\study.pdf", "D1").filename == "study.pdf"


def test_scan_with_only_text_page_number_is_rejected():
    with pymupdf.open() as pdf:
        page = pdf.new_page()
        pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 40, 40), False)
        pixmap.clear_with(255)
        page.insert_image(page.rect, stream=pixmap.tobytes("png"))
        page.insert_text((50, 810), "Page 1")
        data = pdf.tobytes()
    with pytest.raises(PDFError, match="极少文字"):
        parse_pdf(data, "scan-with-footer.pdf", "D1")


def test_text_over_old_twenty_thousand_limit_is_allowed():
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=1000, height=3000)
        page.insert_text((20, 30), "\n".join(["a" * 100] * 210), fontsize=5)
        data = pdf.tobytes()
    document = parse_pdf(data, "long-text.pdf", "D1")
    assert document.text_chars > 20_000


@pytest.mark.parametrize("extra_characters", [0, 1])
def test_real_hundred_thousand_character_boundary(extra_characters):
    # 100 + 999*99 个字母，加上 999 个换行，恰好为 100,000 字符。
    lines = ["a" * (100 + extra_characters)] + ["a" * 99] * 999
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=1000, height=8000)
        page.insert_text((20, 30), "\n".join(lines), fontsize=5)
        data = pdf.tobytes()
    if extra_characters:
        with pytest.raises(PDFError, match="超过 100,000 字符"):
            parse_pdf(data, "too-much-text.pdf", "D1")
    else:
        assert parse_pdf(data, "at-limit.pdf", "D1").text_chars == 100_000
