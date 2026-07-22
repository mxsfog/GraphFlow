from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_QUERY = "(oil OR crude OR Brent OR WTI) price spike market futures week"
DEFAULT_MODEL = "deepseek/deepseek-v4-flash"
DEFAULT_ORIENTDB_URL = "http://127.0.0.1:2480"
DEFAULT_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "orientdb" / "schema.sql"
MAX_NEWS_RECORDS = 100


@dataclass(frozen=True)
class GoogleSheetsConfig:
    enabled: bool
    spreadsheet_id: str
    sheet_name: str
    service_account_file: Path | None


@dataclass(frozen=True)
class PipelineConfig:
    query: str
    max_records: int
    openrouter_api_key: str
    openrouter_model: str
    orientdb_url: str
    orientdb_database: str
    orientdb_auth_header: str
    output_path: Path
    google_sheets: GoogleSheetsConfig


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Не задана обязательная переменная окружения {name}.")
    return value


def get_int_env(name: str, default: int) -> int:
    raw_value = os.environ.get(name)
    if raw_value is None or raw_value == "":
        return default
    try:
        return int(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"Переменная {name} должна быть целым числом.") from exc


def get_bool_env(name: str, default: bool) -> bool:
    raw_value = os.environ.get(name)
    if raw_value is None or raw_value == "":
        return default
    normalized = raw_value.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    raise RuntimeError(f"Переменная {name} должна быть boolean-значением.")


def build_config(
    *,
    env_file: Path,
    query: str | None,
    max_records: int | None,
    model: str | None,
    orientdb_url: str | None,
    database: str | None,
    output_path: Path | None,
    google_sheets_enabled: bool | None = None,
    require_openrouter: bool = True,
    require_orientdb: bool = True,
) -> PipelineConfig:
    load_dotenv(env_file)

    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if require_openrouter and not api_key:
        raise RuntimeError("Не задан OPENROUTER_API_KEY. Без него LLM-оценка невозможна.")

    auth_header = os.environ.get("ORIENTDB_AUTH_HEADER", "").strip()
    if not auth_header and require_orientdb:
        password = os.environ.get("ORIENTDB_ROOT_PASSWORD", "").strip()
        if not password:
            raise RuntimeError(
                "Не задан ORIENTDB_AUTH_HEADER или ORIENTDB_ROOT_PASSWORD для доступа к OrientDB."
            )
        import base64

        token = base64.b64encode(f"root:{password}".encode()).decode("ascii")
        auth_header = f"Basic {token}"

    resolved_max_records = (
        max_records if max_records is not None else get_int_env("SEARCH_MAX_RECORDS", 5)
    )
    if not 1 <= resolved_max_records <= MAX_NEWS_RECORDS:
        raise RuntimeError(f"Количество RSS-кандидатов должно быть от 1 до {MAX_NEWS_RECORDS}.")

    resolved_output = output_path or Path("outputs/python_news_links.json")
    sheets_enabled = (
        google_sheets_enabled
        if google_sheets_enabled is not None
        else get_bool_env("GOOGLE_SHEETS_ENABLED", False)
    )
    spreadsheet_id = os.environ.get("GOOGLE_SHEETS_SPREADSHEET_ID", "").strip()
    sheet_name = os.environ.get("GOOGLE_SHEETS_SHEET_NAME", "news_links").strip()
    service_account_file_raw = (
        os.environ.get("GOOGLE_SHEETS_SERVICE_ACCOUNT_FILE")
        or os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE")
        or ""
    ).strip()
    service_account_file = Path(service_account_file_raw) if service_account_file_raw else None
    if sheets_enabled:
        if not spreadsheet_id:
            raise RuntimeError("Не задан GOOGLE_SHEETS_SPREADSHEET_ID для записи в Google Sheets.")
        if not service_account_file:
            raise RuntimeError(
                "Не задан GOOGLE_SHEETS_SERVICE_ACCOUNT_FILE для записи в Google Sheets."
            )
        if not service_account_file.exists():
            raise RuntimeError(f"Файл service account не найден: {service_account_file}")

    return PipelineConfig(
        query=query or os.environ.get("SEARCH_QUERY", DEFAULT_QUERY),
        max_records=resolved_max_records,
        openrouter_api_key=api_key,
        openrouter_model=model or os.environ.get("OPENROUTER_MODEL", DEFAULT_MODEL),
        orientdb_url=(orientdb_url or os.environ.get("ORIENTDB_URL", DEFAULT_ORIENTDB_URL)).rstrip(
            "/"
        ),
        orientdb_database=database or os.environ.get("ORIENTDB_DATABASE", "news"),
        orientdb_auth_header=auth_header,
        output_path=resolved_output,
        google_sheets=GoogleSheetsConfig(
            enabled=sheets_enabled,
            spreadsheet_id=spreadsheet_id,
            sheet_name=sheet_name or "news_links",
            service_account_file=service_account_file,
        ),
    )
