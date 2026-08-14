from __future__ import annotations

import mimetypes
import time
import uuid
from pathlib import Path
from typing import Protocol

from cryptography.fernet import Fernet, InvalidToken

from .config import Settings


class AudioStorageError(RuntimeError):
    pass


class AudioStorage(Protocol):
    def put(self, assessment_id: str, response_id: str, payload: bytes, content_type: str) -> str: ...
    def get(self, uri: str) -> bytes: ...
    def delete_expired(self, retention_days: int) -> int: ...


class EncryptedLocalAudioStorage:
    def __init__(self, root: Path, encryption_key: str) -> None:
        if not encryption_key:
            raise AudioStorageError("AUDIO_ENCRYPTION_KEY is required")
        try:
            self._fernet = Fernet(encryption_key.encode())
        except ValueError as exc:
            raise AudioStorageError("AUDIO_ENCRYPTION_KEY is not a valid Fernet key") from exc
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, assessment_id: str, response_id: str, payload: bytes, content_type: str) -> str:
        if not payload:
            raise AudioStorageError("Audio payload is empty")
        extension = mimetypes.guess_extension(content_type.split(";", 1)[0]) or ".bin"
        safe_assessment = assessment_id.replace("/", "_")
        directory = (self.root / safe_assessment).resolve()
        if self.root not in directory.parents:
            raise AudioStorageError("Invalid assessment audio path")
        directory.mkdir(parents=True, exist_ok=True)
        filename = f"{response_id.replace('/', '_')}-{uuid.uuid4().hex}{extension}.fernet"
        target = (directory / filename).resolve()
        if self.root not in target.parents:
            raise AudioStorageError("Invalid audio target path")
        target.write_bytes(self._fernet.encrypt(payload))
        return f"encrypted+local://{safe_assessment}/{filename}"

    def _path(self, uri: str) -> Path:
        prefix = "encrypted+local://"
        if not uri.startswith(prefix):
            raise AudioStorageError("Unsupported local audio URI")
        target = (self.root / uri.removeprefix(prefix)).resolve()
        if self.root not in target.parents:
            raise AudioStorageError("Audio URI escapes storage root")
        return target

    def get(self, uri: str) -> bytes:
        try:
            return self._fernet.decrypt(self._path(uri).read_bytes())
        except (FileNotFoundError, InvalidToken) as exc:
            raise AudioStorageError("Audio object is missing or failed integrity validation") from exc

    def delete_expired(self, retention_days: int) -> int:
        cutoff = time.time() - retention_days * 86400
        deleted = 0
        for path in self.root.rglob("*.fernet"):
            if path.is_file() and path.stat().st_mtime < cutoff:
                path.unlink()
                deleted += 1
        for directory in sorted(self.root.rglob("*"), reverse=True):
            if directory.is_dir():
                try:
                    directory.rmdir()
                except OSError:
                    pass
        return deleted


class EncryptedS3AudioStorage:
    def __init__(self, settings: Settings) -> None:
        if not settings.audio_encryption_key:
            raise AudioStorageError("AUDIO_ENCRYPTION_KEY is required")
        if not settings.s3_bucket:
            raise AudioStorageError("S3_BUCKET is required")
        try:
            import boto3
        except ImportError as exc:
            raise AudioStorageError("Install boto3 for S3 audio storage") from exc
        self._fernet = Fernet(settings.audio_encryption_key.encode())
        self._client = boto3.client("s3", region_name=settings.s3_region or None)
        self.bucket = settings.s3_bucket
        self.prefix = settings.s3_prefix.strip("/")
        self.kms_key_id = settings.s3_kms_key_id

    def put(self, assessment_id: str, response_id: str, payload: bytes, content_type: str) -> str:
        key = f"{self.prefix}/{assessment_id}/{response_id}-{uuid.uuid4().hex}.fernet"
        kwargs = {
            "Bucket": self.bucket,
            "Key": key,
            "Body": self._fernet.encrypt(payload),
            "ContentType": "application/octet-stream",
            "Metadata": {"original-content-type": content_type},
        }
        if self.kms_key_id:
            kwargs.update(ServerSideEncryption="aws:kms", SSEKMSKeyId=self.kms_key_id)
        else:
            kwargs.update(ServerSideEncryption="AES256")
        self._client.put_object(**kwargs)
        return f"encrypted+s3://{self.bucket}/{key}"

    def get(self, uri: str) -> bytes:
        prefix = f"encrypted+s3://{self.bucket}/"
        if not uri.startswith(prefix):
            raise AudioStorageError("Unsupported S3 audio URI")
        response = self._client.get_object(Bucket=self.bucket, Key=uri.removeprefix(prefix))
        try:
            return self._fernet.decrypt(response["Body"].read())
        except InvalidToken as exc:
            raise AudioStorageError("S3 audio failed integrity validation") from exc

    def delete_expired(self, retention_days: int) -> int:
        cutoff = time.time() - retention_days * 86400
        deleted = 0
        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=f"{self.prefix}/"):
            objects = [
                {"Key": item["Key"]}
                for item in page.get("Contents", [])
                if item["LastModified"].timestamp() < cutoff
            ]
            if objects:
                self._client.delete_objects(Bucket=self.bucket, Delete={"Objects": objects})
                deleted += len(objects)
        return deleted


def build_audio_storage(settings: Settings) -> AudioStorage:
    if settings.audio_storage_backend == "local":
        return EncryptedLocalAudioStorage(settings.audio_storage_root, settings.audio_encryption_key)
    if settings.audio_storage_backend == "s3":
        return EncryptedS3AudioStorage(settings)
    raise AudioStorageError(f"Unsupported audio storage backend: {settings.audio_storage_backend}")
