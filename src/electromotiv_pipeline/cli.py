from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import Counter
from pathlib import Path

from electromotiv_pipeline.config import DEFAULT_SCHEMA_PATH, build_config
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
    "decompose-document": "command_decompose_document",
    "import-technology-maps": "command_import_technology_maps",
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
        default=None,
        help="Идентификатор модели OpenRouter. По умолчанию используется OPENROUTER_MODEL.",
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
    schema_parser.add_argument(
        "--schema",
        default=str(DEFAULT_SCHEMA_PATH),
        help="Путь к SQL-схеме.",
    )

    dashboard_parser = subparsers.add_parser("dashboard", help="Запустить простой HTML dashboard.")
    add_common_config_args(dashboard_parser, include_query=False)
    dashboard_parser.add_argument("--host", default="127.0.0.1", help="Адрес панели просмотра.")
    dashboard_parser.add_argument("--port", type=int, default=8088, help="Порт панели просмотра.")
    dashboard_parser.add_argument("--auth-user", default=None, help="Логин dashboard.")

    graph_api_parser = subparsers.add_parser("graph-api", help="Запустить API графов.")
    add_common_config_args(graph_api_parser, include_query=False)
    graph_api_parser.add_argument("--host", default="127.0.0.1", help="Адрес API графов.")
    graph_api_parser.add_argument("--port", type=int, default=8090, help="Порт API графов.")
    graph_api_parser.add_argument("--auth-user", default=None, help="Логин Graph API.")

    document_parser = subparsers.add_parser(
        "decompose-document",
        help="Декомпозировать текстовый документ через LLM и сохранить граф в OrientDB.",
    )
    add_common_config_args(document_parser, include_query=False)
    document_parser.add_argument("--file", required=True, help="Путь к текстовому документу.")
    document_parser.add_argument("--title", default=None, help="Название графа.")
    document_parser.add_argument("--graph-id", default=None, help="Стабильный идентификатор графа.")
    document_parser.add_argument("--model", default=None, help="Модель OpenRouter.")
    document_parser.add_argument(
        "--schema",
        default=str(DEFAULT_SCHEMA_PATH),
        help="Путь к SQL-схеме.",
    )

    technology_parser = subparsers.add_parser(
        "import-technology-maps",
        help="Построить интегрированный граф технологических карт и программ поддержки.",
    )
    add_common_config_args(technology_parser, include_query=False)
    technology_parser.add_argument(
        "--technology-file",
        required=True,
        help="DOCX с технологическими картами.",
    )
    technology_parser.add_argument(
        "--plan-file",
        required=True,
        help="DOCX с единым планом достижения национальных целей.",
    )
    technology_parser.add_argument(
        "--title",
        default="Технологическое лидерство: технологии и программы поддержки",
        help="Название графа.",
    )
    technology_parser.add_argument(
        "--graph-id",
        default="technology-leadership",
        help="Стабильный идентификатор графа.",
    )
    technology_parser.add_argument("--model", default=None, help="Модель OpenRouter.")
    technology_parser.add_argument(
        "--program-extractor",
        choices=("local", "openrouter"),
        default="local",
        help="Способ извлечения программ поддержки. По умолчанию данные не покидают компьютер.",
    )
    technology_parser.add_argument(
        "--schema",
        default=str(DEFAULT_SCHEMA_PATH),
        help="Путь к SQL-схеме.",
    )
    technology_parser.set_defaults(output="outputs/technology_leadership_graph.json")

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
        config = build_config_from_args(
            args,
            require_openrouter=False,
            require_orientdb=False,
        )
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

    config = build_config_from_args(
        args,
        require_openrouter=True,
        require_orientdb=not args.no_save,
    )
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
    config = build_config_from_args(
        args,
        require_openrouter=False,
        require_orientdb=False,
    )
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
                "SearchResult",
                "NewsLink",
                "Source",
                "Topic",
                "ModelRun",
                "GraphDocument",
                "GraphNode",
                "GraphConnection",
                "GraphAnnotation",
                "GraphGroup",
                "GraphTemplate",
                "GraphView",
            )
        }
    )


def command_ensure_schema(args: argparse.Namespace) -> None:
    client_from_args(args).ensure_schema(Path(args.schema))
    json_print({"schema": args.schema, "status": "ok"})


def command_dashboard(args: argparse.Namespace) -> None:
    from electromotiv_pipeline.dashboard import run_dashboard
    from electromotiv_pipeline.graph_api import ApiAuth

    run_dashboard(
        client=client_from_args(args),
        host=args.host,
        port=args.port,
        auth=graph_api_auth_from_args(args, auth_class=ApiAuth),
    )


def command_graph_api(args: argparse.Namespace) -> None:
    from electromotiv_pipeline.graph_api import ApiAuth, run_graph_api

    run_graph_api(
        client=client_from_args(args),
        host=args.host,
        port=args.port,
        auth=graph_api_auth_from_args(args, auth_class=ApiAuth),
    )


