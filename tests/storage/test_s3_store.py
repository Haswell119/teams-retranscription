from __future__ import annotations

import sys
import types
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import SecretStr

from hansard.adapters.storage.s3 import (
    S3ArtifactStore,
    S3ClientConfiguration,
    build_boto3_client,
)
from hansard.domain.errors import ArtifactKeyError, ArtifactNotFoundError, ConfigurationError
from hansard.ports.storage import ArtifactStore

NOW = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)


class MissingObjectError(Exception):
    def __init__(self):
        super().__init__("not found")
        self.response = {"Error": {"Code": "404"}, "ResponseMetadata": {"HTTPStatusCode": 404}}


class FakeS3Client:
    def __init__(self, page_size: int = 1000):
        self.objects: dict[str, tuple[bytes, datetime]] = {}
        self.page_size = page_size
        self.calls: list[str] = []

    def upload_file(self, **kwargs):
        self.calls.append("upload_file")
        self.objects[kwargs["Key"]] = (Path(kwargs["Filename"]).read_bytes(), NOW)

    def download_file(self, **kwargs):
        self.calls.append("download_file")
        stored = self.objects.get(kwargs["Key"])
        if stored is None:
            raise MissingObjectError
        Path(kwargs["Filename"]).write_bytes(stored[0])

    def head_object(self, **kwargs):
        self.calls.append("head_object")
        if kwargs["Key"] not in self.objects:
            raise MissingObjectError
        return {"ContentLength": len(self.objects[kwargs["Key"]][0])}

    def delete_object(self, **kwargs):
        self.calls.append("delete_object")
        self.objects.pop(kwargs["Key"], None)
        return {}

    def list_objects_v2(self, **kwargs):
        self.calls.append("list_objects_v2")
        keys = sorted(key for key in self.objects if key.startswith(kwargs.get("Prefix", "")))
        start = keys.index(kwargs["ContinuationToken"]) if kwargs.get("ContinuationToken") else 0
        page = keys[start : start + self.page_size]
        truncated = start + self.page_size < len(keys)
        response = {
            "Contents": [{"Key": key, "LastModified": self.objects[key][1]} for key in page],
            "IsTruncated": truncated,
        }
        if truncated:
            response["NextContinuationToken"] = keys[start + self.page_size]
        return response


@pytest.fixture
def client():
    return FakeS3Client()


@pytest.fixture
def store(client):
    return S3ArtifactStore(
        bucket="hansard",
        endpoint_url="https://objects.internal",
        client_factory=lambda _configuration: client,
        clock=lambda: NOW,
    )


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "minutes.md"
    path.write_text("# Relevé de décisions", encoding="utf-8")
    return path


def test_it_satisfies_the_artifact_store_port(store):
    assert isinstance(store, ArtifactStore)
    assert store.name == "s3"


def test_path_style_addressing_is_the_default():
    assert S3ClientConfiguration().addressing_style == "path"
    assert S3ClientConfiguration(force_path_style=False).addressing_style == "virtual"


async def test_put_get_list_and_delete_round_trip(store, client, source, tmp_path):
    location = await store.put("meeting-1/minutes.md", source)
    assert location == "s3://hansard/meeting-1/minutes.md"
    assert await store.exists("meeting-1/minutes.md")
    assert await store.list_keys() == ("meeting-1/minutes.md",)

    restored = await store.get("meeting-1/minutes.md", tmp_path / "out" / "minutes.md")
    assert restored.read_text(encoding="utf-8") == source.read_text(encoding="utf-8")

    await store.delete("meeting-1/minutes.md")
    assert not await store.exists("meeting-1/minutes.md")


async def test_downloads_are_staged_and_leave_no_partial_file(store, source, tmp_path):
    await store.put("meeting-1/minutes.md", source)
    destination = tmp_path / "out" / "minutes.md"
    await store.get("meeting-1/minutes.md", destination)
    assert [path.name for path in destination.parent.iterdir()] == ["minutes.md"]


