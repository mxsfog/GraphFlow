from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from electromotiv_pipeline.config import DEFAULT_MODEL, build_config
from electromotiv_pipeline.google_news import fetch_news
from electromotiv_pipeline.models import Article, RankedLink
from electromotiv_pipeline.orientdb import OrientDBClient
from electromotiv_pipeline.pipeline import (
    run_pipeline,
    save_ranked_links_to_google_sheets,
    write_output,
)

COMMANDS = {
    "run": "command_run",
    "fetch-news": "command_fetch_news",
    "check-orientdb": "command_check_orientdb",
    "ensure-schema": "command_ensure_schema",
    "dashboard": "command_dashboard",
    "graph-api": "command_graph_api",
}


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        globals()[COMMANDS[args.command]](args)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="electromotiv-news",
        description="Python-пайплайн: Google News RSS -> LLM OpenRouter -> OrientDB.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Запустить полный пайплайн.")
    add_common_config_args(run_parser)
    run_parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help="Идентификатор модели OpenRouter.",
    )
    run_parser.add_argument(
        "--no-save",
        action="store_true",
        help="Не сохранять результат в OrientDB.",
    )
    run_parser.add_argument(
        "--ensure-schema",
        action="store_true",
        help="Перед записью выполнить orientdb/schema.sql.",
    )
    run_parser.add_argument(
        "--mock-llm",
        action="store_true",
        help="Локальная проверка без OpenRouter. Для демонстрации LLM не использовать.",
    )
    sheets_group = run_parser.add_mutually_exclusive_group()
    sheets_group.add_argument(
        "--save-sheets",
        action="store_true",
        help="Записать результат в Google Sheets независимо от GOOGLE_SHEETS_ENABLED.",
    )
    sheets_group.add_argument(
        "--no-sheets",
        action="store_true",
        help="Отключить запись в Google Sheets для текущего запуска.",
    )

    fetch_parser = subparsers.add_parser(
        "fetch-news",
        help="Проверить получение новостей из Google News RSS.",
    )
    add_common_config_args(fetch_parser, include_orientdb=False)

    check_parser = subparsers.add_parser(
        "check-orientdb",
        help="Проверить счетчики классов OrientDB.",
    )
    add_common_config_args(check_parser, include_query=False)

    schema_parser = subparsers.add_parser("ensure-schema", help="Выполнить orientdb/schema.sql.")
    add_common_config_args(schema_parser, include_query=False)
    schema_parser.add_argument("--schema", default="orientdb/schema.sql", help="Путь к SQL-схеме.")

    dashboard_parser = subparsers.add_parser("dashboard", help="Запустить простой HTML dashboard.")
    add_common_config_args(dashboard_parser, include_query=False)
    dashboard_parser.add_argument("--host", default="127.0.0.1", help="Адрес панели просмотра.")
    dashboard_parser.add_argument("--port", type=int, default=8088, help="Порт панели просмотра.")

    graph_api_parser = subparsers.add_parser("graph-api", help="Запустить API графов.")
    add_common_config_args(graph_api_parser, include_query=False)
    graph_api_parser.add_argument("--host", default="127.0.0.1", help="Адрес API графов.")
    graph_api_parser.add_argument("--port", type=int, default=8090, help="Порт API графов.")

    return parser


def add_common_config_args(
    parser: argparse.ArgumentParser,
    *,
    include_query: bool = True,
    include_orientdb: bool = True,
) -> None:
    parser.add_argument("--env-file", default=".env", help="Путь к локальному .env.")
    parser.add_argument(
        "--output",
        default="outputs/python_news_links.json",
        help="JSON-результат.",
    )
    if include_query:
        parser.add_argument("--query", default=None, help="Поисковый запрос.")
        parser.add_argument(
            "--max-records",
            type=int,
            default=None,
            help="Сколько RSS-кандидатов взять.",
        )
    if include_orientdb:
        parser.add_argument("--orientdb-url", default=None, help="URL OrientDB HTTP API.")
        parser.add_argument("--database", default=None, help="База OrientDB.")