def command_decompose_document(args: argparse.Namespace) -> None:
    from uuid import uuid4

    from electromotiv_pipeline.document_graph import decompose_document_with_openrouter

    document_path = Path(args.file)
    try:
        document_text = document_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"Не удалось прочитать документ: {document_path}") from exc
    title = (args.title or document_path.stem).strip()
    graph_id = (args.graph_id or f"document-{uuid4().hex[:12]}").strip()
    config = build_config_from_args(
        args,
        require_openrouter=True,
        require_orientdb=True,
    )
    client = OrientDBClient(
        base_url=config.orientdb_url,
        database=config.orientdb_database,
        auth_header=config.orientdb_auth_header,
    )
    client.ensure_schema(Path(args.schema))
    nodes, edges, _ = decompose_document_with_openrouter(
        api_key=config.openrouter_api_key,
        model=config.openrouter_model,
        title=title,
        text=document_text,
    )
    client.save_graph_document(
        graph_id=graph_id,
        title=title,
        source_type=f"openrouter:{config.openrouter_model}",
        nodes=nodes,
        edges=edges,
    )
    json_print(
        {
            "graph_id": graph_id,
            "nodes": len(nodes),
            "edges": len(edges),
            "model": config.openrouter_model,
        },
        indent=2,
    )


def command_import_technology_maps(args: argparse.Namespace) -> None:
    from electromotiv_pipeline.docx_reader import read_docx
    from electromotiv_pipeline.technology_graph import (
        GraphBundle,
        arrange_graph,
        build_technology_maps,
        normalize_bundle,
        technology_catalog,
    )

    technology_path = Path(args.technology_file)
    plan_path = Path(args.plan_file)
    technology_document = read_docx(technology_path)
    plan_document = read_docx(plan_path)
    use_openrouter = args.program_extractor == "openrouter"
    config = build_config_from_args(
        args,
        require_openrouter=use_openrouter,
        require_orientdb=True,
    )
    client = OrientDBClient(
        base_url=config.orientdb_url,
        database=config.orientdb_database,
        auth_header=config.orientdb_auth_header,
    )
    client.ensure_schema(Path(args.schema))

    technology_graph = build_technology_maps(technology_document)
    llm_response = ""
    if use_openrouter:
        from electromotiv_pipeline.technology_programs import (
            build_program_graph_with_openrouter,
        )

        program_graph, llm_response = build_program_graph_with_openrouter(
            document=plan_document,
            technology_catalog=technology_catalog(technology_graph),
            api_key=config.openrouter_api_key,
            model=config.openrouter_model,
        )
        extractor = f"openrouter:{config.openrouter_model}"
    else:
        from electromotiv_pipeline.technology_programs_local import (
            build_program_graph_locally,
        )

        program_graph = build_program_graph_locally(
            document=plan_document,
            technology_graph=technology_graph,
        )
        extractor = "local-rules-v1"
    graph = arrange_graph(
        normalize_bundle(
            GraphBundle(
                nodes=[*technology_graph.nodes, *program_graph.nodes],
                edges=[*technology_graph.edges, *program_graph.edges],
            )
        )
    )
    client.save_graph_document(
        graph_id=args.graph_id,
        title=args.title,
        source_type=f"docx:{extractor}",
        nodes=graph.nodes,
        edges=graph.edges,
    )
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    audit = {
        "graph_id": args.graph_id,
        "title": args.title,
        "extractor": extractor,
        "source_files": [
            file_fingerprint(technology_path),
            file_fingerprint(plan_path),
        ],
        "statistics": graph_statistics(graph.nodes, graph.edges),
        "nodes": graph.nodes,
        "edges": graph.edges,
    }
    if llm_response:
        audit["llm_response_sha256"] = hashlib.sha256(llm_response.encode("utf-8")).hexdigest()
    output_path.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    json_print(
        {
            "graph_id": args.graph_id,
            "nodes": len(graph.nodes),
            "edges": len(graph.edges),
            "extractor": extractor,
            "output": str(output_path),
        },
        indent=2,
    )


def file_fingerprint(path: Path) -> dict[str, object]:
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"name": path.name, "size": path.stat().st_size, "sha256": digest}


def graph_statistics(
    nodes: list[dict[str, object]],
    edges: list[dict[str, object]],
) -> dict[str, object]:
    node_types = Counter(str(node.get("type") or "") for node in nodes)
    edge_types = Counter(str(edge.get("type") or "") for edge in edges)
    statuses = Counter()
    for node in nodes:
        for prop in node.get("properties", []):
            if isinstance(prop, dict) and prop.get("key") == "status" and prop.get("value"):
                statuses[str(prop["value"])] += 1
    return {
        "nodes": len(nodes),
        "edges": len(edges),
        "node_types": dict(sorted(node_types.items())),
        "edge_types": dict(sorted(edge_types.items())),
        "statuses": dict(sorted(statuses.items())),
    }


def graph_api_auth_from_args(args: argparse.Namespace, *, auth_class):
    username = (args.auth_user or os.environ.get("GRAPH_API_USERNAME", "")).strip()
    password = os.environ.get("GRAPH_API_PASSWORD", "").strip()
    if not username or not password:
        raise RuntimeError(
            "Не заданы GRAPH_API_USERNAME и GRAPH_API_PASSWORD для защищенного Graph API."
        )
    return auth_class(username=username, password=password)


def build_config_from_args(
    args: argparse.Namespace,
    *,
    require_openrouter: bool,
    require_orientdb: bool = True,
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
        require_orientdb=require_orientdb,
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
