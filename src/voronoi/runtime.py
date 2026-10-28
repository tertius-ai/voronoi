"""The Noether release shared by the Python application and Rust worker."""

from __future__ import annotations

import json
import os
import signal
import subprocess
from functools import lru_cache
from pathlib import Path

import noether

NOETHER_VERSION = "0.3.2"
ENGINE_RUNTIME_SCHEMA = "voronoi/census-engine-runtime@1"
ENGINE_VERSION_TIMEOUT_SECONDS = 10


@lru_cache(maxsize=1)
def _compiled_noether_version() -> str:
    # Older projections derived __version__ from installed distribution metadata,
    # which can mask an old extension when PYTHONPATH points at another checkout.
    return noether.capabilities().version


def require_noether_version() -> None:
    """Reject stale editable installations as well as unsupported releases."""

    if (
        noether.__version__ != NOETHER_VERSION
        or _compiled_noether_version() != NOETHER_VERSION
    ):
        raise RuntimeError(
            f"Voronoi requires Noether {NOETHER_VERSION}; loaded "
            f"projection {noether.__version__} with compiled engine "
            f"{_compiled_noether_version()} from {noether.__file__}. "
            "Run `make sync` with the sibling Noether v0.3.2 checkout."
        )


def census_engine_runtime(executable: Path) -> dict[str, str]:
    """Check a worker once per binary revision, including explicit overrides."""

    require_noether_version()
    path = executable.resolve()
    stat = path.stat()
    return dict(
        _census_engine_runtime(path, stat.st_ino, stat.st_size, stat.st_mtime_ns)
    )


@lru_cache(maxsize=8)
def _census_engine_runtime(
    executable: Path, inode: int, size: int, mtime_ns: int
) -> tuple[tuple[str, str], ...]:
    # File identity is part of the cache key so rebuilding or replacing a worker
    # cannot reuse the verdict for an older binary at the same path.
    try:
        process = subprocess.Popen(
            [str(executable), "--version"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        try:
            stdout, stderr = process.communicate(timeout=ENGINE_VERSION_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.communicate()
            raise
        if process.returncode:
            raise subprocess.CalledProcessError(
                process.returncode, executable, stdout, stderr
            )
        payload = json.loads(stdout)
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        raise RuntimeError(
            f"Cannot identify census worker {executable}; run `make engine` "
            "to rebuild it against Noether 0.3.2."
        ) from error
    if (
        not isinstance(payload, dict)
        or payload.get("type") != ENGINE_RUNTIME_SCHEMA
        or payload.get("noether_version") != NOETHER_VERSION
    ):
        raise RuntimeError(
            f"Census worker {executable} does not report Noether {NOETHER_VERSION}; "
            "run `make engine` or select a matching VORONOI_CENSUS_ENGINE."
        )
    return tuple((key, str(value)) for key, value in payload.items())