async def test_a_missing_object_is_reported_as_not_found(store, tmp_path):
    with pytest.raises(ArtifactNotFoundError):
        await store.get("meeting-1/minutes.md", tmp_path / "out.md")
    assert await store.exists("meeting-1/minutes.md") is False


async def test_deleting_an_absent_object_is_harmless(store):
    await store.delete("meeting-1/minutes.md")


async def test_hostile_keys_never_reach_the_bucket(store, client, source):
    with pytest.raises(ArtifactKeyError):
        await store.put("../../etc/passwd", source)
    assert client.calls == []


async def test_listing_follows_continuation_tokens(source):
    client = FakeS3Client(page_size=2)
    store = S3ArtifactStore(bucket="hansard", client_factory=lambda _configuration: client)
    for index in range(5):
        await store.put(f"meeting-{index}/minutes.md", source)
    assert len(await store.list_keys()) == 5


async def test_retention_deletes_only_expired_objects(store, client, source):
    await store.put("old/minutes.md", source)
    await store.put("fresh/minutes.md", source)
    client.objects["old/minutes.md"] = (b"old", NOW - timedelta(days=90))

    assert await store.purge_older_than() == ("old/minutes.md",)
    assert await store.list_keys() == ("fresh/minutes.md",)


async def test_zero_retention_never_purges(client, source):
    store = S3ArtifactStore(
        bucket="hansard",
        retention_days=0,
        client_factory=lambda _configuration: client,
        clock=lambda: NOW,
    )
    await store.put("old/minutes.md", source)
    client.objects["old/minutes.md"] = (b"old", NOW - timedelta(days=900))
    assert await store.purge_older_than() == ()


def test_credentials_are_unwrapped_only_when_the_client_is_built(client):
    store = S3ArtifactStore(
        bucket="hansard",
        access_key=SecretStr("AKIA"),
        secret_key=SecretStr("shhh"),
        client_factory=lambda _configuration: client,
    )
    assert "shhh" not in repr(store)
    assert store.configuration.secret_key == "shhh"


def test_the_client_is_created_once(source):
    created: list[S3ClientConfiguration] = []
    client = FakeS3Client()

    def factory(configuration):
        created.append(configuration)
        return client

    store = S3ArtifactStore(bucket="hansard", client_factory=factory)
    store.client()
    store.client()
    assert len(created) == 1


def test_boto3_is_configured_for_path_style_and_a_ca_bundle(monkeypatch, tmp_path):
    captured: dict[str, object] = {}
    bundle = tmp_path / "internal-ca.pem"
    bundle.write_text("-----BEGIN CERTIFICATE-----", encoding="utf-8")

    boto3_module = types.ModuleType("boto3")
    boto3_module.client = lambda service, **kwargs: captured.update(service=service, **kwargs)
    botocore_module = types.ModuleType("botocore")
    config_module = types.ModuleType("botocore.config")
    config_module.Config = dict
    monkeypatch.setitem(sys.modules, "boto3", boto3_module)
    monkeypatch.setitem(sys.modules, "botocore", botocore_module)
    monkeypatch.setitem(sys.modules, "botocore.config", config_module)

    build_boto3_client(
        S3ClientConfiguration(
            endpoint_url="https://objects.internal",
            access_key="AKIA",
            secret_key="shhh",
            ca_bundle=bundle,
        )
    )
    assert captured["service"] == "s3"
    assert captured["endpoint_url"] == "https://objects.internal"
    assert captured["verify"] == str(bundle)
    assert captured["config"]["s3"] == {"addressing_style": "path"}


def test_tls_verification_is_never_disabled():
    captured: dict[str, object] = {}

    def factory(configuration):
        captured["verify"] = configuration.ca_bundle
        return FakeS3Client()

    S3ArtifactStore(bucket="hansard", client_factory=factory).client()
    assert captured["verify"] is None


def test_a_missing_boto3_is_reported_as_a_configuration_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "boto3", None)
    with pytest.raises(ConfigurationError, match="storage-s3"):
        build_boto3_client(S3ClientConfiguration())
