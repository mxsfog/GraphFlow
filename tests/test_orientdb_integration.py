from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from electromotiv_pipeline.config import build_config
from electromotiv_pipeline.graph_api import (
    ConflictError,
    custom_graph_payload,
    orient_rows,
    save_graph_annotation,
)
from electromotiv_pipeline.models import RankedLink
from electromotiv_pipeline.orientdb import OrientDBClient

pytestmark = pytest.mark.skipif(
    os.environ.get("ORIENTDB_INTEGRATION") != "1",
    reason="Требуется ORIENTDB_INTEGRATION=1.",
)


def integration_client() -> OrientDBClient:
    config = build_config(
        env_file=Path(".env"),
        query="integration query",
        max_records=1,
        model=None,
        orientdb_url=None,
        database=os.environ.get("ORIENTDB_DATABASE", "news_ci"),
        output_path=None,
        google_sheets_enabled=False,
        require_openrouter=False,
    )
    return OrientDBClient(
        base_url=config.orientdb_url,
        database=config.orientdb_database,
        auth_header=config.orientdb_auth_header,
    )


def ranked_link(*, run_id: str, score: float) -> RankedLink:
    return RankedLink(
        query="integration query",
        run_id=run_id,
        rank=1,
        article_index=1,
        title="Shared article",
        url="https://example.com/shared-integration-article",
        source="Example",
        source_name="integration",
        domain="example.com",
        published_at="2026-07-10T10:00:00Z",
        llm_score=score,
        reason=f"score={score}",
        created_at=datetime.now(UTC).isoformat(timespec="seconds"),
        model="integration-model",
        keywords=("integration",),
        llm_raw_response='{"results":[]}',
    )


def test_run_history_annotations_and_custom_graph() -> None:
    client = integration_client()
    client.ensure_schema(Path("orientdb/schema.sql"))
    first_run = str(uuid4())
    second_run = str(uuid4())
    client.save_ranked_links(
        query="integration query",
        run_id=first_run,
        model="integration-model",
        links=[ranked_link(run_id=first_run, score=0.2)],
        sources_count=1,
        candidates_count=1,
    )
    client.save_ranked_links(
        query="integration query",
        run_id=second_run,
        model="integration-model",
        links=[ranked_link(run_id=second_run, score=0.9)],
        sources_count=1,
        candidates_count=1,
    )
    first_results = orient_rows(
        client,
        f"SELECT expand(out('Found')) FROM SearchRun WHERE run_id = '{first_run}'",
    )
    second_results = orient_rows(
        client,
        f"SELECT expand(out('Found')) FROM SearchRun WHERE run_id = '{second_run}'",
    )
    assert first_results[0]["llm_score"] == 0.2
    assert second_results[0]["llm_score"] == 0.9

    request = {
        "graph_id": f"run:{first_run}",
        "notation": "flow",
        "element_id": "run",
        "element_kind": "node",
        "revision": 0,
        "payload": {"label": "Integration run"},
    }
    saved = save_graph_annotation(client, request)
    assert saved["revision"] == 1
    with pytest.raises(ConflictError):
        save_graph_annotation(client, request)

    graph_id = f"integration-{uuid4().hex}"
    client.save_graph_document(
        graph_id=graph_id,
        title="Integration graph",
        source_type="integration",
        nodes=[
            {
                "id": "a",
                "label": "A",
                "type": "task",
                "position3d": {"x": 12.5, "y": -4.0, "z": 33.0},
            },
            {"id": "b", "label": "B", "type": "result"},
        ],
        edges=[
            {"id": "a-b", "source": "a", "target": "b", "type": "follow"},
        ],
    )
    graph = custom_graph_payload(client=client, graph_id=graph_id, notation="flow")
    assert {node["id"] for node in graph["nodes"]} == {"a", "b"}
    node_a = next(node for node in graph["nodes"] if node["id"] == "a")
    assert node_a["data"]["position3d"] == {"x": 12.5, "y": -4.0, "z": 33.0}
    assert graph["edges"][0]["source"] == "a"
    assert graph["edges"][0]["target"] == "b"

    client.save_graph_document(
        graph_id=graph_id,
        title="Integration graph",
        source_type="integration",
        nodes=[
            {"id": "a", "label": "A", "type": "task"},
            {"id": "b", "label": "B", "type": "result"},
            {"id": "c", "label": "C", "type": "result"},
        ],
        edges=[
            {"id": "a-b", "source": "b", "target": "c", "type": "follow"},
        ],
    )
    changed_graph = custom_graph_payload(client=client, graph_id=graph_id, notation="flow")
    assert changed_graph["edges"][0]["source"] == "b"
    assert changed_graph["edges"][0]["target"] == "c"

    client.save_graph_document(
        graph_id=graph_id,
        title="Integration graph",
        source_type="integration",
        nodes=[
            {"id": "a", "label": "A", "type": "task"},
            {"id": "c", "label": "C", "type": "result"},
        ],
        edges=[],
    )
    reduced_graph = custom_graph_payload(client=client, graph_id=graph_id, notation="flow")
    assert {node["id"] for node in reduced_graph["nodes"]} == {"a", "c"}
    assert reduced_graph["edges"] == []
