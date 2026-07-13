from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import tempfile
import urllib.parse
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from electromotiv_pipeline.http_client import get_url, post_url, put_url
from electromotiv_pipeline.models import RankedLink

SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"
SHEETS_API = "https://sheets.googleapis.com/v4/spreadsheets"
DEFAULT_TOKEN_URI = "https://oauth2.googleapis.com/token"
SHEET_COLUMNS = (
    "created_at",
    "run_id",
    "query",
    "rank",
    "title",
    "url",
    "source",
    "published_at",
    "llm_score",
    "reason",
    "model",
    "keywords",
)


@dataclass(frozen=True)
class ServiceAccount:
    client_email: str
    private_key: str
    token_uri: str


class GoogleSheetsClient:
    def __init__(
        self,
        *,
        spreadsheet_id: str,
        sheet_name: str,
        service_account: ServiceAccount,
    ) -> None:
        self.spreadsheet_id = spreadsheet_id
        self.sheet_name = sheet_name
        self.service_account = service_account
        self._access_token = ""

    @classmethod
    def from_service_account_file(
        cls,
        *,
        spreadsheet_id: str,
        sheet_name: str,
        service_account_file: Path,
    ) -> GoogleSheetsClient:
        return cls(
            spreadsheet_id=spreadsheet_id,
            sheet_name=sheet_name,
            service_account=load_service_account(service_account_file),
        )

    def append_ranked_links(self, links: list[RankedLink]) -> int:
        if not links:
            return 0
        self.ensure_sheet_exists()
        self.ensure_header()
        return self.append_rows([ranked_link_to_row(link) for link in links])

    def ensure_sheet_exists(self) -> None:
        payload = self.get_json(
            f"{SHEETS_API}/{quote_path(self.spreadsheet_id)}?fields=sheets.properties.title"
        )
        existing_titles = {
            str(sheet.get("properties", {}).get("title", ""))
            for sheet in payload.get("sheets", [])
            if isinstance(sheet, dict)
        }
        if self.sheet_name in existing_titles:
            return
        self.post_json(
            f"{SHEETS_API}/{quote_path(self.spreadsheet_id)}:batchUpdate",
            {
                "requests": [
                    {
                        "addSheet": {
                            "properties": {
                                "title": self.sheet_name,
                                "gridProperties": {
                                    "rowCount": 1000,
                                    "columnCount": len(SHEET_COLUMNS),
                                },
                            }
                        }
                    }
                ]
            },
        )

    def ensure_header(self) -> None:
        range_name = sheet_range(self.sheet_name, "A1:L1")
        payload = self.get_json(
            f"{SHEETS_API}/{quote_path(self.spreadsheet_id)}/values/{range_name}"
        )
        values = payload.get("values", [])
        if values and values[0] == list(SHEET_COLUMNS):
            return
        if values:
            raise RuntimeError(
                "Первая строка Google Sheets не соответствует схеме проекта; "
                "существующие данные не перезаписаны."
            )
        self.put_json(
            f"{SHEETS_API}/{quote_path(self.spreadsheet_id)}/values/{range_name}"
            "?valueInputOption=RAW",
            {"values": [list(SHEET_COLUMNS)]},
        )

    def append_rows(self, rows: list[list[object]]) -> int:
        if not rows:
            return 0
        range_name = sheet_range(self.sheet_name, "A:L")
        self.post_json(
            f"{SHEETS_API}/{quote_path(self.spreadsheet_id)}/values/{range_name}:append"
            "?valueInputOption=RAW&insertDataOption=INSERT_ROWS",
            {"values": rows},
        )
        return len(rows)

    def get_json(self, url: str) -> dict[str, object]:
        return decode_json_object(
            get_url(url, headers=self.auth_headers(), timeout_seconds=30),
            context="Google Sheets GET",
        )

    def post_json(self, url: str, payload: dict[str, object]) -> dict[str, object]:
        return decode_json_object(
            post_url(
                url,
                headers={**self.auth_headers(), "Content-Type": "application/json"},
                body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                timeout_seconds=60,
            ),
            context="Google Sheets POST",
        )

    def put_json(self, url: str, payload: dict[str, object]) -> dict[str, object]:
        return decode_json_object(
            put_url(
                url,
                headers={**self.auth_headers(), "Content-Type": "application/json"},
                body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                timeout_seconds=60,
            ),
            context="Google Sheets PUT",
        )

    def auth_headers(self) -> dict[str, str]:
        if not self._access_token:
            self._access_token = request_access_token(self.service_account)
        return {"Authorization": f"Bearer {self._access_token}"}


