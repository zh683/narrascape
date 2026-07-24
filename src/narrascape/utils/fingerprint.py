"""Request-level content-addressed fingerprints for paid generation stages.

A request fingerprint captures *everything that changes the provider's
output* for a paid generation call: provider, model, prompt, negative
prompt, shaping parameters (size / resolution / duration / voice / speed
...), and the content of reference inputs. Stage skip logic must require
both "output file exists" AND "stored fingerprint == current fingerprint";
a fingerprint mismatch means the on-disk artifact was produced by a
different request and must be regenerated.

Fingerprints are persisted by each stage next to its existing resume
state (e.g. ``image_gen_state.json["fingerprints"]``) or, for video, in
the paid task ledger (``video_tasks.json`` record field
``request_fingerprint``). Legacy state files without fingerprints simply
fail the match and are regenerated once — a safe, one-time upgrade cost.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

_HASH_LEN = 16
_CHUNK_SIZE = 1024 * 1024


def hash_file_content(path: Path) -> str:
    """Return a truncated sha256 of the file's bytes (chunked read)."""
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()[:_HASH_LEN]


def hash_reference(value: str) -> str:
    """Hash a reference input by content whenever possible.

    - Existing local file path  -> hash of the file bytes (content moves
      with the file even if the path stays the same).
    - Anything else (http(s) URL, data URI) -> hash of the string itself.
      A data URI embeds the bytes, so hashing the string *is* a content
      hash; for remote URLs only the locator is observable locally.
    """
    candidate = Path(value)
    if not value.startswith(("http://", "https://", "data:")):
        try:
            if candidate.is_file():
                return hash_file_content(candidate)
        except OSError:
            pass
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:_HASH_LEN]


def request_fingerprint(
    *,
    provider: str,
    model: str,
    prompt: str,
    negative_prompt: str = "",
    params: Mapping[str, Any] | None = None,
    reference_hashes: Sequence[str] | None = None,
) -> str:
    """Compute a deterministic fingerprint for one paid generation request.

    The fingerprint is a truncated sha256 of a canonical JSON document
    (sorted keys), so it is stable across processes and machines for the
    same logical request. Any change to a hashed component — including
    reference *content* — yields a different fingerprint; changes to
    unrelated metadata (timestamps, state bookkeeping) do not.
    """
    document = {
        "provider": provider,
        "model": model,
        "prompt": prompt,
        "negative_prompt": negative_prompt,
        "params": dict(params) if params else {},
        "reference_hashes": list(reference_hashes) if reference_hashes else [],
    }
    payload = json.dumps(document, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:_HASH_LEN]
