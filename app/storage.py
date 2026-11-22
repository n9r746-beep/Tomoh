"""
Stateless Object Storage Abstraction for Serverless (Vercel + Supabase Storage) & Local Dev.
Zero extra dependencies — uses Python stdlib urllib.request for Supabase Storage REST API.
Never exposes SUPABASE_SERVICE_ROLE_KEY to the frontend.
"""

from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path
from typing import Optional


class StorageBackend:
    def upload_bytes(self, bucket: str, object_path: str, data: bytes, content_type: str) -> str:
        raise NotImplementedError

    def download_bytes(self, bucket: str, object_path: str) -> bytes:
        raise NotImplementedError

    def create_signed_url(self, bucket: str, object_path: str, expires_in_sec: int = 300) -> Optional[str]:
        return None


class LocalStorageBackend(StorageBackend):
    def __init__(self, root_dir: Path):
        self.root_dir = Path(root_dir).resolve()
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def _resolve(self, bucket: str, object_path: str) -> Path:
        dest = (self.root_dir / bucket / object_path).resolve()
        dest.relative_to(self.root_dir)
        dest.parent.mkdir(parents=True, exist_ok=True)
        return dest

    def upload_bytes(self, bucket: str, object_path: str, data: bytes, content_type: str) -> str:
        dest = self._resolve(bucket, object_path)
        dest.write_bytes(data)
        try:
            os.chmod(dest, 0o600)
        except OSError:
            pass
        return str(dest)

    def download_bytes(self, bucket: str, object_path: str) -> bytes:
        return self._resolve(bucket, object_path).read_bytes()


class SupabaseStorageBackend(StorageBackend):
    """Server-side private Supabase Storage client using service_role key from environment."""

    def __init__(self, supabase_url: str, service_role_key: str):
        if not supabase_url or not service_role_key:
            raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required for SupabaseStorageBackend.")
        self.base_url = supabase_url.rstrip("/")
        self.service_role_key = service_role_key

    def _headers(self, content_type: Optional[str] = None) -> dict:
        h = {
            "Authorization": f"Bearer {self.service_role_key}",
            "apikey": self.service_role_key,
        }
        if content_type:
            h["Content-Type"] = content_type
        return h

    def upload_bytes(self, bucket: str, object_path: str, data: bytes, content_type: str) -> str:
        url = f"{self.base_url}/storage/v1/object/{bucket}/{object_path.lstrip('/')}"
        headers = self._headers(content_type)
        headers["x-upsert"] = "true"
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=30) as resp:
            if resp.status not in (200, 201):
                raise RuntimeError(f"Supabase upload failed ({resp.status})")
        return f"supabase://{bucket}/{object_path.lstrip('/')}"

    def download_bytes(self, bucket: str, object_path: str) -> bytes:
        url = f"{self.base_url}/storage/v1/object/{bucket}/{object_path.lstrip('/')}"
        req = urllib.request.Request(url, headers=self._headers(), method="GET")
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read()

    def create_signed_url(self, bucket: str, object_path: str, expires_in_sec: int = 300) -> str:
        url = f"{self.base_url}/storage/v1/object/sign/{bucket}/{object_path.lstrip('/')}"
        body = json.dumps({"expiresIn": expires_in_sec}).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers=self._headers("application/json"), method="POST")
        with urllib.request.urlopen(req, timeout=15) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        signed = payload.get("signedURL") or payload.get("signedUrl")
        if not signed:
            raise RuntimeError("Supabase sign response missing signedURL")
        return f"{self.base_url}/storage/v1{signed}"