def load_service_account(path: Path) -> ServiceAccount:
    try:
        raw_payload = path.read_bytes()
    except OSError as exc:
        raise RuntimeError(f"Не удалось прочитать service account: {path}") from exc
    try:
        payload = decode_json_object(raw_payload, context=f"service account {path}")
    except RuntimeError as exc:
        raise RuntimeError(f"Некорректный JSON service account: {path}") from exc

    client_email = str(payload.get("client_email") or "").strip()
    private_key = str(payload.get("private_key") or "").strip()
    token_uri = str(payload.get("token_uri") or DEFAULT_TOKEN_URI).strip()
    if not client_email or not private_key:
        raise RuntimeError("Service account JSON должен содержать client_email и private_key.")
    return ServiceAccount(
        client_email=client_email,
        private_key=private_key,
        token_uri=token_uri,
    )


def request_access_token(service_account: ServiceAccount) -> str:
    assertion = build_jwt_assertion(service_account)
    body = urllib.parse.urlencode(
        {
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": assertion,
        }
    ).encode("utf-8")
    payload = decode_json_object(
        post_url(
            service_account.token_uri,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            body=body,
            timeout_seconds=60,
        ),
        context="Google OAuth",
    )
    access_token = str(payload.get("access_token") or "").strip()
    if not access_token:
        raise RuntimeError("Google OAuth не вернул access_token.")
    return access_token


def build_jwt_assertion(service_account: ServiceAccount) -> str:
    now = datetime.now(UTC)
    header = {"alg": "RS256", "typ": "JWT"}
    claims = {
        "iss": service_account.client_email,
        "scope": SHEETS_SCOPE,
        "aud": service_account.token_uri,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=55)).timestamp()),
    }
    signing_input = ".".join(
        [
            base64url_json(header),
            base64url_json(claims),
        ]
    )
    signature = sign_rs256(signing_input.encode("ascii"), service_account.private_key)
    return f"{signing_input}.{base64url_bytes(signature)}"


def sign_rs256(payload: bytes, private_key: str) -> bytes:
    openssl = shutil.which("openssl")
    if not openssl:
        raise RuntimeError("Не найдена команда openssl, необходимая для Google OAuth.")
    temp_dir = Path(os.environ.get("ELECTROMOTIV_TEMP_DIR", ".runtime/tmp"))
    temp_dir.mkdir(parents=True, exist_ok=True)
    fd, path = tempfile.mkstemp(
        prefix="electromotiv-google-sa-",
        suffix=".pem",
        dir=temp_dir,
    )
    try:
        os.write(fd, private_key.encode("utf-8"))
        os.close(fd)
        fd = -1
        os.chmod(path, 0o600)
        try:
            completed = subprocess.run(
                [openssl, "dgst", "-sha256", "-sign", path],
                input=payload,
                capture_output=True,
                check=False,
                timeout=20,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(f"Не удалось запустить openssl: {exc}") from exc
        if completed.returncode != 0:
            details = completed.stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"Не удалось подписать JWT для Google OAuth: {details}")
        return completed.stdout
    finally:
        if fd != -1:
            os.close(fd)
        with suppress(FileNotFoundError):
            os.unlink(path)


def ranked_link_to_row(link: RankedLink) -> list[object]:
    return [
        link.created_at,
        link.run_id,
        link.query,
        link.rank,
        link.title,
        link.url,
        link.source or link.source_name,
        link.published_at,
        link.llm_score,
        link.reason,
        link.model,
        ", ".join(link.keywords),
    ]


def sheet_range(sheet_name: str, cells: str) -> str:
    escaped_sheet = sheet_name.replace("'", "''")
    return quote_path(f"'{escaped_sheet}'!{cells}")


def quote_path(value: str) -> str:
    return urllib.parse.quote(value, safe="")


def base64url_json(payload: dict[str, object]) -> str:
    return base64url_bytes(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    )


def base64url_bytes(payload: bytes) -> str:
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def decode_json_object(payload: bytes, *, context: str) -> dict[str, object]:
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{context} вернул невалидный JSON.") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"{context} должен вернуть JSON-объект.")
    return value
