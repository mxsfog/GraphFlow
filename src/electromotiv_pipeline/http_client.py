from __future__ import annotations

import os
import platform
import socket
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

from electromotiv_pipeline.http_utils import prefer_ipv4_addresses

WINDOWS_CURL = Path("/mnt/c/Windows/System32/curl.exe")


def get_url(url: str, *, headers: dict[str, str] | None = None, timeout_seconds: int = 30) -> bytes:
    return request_url(
        method="GET",
        url=url,
        headers=headers or {},
        body=None,
        timeout_seconds=timeout_seconds,
    )


def post_url(
    url: str,
    *,
    headers: dict[str, str],
    body: bytes,
    timeout_seconds: int = 90,
) -> bytes:
    return request_url(
        method="POST",
        url=url,
        headers=headers,
        body=body,
        timeout_seconds=timeout_seconds,
    )


def put_url(
    url: str,
    *,
    headers: dict[str, str],
    body: bytes,
    timeout_seconds: int = 90,
) -> bytes:
    return request_url(
        method="PUT",
        url=url,
        headers=headers,
        body=body,
        timeout_seconds=timeout_seconds,
    )


def request_url(
    *,
    method: str,
    url: str,
    headers: dict[str, str],
    body: bytes | None,
    timeout_seconds: int,
) -> bytes:
    if should_use_windows_curl(url, headers=headers):
        return curl_request(
            method=method,
            url=url,
            headers=headers,
            body=body,
            timeout_seconds=timeout_seconds,
        )
    return urllib_request(
        method=method,
        url=url,
        headers=headers,
        body=body,
        timeout_seconds=timeout_seconds,
    )


def should_use_windows_curl(url: str, *, headers: dict[str, str] | None = None) -> bool:
    sensitive_headers = {"authorization", "proxy-authorization"}
    if any(key.lower() in sensitive_headers for key in (headers or {})):
        return False
    backend = os.environ.get("ELECTROMOTIV_HTTP_BACKEND", "auto").strip().lower()
    if backend == "urllib":
        return False
    if backend == "curl":
        return True
    return url.startswith("https://") and is_wsl() and WINDOWS_CURL.exists()


def is_wsl() -> bool:
    release = platform.release().lower()
    if "microsoft" in release or "wsl" in release:
        return True
    version_path = Path("/proc/version")
    if version_path.exists():
        return "microsoft" in version_path.read_text(encoding="utf-8", errors="ignore").lower()
    return False


def urllib_request(
    *,
    method: str,
    url: str,
    headers: dict[str, str],
    body: bytes | None,
    timeout_seconds: int,
) -> bytes:
    socket.setdefaulttimeout(timeout_seconds)
    prefer_ipv4_addresses()
    request = urllib.request.Request(
        url,
        data=body,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {error_body}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"Сетевая ошибка при обращении к {url}: {exc}") from exc


def curl_request(
    *,
    method: str,
    url: str,
    headers: dict[str, str],
    body: bytes | None,
    timeout_seconds: int,
) -> bytes:
    command = [
        str(WINDOWS_CURL),
        "-sS",
        "-L",
        "--fail-with-body",
        "--max-time",
        str(timeout_seconds),
        "-X",
        method,
    ]
    for key, value in headers.items():
        command.extend(["-H", f"{key}: {value}"])
    if body is not None:
        command.extend(["--data-binary", "@-"])
    command.append(url)

    try:
        completed = subprocess.run(
            command,
            input=body,
            capture_output=True,
            timeout=timeout_seconds + 5,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise RuntimeError(f"HTTP curl backend failed: {exc}") from exc
    if completed.returncode != 0:
        stderr = completed.stderr.decode("utf-8", errors="replace").strip()
        stdout = completed.stdout.decode("utf-8", errors="replace").strip()
        if stderr and stdout:
            details = f"{stderr}; response body: {stdout}"
        else:
            details = stderr or stdout or f"curl exit code {completed.returncode}"
        raise RuntimeError(f"HTTP curl backend failed: {details}")
    return completed.stdout
