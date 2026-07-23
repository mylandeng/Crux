from __future__ import annotations

from io import BytesIO
from threading import Lock
from typing import Protocol
from urllib.parse import urlparse

from minio import Minio
from minio.error import S3Error

from curx.core.config import Settings


class ObjectStore(Protocol):
    def put_bytes(self, object_key: str, content: bytes, content_type: str) -> None: ...

    def get_bytes(self, object_key: str) -> bytes: ...

    def exists(self, object_key: str) -> bool: ...


class MemoryObjectStore:
    def __init__(self) -> None:
        self._objects: dict[str, tuple[bytes, str]] = {}
        self._lock = Lock()

    def put_bytes(self, object_key: str, content: bytes, content_type: str) -> None:
        with self._lock:
            self._objects[object_key] = (bytes(content), content_type)

    def get_bytes(self, object_key: str) -> bytes:
        with self._lock:
            try:
                content, _ = self._objects[object_key]
            except KeyError as exc:
                raise FileNotFoundError(object_key) from exc
            return bytes(content)

    def exists(self, object_key: str) -> bool:
        with self._lock:
            return object_key in self._objects


class MinioObjectStore:
    def __init__(self, settings: Settings) -> None:
        parsed = urlparse(settings.object_store_endpoint)
        if not parsed.hostname:
            raise ValueError("CURX_OBJECT_STORE_ENDPOINT must be an HTTP(S) URL.")
        endpoint = parsed.hostname
        if parsed.port:
            endpoint = f"{endpoint}:{parsed.port}"
        self._client = Minio(
            endpoint,
            access_key=settings.object_store_access_key,
            secret_key=settings.object_store_secret_key,
            secure=parsed.scheme == "https",
            region=settings.object_store_region,
        )
        self._bucket = settings.object_store_bucket
        self._bucket_ready = False
        self._lock = Lock()

    def _ensure_bucket(self) -> None:
        if self._bucket_ready:
            return
        with self._lock:
            if self._bucket_ready:
                return
            if not self._client.bucket_exists(self._bucket):
                self._client.make_bucket(self._bucket)
            self._bucket_ready = True

    def put_bytes(self, object_key: str, content: bytes, content_type: str) -> None:
        self._ensure_bucket()
        self._client.put_object(
            self._bucket,
            object_key,
            BytesIO(content),
            len(content),
            content_type=content_type,
        )

    def get_bytes(self, object_key: str) -> bytes:
        self._ensure_bucket()
        response = self._client.get_object(self._bucket, object_key)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    def exists(self, object_key: str) -> bool:
        self._ensure_bucket()
        try:
            self._client.stat_object(self._bucket, object_key)
        except S3Error as exc:
            if exc.code in {"NoSuchKey", "NoSuchObject", "NoSuchBucket"}:
                return False
            raise
        return True


def create_object_store(settings: Settings) -> ObjectStore:
    return MinioObjectStore(settings)

