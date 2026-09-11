"""Server-only Supabase Storage REST adapter (custom application JWTs stay in FastAPI)."""
from urllib.parse import quote, urlparse
from uuid import uuid4

import httpx


class SupabaseObjectStore:
    def __init__(self, url: str, secret_key: str, bucket: str):
        self.base_url = url.rstrip("/") + "/storage/v1/object/" + quote(bucket, safe="")
        self.headers = {"apikey": secret_key}
        # Modern sb_secret keys are translated by the gateway. Legacy service-role
        # JWTs also need the Authorization header; never forward the app user's JWT.
        if not secret_key.startswith("sb_secret_"):
            self.headers["Authorization"] = "Bearer " + secret_key

    @staticmethod
    def _path(key: str) -> str:
        if not key or any(part in ("", ".", "..") for part in key.split("/")) or "\\" in key:
            raise ValueError("Invalid object key")
        return quote(key, safe="/")

    def _request(self, method, path="", *, authenticated=False, operation=None, **kwargs):
        headers = {**self.headers, **kwargs.pop("headers", {})}
        base = self.base_url.replace("/object/", "/object/authenticated/", 1) if authenticated else self.base_url
        if operation:
            base = self.base_url.replace("/object/", f"/object/{operation}/", 1)
        try:
            response = httpx.request(method, base + path, headers=headers,
                                     timeout=httpx.Timeout(60, connect=10), follow_redirects=False, **kwargs)
        except httpx.RequestError:
            raise RuntimeError("Supabase Storage connection failed") from None
        if response.is_error:
            # Missing private objects may be returned as 400 with an inner 404.
            try:
                body = response.json()
            except ValueError:
                body = {}
            if response.status_code == 404 or (isinstance(body, dict) and
                    (str(body.get("statusCode")) == "404" or body.get("code") == "NoSuchKey")):
                raise FileNotFoundError("Storage object not found")
            raise RuntimeError(f"Supabase Storage request failed (HTTP {response.status_code})")
        if not 200 <= response.status_code < 300:
            raise RuntimeError("Unexpected Supabase Storage response")
        return response

    def _signed_url(self, value: str, operation: str, key: str) -> str:
        # Only return the exact object URL from our configured Storage origin.
        origin = self.base_url.split("/storage/v1/", 1)[0]
        url = origin + "/storage/v1" + value if value.startswith("/object/") else value
        parsed = urlparse(url)
        expected = urlparse(self.base_url.replace("/object/", f"/object/{operation}/", 1) + "/" + self._path(key))
        if (parsed.scheme, parsed.netloc, parsed.path) != (expected.scheme, expected.netloc, expected.path) or not parsed.query:
            raise RuntimeError("Unexpected Supabase signed URL")
        return url

    def create_upload_url(self, key: str) -> str:
        response = self._request("POST", "/" + self._path(key), operation="upload/sign",
                                 json={}, headers={"x-upsert": "false"})
        return self._signed_url(response.json()["url"], "upload/sign", key)

    def create_download_url(self, key: str) -> str:
        response = self._request("POST", "/" + self._path(key), operation="sign", json={"expiresIn": 60})
        return self._signed_url(response.json()["signedURL"], "sign", key)

    def get_limited(self, key: str, limit: int) -> bytes:
        url = self.base_url.replace("/object/", "/object/authenticated/", 1) + "/" + self._path(key)
        try:
            with httpx.stream("GET", url, params={"cacheNonce": uuid4().hex}, headers=self.headers,
                              timeout=httpx.Timeout(60, connect=10), follow_redirects=False) as response:
                if response.status_code in (400, 404):
                    raise FileNotFoundError("Uploaded object not found")
                if response.status_code != 200:
                    raise RuntimeError("Supabase object verification failed")
                content = bytearray()
                for chunk in response.iter_bytes(chunk_size=65536):
                    if len(content) + len(chunk) > limit:
                        raise ValueError("Uploaded object exceeds declared size")
                    content.extend(chunk)
                return bytes(content)
        except httpx.RequestError:
            raise RuntimeError("Supabase object verification failed") from None

    def put(self, key: str, content: bytes, *, upsert=False):
        self._request("POST", "/" + self._path(key), content=content,
                      headers={"Content-Type": "application/octet-stream", "x-upsert": str(upsert).lower(),
                               "Cache-Control": "no-store"})

    def get(self, key: str) -> bytes:
        # Analysis must read current bytes, including immediately after staging
        # replacement/deletion. Cache-Control alone does not bypass the CDN.
        return self._request("GET", "/" + self._path(key), authenticated=True,
                             params={"cacheNonce": uuid4().hex}).content

    def delete(self, key: str):
        self._path(key)
        self._request("DELETE", json={"prefixes": [key]})
