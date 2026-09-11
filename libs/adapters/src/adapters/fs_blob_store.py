import asyncio
import hashlib
import os
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path

from ports.interfaces import BlobStore


class FsBlobStore(BlobStore):
    """
    Blob storage port implementation that persists to the local filesystem.
    Uses asyncio.to_thread for non-blocking I/O.
    """

    def __init__(self, base_dir: str | Path):
        self.base_dir = Path(base_dir).resolve()

    def _resolve_path(self, key: str) -> Path:
        path = (self.base_dir / key.lstrip("/")).resolve()
        if not path.is_relative_to(self.base_dir):
            raise ValueError("Key resolves outside of base directory")
        return path

    def _put(self, key: str, data: bytes, content_addressing: bool) -> str:
        if content_addressing:
            digest = hashlib.sha256(data).hexdigest()
            # For content-addressable storage, append SHA-256 digest suffix to key
            key = f"{key}-{digest}"

        path = self._resolve_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)

        with tempfile.NamedTemporaryFile(
            dir=path.parent,
            prefix=f".tmp_{path.name}_",
            delete=False,
        ) as temp_file:
            temp_file.write(data)
            temp_file.flush()
            os.fsync(temp_file.fileno())
            temp_path = Path(temp_file.name)

        try:
            os.replace(temp_path, path)
        except BaseException:
            if temp_path.exists():
                temp_path.unlink()
            raise

        return key

    async def put(self, key: str, data: bytes, content_addressing: bool = False) -> str:
        return await asyncio.to_thread(self._put, key, data, content_addressing)

    def _get(self, key: str) -> bytes:
        path = self._resolve_path(key)
        if not path.is_file():
            raise KeyError(f"Blob '{key}' not found")
        try:
            return path.read_bytes()
        except (FileNotFoundError, IsADirectoryError):
            raise KeyError(f"Blob '{key}' not found")

    async def get(self, key: str) -> bytes:
        return await asyncio.to_thread(self._get, key)

    def _delete(self, key: str) -> None:
        path = self._resolve_path(key)
        if path.is_file():
            try:
                path.unlink()
            except FileNotFoundError:
                pass

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._delete, key)

    async def list(self, prefix: str) -> AsyncIterator[str]:
        def _list_keys() -> list[str]:
            clean_prefix = prefix.lstrip("/")
            if "/" in clean_prefix:
                prefix_dir_part, _, _ = clean_prefix.rpartition("/")
                start_dir = (self.base_dir / prefix_dir_part).resolve()
                if (
                    not start_dir.is_relative_to(self.base_dir)
                    or not start_dir.is_dir()
                ):
                    return []
            else:
                start_dir = self.base_dir

            if not start_dir.exists():
                return []

            keys: list[str] = []
            for root, dirs, files in os.walk(start_dir):
                pruned_dirs: list[str] = []
                for d in dirs:
                    dir_path = Path(root) / d
                    dir_rel = dir_path.relative_to(self.base_dir).as_posix()
                    if (
                        clean_prefix.startswith(f"{dir_rel}/")
                        or dir_rel.startswith(clean_prefix)
                        or dir_rel == clean_prefix
                    ):
                        pruned_dirs.append(d)
                dirs[:] = pruned_dirs

                for f in files:
                    if f.startswith(".tmp_"):
                        continue
                    full_path = Path(root) / f
                    rel_str = full_path.relative_to(self.base_dir).as_posix()
                    key_str = f"/{rel_str}" if prefix.startswith("/") else rel_str
                    if key_str.startswith(prefix):
                        keys.append(key_str)

            keys.sort()
            return keys

        keys = await asyncio.to_thread(_list_keys)
        for key in keys:
            yield key
