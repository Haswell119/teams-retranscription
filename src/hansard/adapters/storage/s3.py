from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from pydantic import SecretStr

from hansard.adapters.storage.keys import sanitised_key
from hansard.domain.errors import ArtifactNotFoundError, ConfigurationError

DEFAULT_REGION = "us-east-1"
PATH_ADDRESSING_STYLE = "path"
VIRTUAL_ADDRESSING_STYLE = "virtual"
SIGNATURE_VERSION = "s3v4"
INSTALL_HINT = "pip install 'hansard[storage-s3]'"
MISSING_OBJECT_CODES = frozenset({"404", "NoSuchKey", "NotFound", "NoSuchBucket"})


class S3ClientLike(Protocol):
    def upload_file(self, **kwargs: Any) -> Any: ...

    def download_file(self, **kwargs: Any) -> Any: ...

    def head_object(self, **kwargs: Any) -> Any: ...

    def delete_object(self, **kwargs: Any) -> Any: ...

    def list_objects_v2(self, **kwargs: Any) -> Any: ...


@dataclass(frozen=True, slots=True)
class S3ClientConfiguration:
    endpoint_url: str | None = None
    region: str = DEFAULT_REGION
    access_key: str | None = None
    secret_key: str | None = None
    ca_bundle: Path | None = None
    force_path_style: bool = True

    @property
    def addressing_style(self) -> str:
        return PATH_ADDRESSING_STYLE if self.force_path_style else VIRTUAL_ADDRESSING_STYLE


S3ClientFactory = Callable[[S3ClientConfiguration], S3ClientLike]
UtcClock = Callable[[], datetime]


def _utcnow() -> datetime:
    return datetime.now(UTC)


def build_boto3_client(configuration: S3ClientConfiguration) -> S3ClientLike:
    try:
        import boto3
        from botocore.config import Config
    except ImportError as error:
        raise ConfigurationError(f"the s3 artifact store needs boto3; {INSTALL_HINT}") from error
    client: S3ClientLike = boto3.client(
        "s3",
        endpoint_url=configuration.endpoint_url,
        region_name=configuration.region,
        aws_access_key_id=configuration.access_key,
        aws_secret_access_key=configuration.secret_key,
        verify=str(configuration.ca_bundle) if configuration.ca_bundle else True,
        config=Config(
            signature_version=SIGNATURE_VERSION,
            s3={"addressing_style": configuration.addressing_style},
        ),
    )
    return client


@dataclass(slots=True)
class S3ArtifactStore:
    bucket: str
    endpoint_url: str | None = None
    region: str = DEFAULT_REGION
    access_key: SecretStr | None = None
    secret_key: SecretStr | None = None
    ca_bundle: Path | None = None
    force_path_style: bool = True
    retention_days: int = 30
    client_factory: S3ClientFactory = build_boto3_client
    clock: UtcClock = _utcnow
    _client: S3ClientLike | None = field(default=None, init=False, repr=False)

    @property
    def name(self) -> str:
        return "s3"

    @property
    def configuration(self) -> S3ClientConfiguration:
        return S3ClientConfiguration(
            endpoint_url=self.endpoint_url,
            region=self.region,
            access_key=self.access_key.get_secret_value() if self.access_key else None,
            secret_key=self.secret_key.get_secret_value() if self.secret_key else None,
            ca_bundle=self.ca_bundle,
            force_path_style=self.force_path_style,
        )

    def client(self) -> S3ClientLike:
        if self._client is None:
            self._client = self.client_factory(self.configuration)
        return self._client

    def uri_for(self, key: str) -> str:
        return f"s3://{self.bucket}/{sanitised_key(key)}"

    async def put(self, key: str, source: Path) -> str:
        return await asyncio.to_thread(self._put, key, source)

    async def get(self, key: str, destination: Path) -> Path:
        return await asyncio.to_thread(self._get, key, destination)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._delete, key)

    async def exists(self, key: str) -> bool:
        return await asyncio.to_thread(self._exists, key)

    async def list_keys(self, prefix: str = "") -> tuple[str, ...]:
        return await asyncio.to_thread(lambda: tuple(sorted(entry.key for entry in self._entries(prefix))))

    async def purge_older_than(self, days: int | None = None) -> tuple[str, ...]:
        return await asyncio.to_thread(self._purge_older_than, days)

    def _put(self, key: str, source: Path) -> str:
        if not source.is_file():
            raise ArtifactNotFoundError(f"cannot store missing file {source}")
        self.client().upload_file(Filename=str(source), Bucket=self.bucket, Key=sanitised_key(key))
        return self.uri_for(key)

    def _get(self, key: str, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        staged = destination.with_name(f".{destination.name}.{uuid4().hex}.partial")
        try:
            self.client().download_file(Bucket=self.bucket, Key=sanitised_key(key), Filename=str(staged))
            staged.replace(destination)
        except Exception as error:
            if _is_missing(error):
                raise ArtifactNotFoundError(f"unknown artifact {key}") from error
            raise
        finally:
            staged.unlink(missing_ok=True)
        return destination

    def _delete(self, key: str) -> None:
        try:
            self.client().delete_object(Bucket=self.bucket, Key=sanitised_key(key))
        except Exception as error:
            if not _is_missing(error):
                raise

    def _exists(self, key: str) -> bool:
        try:
            self.client().head_object(Bucket=self.bucket, Key=sanitised_key(key))
        except Exception as error:
            if _is_missing(error):
                return False
            raise
        return True

    def _entries(self, prefix: str) -> Iterator[_ObjectEntry]:
        token: str | None = None
        while True:
            request: dict[str, Any] = {"Bucket": self.bucket, "Prefix": prefix}
            if token:
                request["ContinuationToken"] = token
            page = self.client().list_objects_v2(**request)
            for item in page.get("Contents", ()):
                yield _ObjectEntry(key=str(item["Key"]), last_modified=_moment(item.get("LastModified")))
            token = page.get("NextContinuationToken")
            if not page.get("IsTruncated") or not token:
                return

    def _purge_older_than(self, days: int | None) -> tuple[str, ...]:
        retention = self.retention_days if days is None else days
        if retention <= 0:
            return ()
        cutoff = self.clock() - timedelta(days=retention)
        expired = [entry.key for entry in self._entries("") if entry.last_modified < cutoff]
        for key in expired:
            self.client().delete_object(Bucket=self.bucket, Key=key)
        return tuple(sorted(expired))


@dataclass(frozen=True, slots=True)
class _ObjectEntry:
    key: str
    last_modified: datetime


def _moment(value: Any) -> datetime:
    if not isinstance(value, datetime):
        return datetime.min.replace(tzinfo=UTC)
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _is_missing(error: Exception) -> bool:
    response = getattr(error, "response", None)
    if not isinstance(response, dict):
        return False
    code = str(response.get("Error", {}).get("Code", ""))
    status = str(response.get("ResponseMetadata", {}).get("HTTPStatusCode", ""))
    return code in MISSING_OBJECT_CODES or status == "404"
