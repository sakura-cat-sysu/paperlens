import hashlib
import json

import pytest

from backend import samples


def test_catalog_papers_are_complete_originals_and_fit_upload_limits():
    data = samples.catalog()
    assert len(data["papers"]) == 4
    assert len({paper["id"] for paper in data["papers"]}) == 4
    assert len({paper["sha256"] for paper in data["papers"]}) == 4
    for paper in data["papers"]:
        content, document = samples.read_paper(paper)
        assert hashlib.sha256(content).hexdigest() == paper["sha256"]
        assert len(document.pages) == paper["page_count"]
        assert document.text_chars == paper["text_chars"]
        assert len(content) == paper["size_bytes"]
        assert paper["license"] == "CC BY 4.0"
        assert paper["authors"] and paper["source_url"].startswith("https://")
        assert all(page.number == index for index, page in enumerate(document.pages, 1))
    views = [samples.collection_view(collection) for collection in data["collections"]]
    assert len(views) == 2 and all(len(view.papers) == 2 for view in views)
    assert any({paper.language for paper in view.papers} == {"中文", "English"} for view in views)
    assert all(0 < len(view.question) <= 2000 for view in views)
    assert "asset" not in json.dumps([view.model_dump() for view in views])


def test_corrupt_sample_is_rejected_before_import(monkeypatch, tmp_path):
    paper = samples.catalog()["papers"][0]
    (tmp_path / paper["asset"]).write_bytes(b"corrupted")
    monkeypatch.setattr(samples, "ASSETS", tmp_path)
    with pytest.raises(ValueError, match="checksum"):
        samples.read_paper(paper)


def test_sample_path_cannot_escape_asset_directory():
    with pytest.raises(ValueError, match="path"):
        samples.read_paper({"asset": "../auth.py", "sha256": "invalid"})
