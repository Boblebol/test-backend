from datetime import UTC, datetime
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse

from app.modules.documents.storage import ObjectStorageUnavailable, S3ObjectStorage


class Response:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


def fixed_now() -> datetime:
    return datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


def test_s3_storage_generates_presigned_put_url() -> None:
    storage = S3ObjectStorage(
        endpoint="http://minio:9000",
        public_endpoint="http://127.0.0.1:9000",
        access_key="access",
        secret_key="secret",
        region="us-east-1",
        now=fixed_now,
    )

    url = storage.create_upload_url(
        bucket="primmo-documents",
        key="orgs/primmo-alpha/users/alpha-example-com/documents/document-id/lease.pdf",
        content_type="application/pdf",
        expires_seconds=300,
    )

    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    assert parsed.scheme == "http"
    assert parsed.netloc == "127.0.0.1:9000"
    assert (
        parsed.path
        == "/primmo-documents/orgs/primmo-alpha/users/alpha-example-com/documents/document-id/lease.pdf"
    )
    assert query["X-Amz-Algorithm"] == ["AWS4-HMAC-SHA256"]
    assert query["X-Amz-Credential"] == ["access/20260102/us-east-1/s3/aws4_request"]
    assert query["X-Amz-Date"] == ["20260102T030405Z"]
    assert query["X-Amz-Expires"] == ["300"]
    assert query["X-Amz-SignedHeaders"] == ["host"]
    assert query["X-Amz-Signature"]


def test_s3_storage_checks_object_existence_with_presigned_head() -> None:
    opened_urls = []

    def opener(request, timeout: int):
        opened_urls.append(request.full_url)
        return Response()

    storage = S3ObjectStorage(
        endpoint="http://minio:9000",
        access_key="access",
        secret_key="secret",
        request_opener=opener,
        now=fixed_now,
    )

    assert storage.object_exists(bucket="primmo-documents", key="file.pdf") is True
    assert opened_urls[0].startswith("http://minio:9000/primmo-documents/file.pdf?")


def test_s3_storage_returns_false_when_object_is_missing() -> None:
    def opener(request, timeout: int):
        raise HTTPError(request.full_url, 404, "Not Found", hdrs=None, fp=None)

    storage = S3ObjectStorage(
        endpoint="http://minio:9000",
        access_key="access",
        secret_key="secret",
        request_opener=opener,
        now=fixed_now,
    )

    assert storage.object_exists(bucket="primmo-documents", key="missing.pdf") is False


def test_s3_storage_puts_object_with_presigned_internal_put() -> None:
    opened_requests = []

    def opener(request, timeout: int):
        opened_requests.append(request)
        return Response()

    storage = S3ObjectStorage(
        endpoint="http://minio:9000",
        access_key="access",
        secret_key="secret",
        request_opener=opener,
        now=fixed_now,
    )

    storage.put_object(
        bucket="primmo-documents",
        key="file.pdf",
        content=b"%PDF-1.4\n",
        content_type="application/pdf",
    )

    request = opened_requests[0]
    assert request.get_method() == "PUT"
    assert request.full_url.startswith("http://minio:9000/primmo-documents/file.pdf?")
    assert request.data == b"%PDF-1.4\n"
    assert request.headers["Content-type"] == "application/pdf"


def test_s3_storage_put_object_wraps_storage_errors() -> None:
    def opener(request, timeout: int):
        raise HTTPError(request.full_url, 500, "Internal Server Error", hdrs=None, fp=None)

    storage = S3ObjectStorage(
        endpoint="http://minio:9000",
        access_key="access",
        secret_key="secret",
        request_opener=opener,
        now=fixed_now,
    )

    try:
        storage.put_object(
            bucket="primmo-documents",
            key="file.pdf",
            content=b"%PDF-1.4\n",
            content_type="application/pdf",
        )
    except ObjectStorageUnavailable:
        pass
    else:
        raise AssertionError("expected ObjectStorageUnavailable")