def command_run(args: argparse.Namespace) -> None:
    if args.mock_llm:
        config = build_config_from_args(args, require_openrouter=False)
        articles = fetch_news(config.query, config.max_records)
        ranked_links = mock_rank_articles(config.query, articles)
        write_output(config.output_path, ranked_links)
        saved_to_sheets = save_ranked_links_to_google_sheets(config, ranked_links)
        json_print(
            {
                "ranked": len(ranked_links),
                "saved_to_google_sheets": bool(saved_to_sheets),
                "output": str(config.output_path),
            }
        )
        return

    config = build_config_from_args(args, require_openrouter=True)
    ranked_links = run_pipeline(
        config=config,
        save_to_orientdb=not args.no_save,
        ensure_schema=args.ensure_schema,
    )
    json_print(
        {
            "ranked": len(ranked_links),
            "saved_to_orientdb": not args.no_save,
            "saved_to_google_sheets": config.google_sheets.enabled,
            "model": config.openrouter_model,
            "output": str(config.output_path),
        }
    )


def command_fetch_news(args: argparse.Namespace) -> None:
    config = build_config_from_args(args, require_openrouter=False)
    articles = fetch_news(config.query, config.max_records)
    json_print(
        [
            {
                "index": article.index,
                "source_name": article.source_name,
                "title": article.title,
                "url": article.url,
                "published_at": article.published_at,
            }
            for article in articles
        ],
        indent=2,
    )


def command_check_orientdb(args: argparse.Namespace) -> None:
    client = client_from_args(args)
    json_print(
        {
            name: client.count_class(name)
            for name in (
                "SearchRun",
                "NewsLink",
                "Source",
                "Topic",
                "ModelRun",
            )
        }
    )


def command_ensure_schema(args: argparse.Namespace) -> None:
    client_from_args(args).ensure_schema(Path(args.schema))
    json_print({"schema": args.schema, "status": "ok"})


def command_dashboard(args: argparse.Namespace) -> None:
    from electromotiv_pipeline.dashboard import run_dashboard

    run_dashboard(client=client_from_args(args), host=args.host, port=args.port)


def command_graph_api(args: argparse.Namespace) -> None:
    from electromotiv_pipeline.graph_api import run_graph_api

    run_graph_api(client=client_from_args(args), host=args.host, port=args.port)


def build_config_from_args(
    args: argparse.Namespace,
    *,
    require_openrouter: bool,
):
    return build_config(
        env_file=Path(args.env_file),
        query=getattr(args, "query", None),
        max_records=getattr(args, "max_records", None),
        model=getattr(args, "model", None),
        orientdb_url=getattr(args, "orientdb_url", None),
        database=getattr(args, "database", None),
        output_path=Path(args.output) if getattr(args, "output", None) else None,
        google_sheets_enabled=google_sheets_enabled_from_args(args),
        require_openrouter=require_openrouter,
    )


def google_sheets_enabled_from_args(args: argparse.Namespace) -> bool | None:
    if getattr(args, "save_sheets", False):
        return True
    if getattr(args, "no_sheets", False):
        return False
    return None


def client_from_args(args: argparse.Namespace) -> OrientDBClient:
    config = build_config_from_args(args, require_openrouter=False)
    return OrientDBClient(
        base_url=config.orientdb_url,
        database=config.orientdb_database,
        auth_header=config.orientdb_auth_header,
    )


def json_print(payload: object, *, indent: int | None = None) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=indent))


def mock_rank_articles(query: str, articles: list[Article]) -> list[RankedLink]:
    from datetime import UTC, datetime
    from uuid import uuid4

    created_at = datetime.now(UTC).isoformat(timespec="seconds")
    run_id = str(uuid4())
    ranked: list[RankedLink] = []
    for index, article in enumerate(articles, start=1):
        ranked.append(
            RankedLink(
                query=query,
                run_id=run_id,
                rank=index,
                article_index=article.index,
                title=article.title,
                url=article.url,
                source=article.source,
                source_name=article.source_name,
                domain=article.domain,
                published_at=article.published_at,
                llm_score=0.0,
                reason="Локальный режим без LLM: оценка релевантности не выполнялась.",
                created_at=created_at,
                model="mock",
                keywords=(),
                llm_raw_response='{"mock": true}',
            )
        )
    return ranked


if __name__ == "__main__":
    main()
