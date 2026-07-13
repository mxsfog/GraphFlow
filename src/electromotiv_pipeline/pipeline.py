from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from electromotiv_pipeline.config import DEFAULT_SCHEMA_PATH, PipelineConfig
from electromotiv_pipeline.google_news import build_news_sources, fetch_news
from electromotiv_pipeline.google_sheets import GoogleSheetsClient
from electromotiv_pipeline.models import RankedLink
from electromotiv_pipeline.openrouter import rank_articles_with_openrouter
from electromotiv_pipeline.orientdb import OrientDBClient


def run_pipeline(
    *,
    config: PipelineConfig,
    save_to_orientdb: bool,
    ensure_schema: bool,
) -> list[RankedLink]:
    run_id = str(uuid4())
    started_at = datetime.now(UTC).isoformat(timespec="seconds")
    articles = fetch_news(config.query, config.max_records)
    if not articles:
        raise RuntimeError("Ни один новостной источник не вернул кандидатов.")
    ranked_links = rank_articles_with_openrouter(
        api_key=config.openrouter_api_key,
        model=config.openrouter_model,
        query=config.query,
        run_id=run_id,
        articles=articles,
    )

    write_output(config.output_path, ranked_links)

    client: OrientDBClient | None = None
    if save_to_orientdb:
        client = OrientDBClient(
            base_url=config.orientdb_url,
            database=config.orientdb_database,
            auth_header=config.orientdb_auth_header,
        )
        if ensure_schema:
            client.ensure_schema(DEFAULT_SCHEMA_PATH)
        client.save_ranked_links(
            query=config.query,
            run_id=run_id,
            model=config.openrouter_model,
            links=ranked_links,
            sources_count=len(build_news_sources(config.query)),
            candidates_count=len(articles),
            started_at=started_at,
        )

    try:
        sheets_saved_count = save_ranked_links_to_google_sheets(config, ranked_links)
    except RuntimeError as exc:
        if client is not None:
            client.mark_google_sheets_result(run_id=run_id, saved_count=0, error=str(exc))
        raise RuntimeError(
            f"Результат сохранен локально, но экспорт в Google Sheets завершился ошибкой: {exc}"
        ) from exc
    if client is not None and config.google_sheets.enabled:
        client.mark_google_sheets_result(run_id=run_id, saved_count=sheets_saved_count)

    return ranked_links


def save_ranked_links_to_google_sheets(
    config: PipelineConfig,
    ranked_links: list[RankedLink],
) -> int:
    if not config.google_sheets.enabled:
        return 0
    if config.google_sheets.service_account_file is None:
        raise RuntimeError("Не задан файл service account для записи в Google Sheets.")
    sheets_client = GoogleSheetsClient.from_service_account_file(
        spreadsheet_id=config.google_sheets.spreadsheet_id,
        sheet_name=config.google_sheets.sheet_name,
        service_account_file=config.google_sheets.service_account_file,
    )
    return sheets_client.append_ranked_links(ranked_links)


def write_output(path: Path, ranked_links: list[RankedLink]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [item.to_dict() for item in ranked_links]
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
