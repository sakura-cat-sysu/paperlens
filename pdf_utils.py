"""使用 PyMuPDF 按页提取文字。不做 OCR，也不静默截断。"""

import hashlib

import pymupdf

from config import MAX_FILE_BYTES, MAX_PAGES, MAX_TEXT_CHARS
from models import Document, PDFPage


class PDFError(ValueError):
    """可直接向用户展示的文件错误。"""


def parse_pdf(data: bytes, filename: str, document_id: str) -> Document:
    filename = filename.replace("\\", "/").rsplit("/", 1)[-1]
    if not filename.lower().endswith(".pdf"):
        raise PDFError("只支持 .pdf 格式，请选择文字型 PDF 文件。")
    if not data:
        raise PDFError("文件为空，请重新选择有效的 PDF。")
    if len(data) > MAX_FILE_BYTES:
        raise PDFError("文件超过 10 MB，请缩小文件后重新上传；未截断文件。")
    if b"%PDF-" not in data[:1024]:
        raise PDFError("文件不是有效的 PDF，请勿通过修改后缀名转换文件。")

    try:
        with pymupdf.open(stream=data, filetype="pdf") as pdf:
            if pdf.needs_pass or pdf.is_encrypted or (pdf.metadata or {}).get("encryption"):
                raise PDFError("文件已加密或设有权限保护，请先解密后再上传。")
            if not pdf.is_pdf or pdf.page_count == 0:
                raise PDFError("PDF 没有可读取的页面。")
            if pdf.page_count > MAX_PAGES:
                raise PDFError(f"文件有 {pdf.page_count} 页，超过 {MAX_PAGES} 页上限；请先拆分，未截断页面。")

            pages = []
            warnings = []
            total_chars = 0
            for number, page in enumerate(pdf, start=1):
                blocks = page.get_text("blocks", sort=True)
                paragraphs = tuple(
                    block[4].strip() for block in blocks
                    if block[6] == 0 and block[4].strip()
                )
                text = "\n\n".join(paragraphs)
                images = page.get_image_info()
                meaningful_chars = sum(c.isalnum() for c in text)
                # 部分扫描页仅有可复制的页脚/页码，不能把它误当作完整正文。
                image_coverage = max(
                    ((pymupdf.Rect(image["bbox"]) & page.rect).get_area() / page.rect.get_area()
                     for image in images), default=0,
                )
                if image_coverage >= 0.75 and meaningful_chars < 50:
                    raise PDFError(f"第 {number} 页主要为图片或扫描页内容，仅能读取极少文字。V0 不支持 OCR。")
                total_chars += len(text)
                if total_chars > MAX_TEXT_CHARS:
                    raise PDFError(f"提取文本超过 {MAX_TEXT_CHARS:,} 字符，请先拆分文档；未截断正文。")
                if not any(c.isalnum() for c in text):
                    if images:
                        raise PDFError(f"第 {number} 页为图片或扫描页，无法提取文字。V0 不支持 OCR。")
                    warnings.append(f"第 {number} 页未提取到正文，已保留原始页码。")
                elif text.count("\ufffd") > max(5, len(text) // 5):
                    raise PDFError(f"第 {number} 页文字编码异常，无法可靠读取，请换用文字可复制的 PDF。")
                pages.append(PDFPage(number, text, paragraphs))

            if not any(any(c.isalnum() for c in p.text) for p in pages):
                raise PDFError("PDF 为空白文档，或没有可提取的文字。请上传文字型 PDF。")
            return Document(
                document_id=document_id, filename=filename, size_bytes=len(data),
                pages=tuple(pages), sha256=hashlib.sha256(data).hexdigest(),
                warnings=tuple(warnings),
            )
    except PDFError:
        raise
    except Exception:
        raise PDFError("PDF 解析失败，文件可能损坏或格式不受支持，请重新导出 PDF 后再试。") from None
