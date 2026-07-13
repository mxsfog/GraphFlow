from __future__ import annotations

from pathlib import Path

import pytest

from electromotiv_pipeline.cli import build_parser
from electromotiv_pipeline.config import build_config, get_bool_env
from electromotiv_pipeline.dashboard import link_row, td
from electromotiv_pipeline.document_graph import parse_document_graph
from electromotiv_pipeline.google_news import (
    deduplicate_articles,
    fetch_news,
    parse_google_news_rss,
)
from electromotiv_pipeline.google_sheets import (
    GoogleSheetsClient,
    ServiceAccount,
    ranked_link_to_row,
    sheet_range,
)
from electromotiv_pipeline.graph_api import (
    ApiAuth,
    empty_graph,
    is_authorized,
    merge_edge_style,
    merge_style,
    notation_shape,
    validate_annotation_payload,
)
from electromotiv_pipeline.models import Article, RankedLink
from electromotiv_pipeline.openrouter import (
    build_openrouter_request_body,
    clamp_score,
    parse_ranked_links,
    should_retry_without_response_format,
)
from electromotiv_pipeline.orientdb import orient_datetime, split_sql_statements


def test_parse_google_news_rss() -> None:
    payload = b"""
    <rss><channel>
      <item>
        <title>Oil price spike hits futures market</title>
        <link>https://example.com/news</link>
        <source>Example</source>
        <pubDate>Tue, 02 Jul 2026 10:00:00 GMT</pubDate>
        <description>Brent crude futures moved higher.</description>
      </item>
    </channel></rss>
    """

    articles = parse_google_news_rss(payload, max_records=5)

    assert len(articles) == 1
    assert articles[0].title == "Oil price spike hits futures market"
    assert articles[0].url == "https://example.com/news"


def test_parse_ranked_links_clamps_score() -> None:
    content = """
    ```json
    {"results":[{"rank":1,"title":"A","url":"https://example.com/a","source":"S",
    "published_at":"2026-07-02T10:00:00Z","llm_score":1.7,
    "keywords":["bitcoin","etf"],"reason":"Relevant"}]}
    ```
    """

    ranked = parse_ranked_links(content=content, query="oil")

    assert len(ranked) == 1
    assert ranked[0].llm_score == 1.0
    assert ranked[0].keywords == ("bitcoin", "etf")


def test_parse_ranked_links_uses_article_index() -> None:
    article = Article(
        index=2,
        title="Oil futures spike after supply shock",
        url="https://example.com/real",
        source="Example",
        published_at="2026-07-02T10:00:00Z",
        snippet="Brent futures moved sharply higher.",
    )
    content = """
    {"results":[{"rank":1,"article_index":2,"llm_score":0.8,
    "keywords":["oil futures","supply shock"],"reason":"Direct"}]}
    """

    ranked = parse_ranked_links(content=content, query="oil", articles=[article])

    assert ranked[0].url == "https://example.com/real"
    assert ranked[0].llm_score == 0.8
    assert ranked[0].keywords == ("oil futures", "supply shock")


def test_deduplicate_articles_by_url_and_title() -> None:
    first = Article(
        index=1,
        title="Oil price spike",
        url="https://example.com/a?utm_source=x",
        source="A",
        published_at="",
        snippet="",
    )
    second = Article(
        index=2,
        title="Oil price spike",
        url="https://example.com/a?utm_source=y",
        source="B",
        published_at="",
        snippet="",
    )

    deduplicated = deduplicate_articles([first, second])

    assert len(deduplicated) == 1


def test_orient_datetime_accepts_rfc822_and_iso() -> None:
    assert orient_datetime("Tue, 02 Jul 2026 10:00:00 GMT") == "2026-07-02 10:00:00"
    assert orient_datetime("2026-07-02T10:00:00Z") == "2026-07-02 10:00:00"


def test_split_sql_statements() -> None:
    statements = split_sql_statements("CREATE CLASS A;\n\nCREATE PROPERTY A.name STRING;")

    assert statements == ["CREATE CLASS A", "CREATE PROPERTY A.name STRING"]


def test_google_sheets_row_format() -> None:
    link = RankedLink(
        query="oil",
        run_id="run-1",
        rank=1,
        article_index=2,
        title="Oil futures spike",
        url="https://example.com/news",
        source="Example",
        source_name="google_news",
        domain="example.com",
        published_at="2026-07-02T10:00:00Z",
        llm_score=0.8,
        reason="Связано со скачком цены нефти.",
        created_at="2026-07-02T10:01:00+00:00",
        model="deepseek/deepseek-v4-flash",
        keywords=("oil", "futures"),
    )

    row = ranked_link_to_row(link)

    assert row[0] == "2026-07-02T10:01:00+00:00"
    assert row[5] == "https://example.com/news"
    assert row[11] == "oil, futures"


def test_google_sheets_range_quotes_sheet_name() -> None:
    assert sheet_range("news links", "A1:L1") == "%27news%20links%27%21A1%3AL1"


