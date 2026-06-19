from collections.abc import Callable
from datetime import UTC, datetime
import hashlib
import hmac
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen


class ObjectStorageUnavailable(RuntimeError):
    pass


class S3ObjectStorage:
    def __init__(
        self,
        *,
        endpoint: str,
        access_key: str,
        secret_key: str,
        public_endpoint: str | None = None,
        region: str = "us-east-1",
        request_timeout_seconds: int = 5,
        request_opener=urlopen,
        now: Callable[[], datetime] | None = None,
    ):
        self.endpoint = endpoint.rstrip("/")
        self.public_endpoint = (public_endpoint or endpoint).rstrip("/")
        self.access_key = access_key
        self.secret_key = secret_key
        self.region = region
        self.request_timeout_seconds = request_timeout_seconds
        self.request_opener = request_opener
        self.now = now or (lambda: datetime.now(UTC))

    def create_upload_url(
        self,
        *,
        bucket: str,
        key: str,
        content_type: str,
        expires_seconds: int,
    ) -> str:
        return self._presigned_url(
            method="PUT",
            endpoint=self.public_endpoint,
            bucket=bucket,
            key=key,
            expires_seconds=expires_seconds,
        )

    def object_exists(self, *, bucket: str, key: str) -> bool:
        url = self._presigned_url(
            method="HEAD",
            endpoint=self.endpoint,
            bucket=bucket,
            key=key,
            expires_seconds=30,
        )
        request = Request(url, method="HEAD")

        try:
            with self.request_opener(request, timeout=self.request_timeout_seconds) as response:
                return 200 <= response.status < 300
        except HTTPError as exc:
            if exc.code == 404:
                return False
            raise ObjectStorageUnavailable(str(exc)) from exc
        except URLError as exc:
            raise ObjectStorageUnavailable(str(exc)) from exc

    def put_object(
        self,
        *,
        bucket: str,
        key: str,
        content: bytes,
        content_type: str,
    ) -> None:
        url = self._presigned_url(
            method="PUT",
            endpoint=self.endpoint,
            bucket=bucket,
            key=key,
            expires_seconds=30,
        )
        request = Request(
            url,
            data=content,
            headers={"Content-Type": content_type},
            method="PUT",
        )

        try:
            with self.request_opener(request, timeout=self.request_timeout_seconds) as response:
                if not 200 <= response.status < 300:
                    raise ObjectStorageUnavailable(f"Unexpected storage status {response.status}")
        except HTTPError as exc:
            raise ObjectStorageUnavailable(str(exc)) from exc
        except URLError as exc:
            raise ObjectStorageUnavailable(str(exc)) from exc

    def _presigned_url(
        self,
        *,
        method: str,
        endpoint: str,
        bucket: str,
        key: str,
        expires_seconds: int,
    ) -> str:
        parsed = urlparse(endpoint)
        now = self.now()
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        datestamp = now.strftime("%Y%m%d")
        credential_scope = f"{datestamp}/{self.region}/s3/aws4_request"
        canonical_uri = self._canonical_uri(bucket, key)
        query_params = {
            "X-Amz-Algorithm": "AWS4-HMAC-SHA256",
            "X-Amz-Credential": f"{self.access_key}/{credential_scope}",
            "X-Amz-Date": amz_date,
            "X-Amz-Expires": str(expires_seconds),
            "X-Amz-SignedHeaders": "host",
        }
        canonical_query = urlencode(
            sorted(query_params.items()),
            quote_via=quote,
            safe="-_.~",
        )
        canonical_headers = f"host:{parsed.netloc}\n"
        canonical_request = "\n".join(
            [
                method,
                canonical_uri,
                canonical_query,
                canonical_headers,
                "host",
                "UNSIGNED-PAYLOAD",
            ]
        )
        string_to_sign = "\n".join(
            [
                "AWS4-HMAC-SHA256",
                amz_date,
                credential_scope,
                hashlib.sha256(canonical_request.encode()).hexdigest(),
            ]
        )
        signature = hmac.new(
            self._signing_key(datestamp),
            string_to_sign.encode(),
            hashlib.sha256,
        ).hexdigest()
        query = f"{canonical_query}&X-Amz-Signature={signature}"
        return urlunparse((parsed.scheme, parsed.netloc, canonical_uri, "", query, ""))

    @staticmethod
    def _canonical_uri(bucket: str, key: str) -> str:
        return f"/{quote(bucket, safe='')}/{quote(key, safe='/')}"

    def _signing_key(self, datestamp: str) -> bytes:
        date_key = self._sign(f"AWS4{self.secret_key}".encode(), datestamp)
        region_key = self._sign(date_key, self.region)
        service_key = self._sign(region_key, "s3")
        return self._sign(service_key, "aws4_request")

    @staticmethod
    def _sign(key: bytes, message: str) -> bytes:
        return hmac.new(key, message.encode(), hashlib.sha256).digest()
