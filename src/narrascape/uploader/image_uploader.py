"""Image uploader for reference image management.

Handles uploading local images to cloud storage for use as reference images
in Seedream (filePath) and Seedance (first_frame/last_frame) workflows.

Supports multiple backends:
- Volcengine (即梦) native upload
- Generic HTTP upload
- Base64 inline (fallback, no upload needed)
"""

from __future__ import annotations

import base64
import json
import logging
import mimetypes
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger("narrascape.uploader")


class ImageUploader:
    """Upload images to cloud storage and return accessible URLs.

    Usage:
        uploader = ImageUploader()
        url = uploader.upload("/path/to/image.png")
        # url can be used as filePath in Seedream/Seedance API
    """

    def __init__(self, backend: str = "base64"):
        """
        Args:
            backend: Upload backend. "base64" (inline, no upload),
                     "volcengine" (即梦 native), or "http" (generic POST).
        """
        self.backend = backend
        self._cache: dict[str, str] = {}  # local_path -> url

    def upload(self, local_path: str | Path, force: bool = False) -> str:
        """Upload a local image and return a URL accessible by the API.

        Args:
            local_path: Path to the image file.
            force: Re-upload even if cached.

        Returns:
            URL string or base64 data URI that can be used as filePath.
        """
        p = Path(local_path)
        if not p.exists():
            raise FileNotFoundError(f"Reference image not found: {p}")

        cache_key = str(p.resolve())
        if not force and cache_key in self._cache:
            return self._cache[cache_key]

        if self.backend == "base64":
            url = self._to_base64(p)
        elif self.backend == "volcengine":
            url = self._upload_to_volcengine(p)
        elif self.backend == "http":
            url = self._upload_http(p)
        else:
            raise ValueError(f"Unknown upload backend: {self.backend}")

        url = self._validate_upload_url(url)
        self._cache[cache_key] = url
        logger.info(f"Uploaded {p.name} -> {url[:60]}...")
        return url

    def _validate_upload_url(self, url: str) -> str:
        """Allow only API-safe reference image URL schemes."""
        value = str(url or "").strip()
        if not value:
            raise ValueError("Upload backend returned an empty URL")
        if value.startswith("data:"):
            if not value.startswith("data:image/"):
                raise ValueError("Only data:image/* upload URLs are allowed")
            if ";base64," not in value[:128]:
                raise ValueError("Data image upload URL must be base64 encoded")
            return value
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError(f"Unsupported upload URL scheme: {value[:80]}")
        return value

    def upload_multiple(self, paths: list[str | Path]) -> list[str]:
        """Upload multiple images and return their URLs."""
        return [self.upload(p) for p in paths]

    def _to_base64(self, path: Path) -> str:
        """Convert image to base64 data URI (no network upload).

        Per Volcengine docs: request body must be < 64 MB.
        Large files should NOT use base64 (encoding expands size ~33%).
        """
        file_size = path.stat().st_size
        if file_size > 1_000_000:  # > 1 MB
            logger.warning(
                f"Reference image {path.name} is {file_size / 1024 / 1024:.1f}MB. "
                f"Base64 encoding will expand it to ~{file_size * 1.33 / 1024 / 1024:.1f}MB. "
                f"Consider using 'http' backend with NARRASCAPE_UPLOAD_ENDPOINT to avoid large request bodies."
            )
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        ext = path.suffix.lower().lstrip(".")
        mime = {
            "png": "image/png",
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "webp": "image/webp",
            "bmp": "image/bmp",
        }.get(ext, "image/png")
        return f"data:{mime};base64,{b64}"

    def _upload_to_volcengine(self, path: Path) -> str:
        """Upload to Volcengine (即梦) platform.

        Note: This is a placeholder. The actual implementation requires
        the Volcengine upload endpoint, which is not publicly documented.
        The jimeng-mcp project uses an internal upload flow.

        For now, falls back to base64 inline.
        """
        logger.warning(
            "Volcengine native upload not yet implemented. "
            "Using base64 inline fallback. "
            "To use Volcengine upload, set backend='base64' and ensure "
            "the API supports base64 image payloads."
        )
        return self._to_base64(path)

    def _upload_http(self, path: Path) -> str:
        """Upload via generic HTTP POST to a configured endpoint.

        Expects the upload endpoint to return JSON with a 'url' field.
        """
        import os

        endpoint = os.environ.get("NARRASCAPE_UPLOAD_ENDPOINT", "")
        if not endpoint:
            logger.warning("NARRASCAPE_UPLOAD_ENDPOINT not set. " "Using base64 inline fallback.")
            return self._to_base64(path)

        # Prepare multipart form data
        boundary = "----NarrascapeBoundary"
        ext = path.suffix.lower().lstrip(".")
        mime = mimetypes.guess_type(str(path))[0] or "image/png"

        with open(path, "rb") as f:
            file_data = f.read()

        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
            f"Content-Type: {mime}\r\n\r\n"
        ).encode()
        body += file_data
        body += f"\r\n--{boundary}--\r\n".encode()

        req = urllib.request.Request(
            endpoint,
            data=body,
            method="POST",
        )
        req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")

        try:
            resp = urllib.request.urlopen(req, timeout=60)
            data = json.loads(resp.read().decode())
            url = data.get("url") or data.get("data", {}).get("url")
            if not url:
                raise ValueError(f"Upload response missing 'url': {data}")
            return str(url)
        except Exception as e:
            logger.error(f"HTTP upload failed: {e}. Fallback to base64.")
            return self._to_base64(path)

    def get_cache(self) -> dict[str, str]:
        """Return current upload cache (local_path -> url)."""
        return self._cache.copy()

    def clear_cache(self) -> None:
        """Clear upload cache."""
        self._cache.clear()
