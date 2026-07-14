#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Reproducible archive provenance hashing and Git metadata helpers."""

import hashlib
import json
import os
import subprocess
from typing import Dict, Iterable, Optional

def _canonical_json_hash(value: object, length: int = 16) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:max(8, int(length))]

def _patch_content_hash(patch_paths: Iterable[Optional[str]], length: int = 16) -> str:
    digest = hashlib.sha256()
    found = False
    normalized = sorted({os.path.abspath(path) for path in patch_paths if path and os.path.isfile(path)})
    for path in normalized:
        found = True
        digest.update(os.path.basename(path).encode("utf-8", errors="replace"))
        digest.update(b"\0")
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()[:max(8, int(length))] if found else "none"

def _current_git_commit(project_root: Optional[str] = None) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=project_root or os.getcwd(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    commit = result.stdout.strip()
    return commit if result.returncode == 0 and commit else "unknown"

def build_archive_metadata(
    runtime_config: Dict[str, object],
    prediction_seed: Optional[int] = None,
    patch_paths: Iterable[Optional[str]] = (),
    git_commit: Optional[str] = None,
) -> Dict[str, str]:
    return {
        "archive_schema_version": "2",
        "runtime_config_hash": _canonical_json_hash(runtime_config),
        "patch_config_hash": _patch_content_hash(patch_paths),
        "prediction_seed": str(prediction_seed) if prediction_seed is not None else "none",
        "git_commit": str(git_commit or _current_git_commit()),
    }
