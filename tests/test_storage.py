from io import BytesIO

from botocore.response import StreamingBody
from botocore.stub import Stubber
import pytest

from backend import storage
from backend.settings import settings


@pytest.fixture(autouse=True)
def storage_config(monkeypatch, tmp_path):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    settings.cache_clear()
    storage.s3.cache_clear()
    yield
    storage.s3.cache_clear()
    settings.cache_clear()


def test_local_store_roundtrip_and_idempotent_remove(monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    storage.put("owner/id.pdf", b"pdf-data")
    assert storage.get("owner/id.pdf") == b"pdf-data"
    storage.remove("owner/id.pdf")
    storage.remove("owner/id.pdf")
    with pytest.raises(FileNotFoundError):
        storage.get("owner/id.pdf")


def test_private_s3_protocol_uses_server_key_and_closes_body(monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "s3")
    monkeypatch.setenv("S3_BUCKET", "private-test-bucket")
    monkeypatch.setenv("S3_ENDPOINT_URL", "https://s3.test.invalid")
    client = storage.s3()
    body = StreamingBody(BytesIO(b"pdf-data"), 8)
    with Stubber(client) as stub:
        stub.add_response(
            "put_object",
            {},
            {
                "Bucket": "private-test-bucket",
                "Key": "owner/id.pdf",
                "Body": b"pdf-data",
                "ContentType": "application/pdf",
            },
        )
        stub.add_response(
            "get_object", {"Body": body}, {"Bucket": "private-test-bucket", "Key": "owner/id.pdf"}
        )
        stub.add_response("delete_object", {}, {"Bucket": "private-test-bucket", "Key": "owner/id.pdf"})
        storage.put("owner/id.pdf", b"pdf-data")
        assert storage.get("owner/id.pdf") == b"pdf-data"
        assert body._raw_stream.closed
        storage.remove("owner/id.pdf")
        stub.assert_no_pending_responses()