def test_get_bool_env(monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_SHEETS_ENABLED", "true")

    assert get_bool_env("GOOGLE_SHEETS_ENABLED", False) is True


def test_openrouter_fallback_body_removes_response_format() -> None:
    article = Article(
        index=1,
        title="Bitcoin prediction",
        url="https://example.com/btc",
        source="Example",
        published_at="",
        snippet="Bitcoin price forecast.",
    )

    strict_body = build_openrouter_request_body(
        model="deepseek/deepseek-v4-flash",
        query="Will Bitcoin hit 65k today",
        articles=[article],
        strict_json=True,
    )
    fallback_body = build_openrouter_request_body(
        model="deepseek/deepseek-v4-flash",
        query="Will Bitcoin hit 65k today",
        articles=[article],
        strict_json=False,
    )

    assert strict_body["response_format"] == {"type": "json_object"}
    assert "response_format" not in fallback_body


def test_openrouter_retries_on_invalid_llm_json() -> None:
    assert should_retry_without_response_format(RuntimeError("LLM вернула невалидный JSON"))


def test_openrouter_rejects_unknown_candidate_url() -> None:
    article = Article(
        index=1,
        title="Known",
        url="https://example.com/known",
        source="Example",
        published_at="",
        snippet="Known candidate",
    )
    content = (
        '{"results":[{"rank":1,"article_index":999,'
        '"url":"javascript:alert(1)","llm_score":1,"reason":"Injected"}]}'
    )

    with pytest.raises(RuntimeError, match="валидного кандидата"):
        parse_ranked_links(content=content, query="known", articles=[article])


def test_openrouter_rejects_invalid_top_level_and_nan_score() -> None:
    with pytest.raises(RuntimeError, match="JSON-объект"):
        parse_ranked_links(content="null", query="test")
    assert clamp_score("nan") == 0.0

    article = Article(
        index=1,
        title="Known",
        url="https://example.com/known",
        source="Example",
        published_at="",
        snippet="Known candidate",
    )
    with pytest.raises(RuntimeError, match="валидного кандидата"):
        parse_ranked_links(
            content='{"results":[{"article_index":1,"llm_score":"nan"}]}',
            query="test",
            articles=[article],
        )


def test_fetch_news_reports_source_failure(monkeypatch) -> None:
    def fail_request(*args, **kwargs):
        raise RuntimeError("offline")

    monkeypatch.setattr("electromotiv_pipeline.google_news.get_url", fail_request)

    with pytest.raises(RuntimeError, match="Не удалось получить RSS"):
        fetch_news("test", 5)


def test_commands_without_orientdb_can_build_config(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("ORIENTDB_AUTH_HEADER", raising=False)
    monkeypatch.delenv("ORIENTDB_ROOT_PASSWORD", raising=False)
    config = build_config(
        env_file=tmp_path / "missing.env",
        query="test",
        max_records=5,
        model=None,
        orientdb_url=None,
        database=None,
        output_path=None,
        require_openrouter=False,
        require_orientdb=False,
    )
    assert config.orientdb_auth_header == ""
    assert build_parser().parse_args(["run"]).model is None


def test_google_sheets_does_not_overwrite_foreign_header(monkeypatch) -> None:
    client = GoogleSheetsClient(
        spreadsheet_id="sheet",
        sheet_name="news_links",
        service_account=ServiceAccount("service@example.com", "key", "token"),
    )
    monkeypatch.setattr(client, "get_json", lambda url: {"values": [["foreign", "header"]]})

    with pytest.raises(RuntimeError, match="не перезаписаны"):
        client.ensure_header()


def test_dashboard_escapes_untrusted_anchor_markup() -> None:
    row = {
        "title": "Title",
        "url": "https://example.com",
        "source": "<a href=x>source</a>",
        "reason": "<a href=x>reason</a>",
    }
    rendered = [td(value) for value in link_row(row)]
    assert "&lt;a href=x&gt;source" in rendered[1]
    assert "&lt;a href=x&gt;reason" in rendered[4]


def test_graph_api_notation_shapes() -> None:
    assert (
        notation_shape(node_type="process", stored_shape="rounded_rectangle", notation="flow")
        == "rounded_rectangle"
    )
    assert notation_shape(node_type="data", stored_shape="document", notation="flow") == "document"
    assert notation_shape(node_type="actor", stored_shape="actor", notation="use_case") == "actor"
    assert notation_shape(node_type="process", stored_shape="", notation="use_case") == "ellipse"
    assert notation_shape(node_type="process", stored_shape="", notation="component") == "component"
    assert notation_shape(node_type="process", stored_shape="", notation="class") == "class"


def test_graph_api_use_case_style() -> None:
    node_style = merge_style(
        stored_style={},
        shape=notation_shape(node_type="process", stored_shape="", notation="use_case"),
        node_type="process",
        notation="use_case",
    )
    edge_style = merge_edge_style(stored_style={}, edge_type="found", notation="use_case")

    assert node_style["shape"] == "ellipse"
    assert edge_style["strokeDasharray"] == "6 4"


def test_graph_api_validates_3d_position() -> None:
    validate_annotation_payload(
        "node",
        {"position3d": {"x": 1.5, "y": -2, "z": 3}},
    )
    with pytest.raises(ValueError, match="position3d"):
        validate_annotation_payload(
            "node",
            {"position3d": {"x": 1, "y": 2}},
        )


def test_graph_api_empty_payload() -> None:
    payload = empty_graph(notation="flow", graph_id="latest")

    assert payload == {"graph_id": "latest", "notation": "flow", "nodes": [], "edges": []}


def test_graph_api_basic_auth() -> None:
    import base64

    token = base64.b64encode(b"admin:secret").decode("ascii")
    auth = ApiAuth(username="admin", password="secret")

    assert is_authorized(f"Basic {token}", auth)
    assert not is_authorized("Basic broken", auth)
    assert not is_authorized(None, auth)


def test_parse_document_graph_accepts_markdown_fence() -> None:
    content = """```json
    {
      "nodes": [
        {"id": "section-1", "label": "Раздел", "type": "section", "shape": "document"},
        {"id": "task-1", "label": "Задача", "type": "task"}
      ],
      "edges": [
        {"id": "edge-1", "source": "section-1", "target": "task-1", "type": "include"}
      ]
    }
    ```"""

    nodes, edges, raw_content = parse_document_graph(content)

    assert [node["id"] for node in nodes] == ["section-1", "task-1"]
    assert edges[0]["type"] == "include"
    assert raw_content == content
