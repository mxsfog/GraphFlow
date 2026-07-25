from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile

import pytest

from electromotiv_pipeline.docx_reader import (
    DocxBlock,
    DocxDocument,
    DocxParagraph,
    DocxTable,
    read_docx,
)
from electromotiv_pipeline.technology_graph import REQUIRED_PROPERTY_KEYS, property_value
from electromotiv_pipeline.universal_import import (
    build_universal_graph,
    default_import_profile,
    load_import_profile,
)

PROFILE_PATH = Path("profiles/technology_leadership.json")
TECHNOLOGY_HEADER = (
    "Блок",
    "Процесс создания",
    "Технологии создания",
    "Готовность",
    "Обоснование",
    "Источники",
)


def test_read_docx_preserves_top_level_block_order(tmp_path: Path) -> None:
    path = tmp_path / "ordered.docx"
    document_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
      <w:body>
        <w:p><w:r><w:t>Раздел</w:t></w:r></w:p>
        <w:tbl><w:tr><w:tc><w:p><w:r><w:t>Колонка</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
        <w:p><w:r><w:t>Итог</w:t></w:r></w:p>
      </w:body>
    </w:document>"""
    with ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", document_xml)

    document = read_docx(path)

    assert [block.kind for block in document.blocks] == ["paragraph", "table", "paragraph"]
    assert document.blocks[0].paragraph.text == "Раздел"
    assert document.blocks[1].table.rows == (("Колонка",),)
    assert document.blocks[2].paragraph.text == "Итог"


def test_auto_profile_builds_structural_graph_for_arbitrary_docx() -> None:
    heading = DocxParagraph(0, "1. Архитектура", "Heading 1")
    paragraph = DocxParagraph(1, "Описание решения.", "Normal")
    table = DocxTable((("Компонент", "Статус"), ("API", "Готов")))
    document = DocxDocument(
        path=Path("arbitrary.docx"),
        paragraphs=(heading, paragraph),
        tables=(table,),
        blocks=(
            DocxBlock(0, "paragraph", paragraph=heading),
            DocxBlock(1, "paragraph", paragraph=paragraph),
            DocxBlock(2, "table", table=table),
        ),
    )

    result = build_universal_graph([document], default_import_profile())

    node_types = {str(node["type"]) for node in result.graph.nodes}
    edge_types = {str(edge["type"]) for edge in result.graph.edges}
    assert {"document", "section", "paragraph", "table", "table_row"} <= node_types
    assert edge_types == {"include"}
    assert result.diagnostics[0]["mode"] == "structure"


def test_profile_assigns_documents_by_structure_and_builds_semantic_graph() -> None:
    profile = load_import_profile(PROFILE_PATH)
    technology = technology_document(Path("first-random-name.docx"))
    programs = program_document(Path("second-random-name.docx"))

    result = build_universal_graph([programs, technology], profile)

    nodes_by_id = {str(node["id"]): node for node in result.graph.nodes}
    edge_types = {str(edge["type"]) for edge in result.graph.edges}
    assert {"product:robots", "program:bas", "program:science"} <= nodes_by_id.keys()
    assert property_value(nodes_by_id["product:robots"], "direction") == "Роботы"
    assert {
        "has_block",
        "has_process",
        "uses_technology",
        "has_goal",
        "has_activity",
        "has_project",
        "todo",
        "supports",
        "develops",
        "implements",
        "make",
        "intersects_with",
    } <= edge_types
    edge_keys = {
        (str(edge["source"]), str(edge["target"]), str(edge["type"])) for edge in result.graph.edges
    }
    assert ("program:bas", "product:robots", "supports") in edge_keys
    assert ("program:bas", "product:batteries", "supports") not in edge_keys
    assert property_value(nodes_by_id["product:robots"], "topics") == "robots"
    assert [item["role"] for item in result.diagnostics] == [
        "technology_maps",
        "support_programs",
    ]
    for item in [*result.graph.nodes, *result.graph.edges]:
        keys = {str(prop["key"]) for prop in item["properties"]}
        assert set(REQUIRED_PROPERTY_KEYS) <= keys


def test_profile_validation_rejects_unknown_schema(tmp_path: Path) -> None:
    path = tmp_path / "invalid.json"
    path.write_text('{"schema_version": 99, "profile_id": "invalid"}', encoding="utf-8")

    with pytest.raises(RuntimeError, match="Версия профиля"):
        load_import_profile(path)


def technology_document(path: Path) -> DocxDocument:
    heading = DocxParagraph(0, "2. Роботы: демонстрационный AMR", "Heading 1")
    goal = DocxParagraph(1, "Конкретная цель: создать автономного робота.", "Normal")
    source = DocxParagraph(2, "R1 Официальный источник", "Normal")
    table = DocxTable(
        (
            TECHNOLOGY_HEADER,
            (
                "Навигация / локализация",
                "Построить маршрут",
                "Лидарная локализация; Автономная навигация",
                "Зелёный",
                "Технология применяется.",
                "R1",
            ),
        )
    )
    return DocxDocument(
        path=path,
        paragraphs=(heading, goal, source),
        tables=(table,),
        blocks=(
            DocxBlock(0, "paragraph", paragraph=heading),
            DocxBlock(1, "paragraph", paragraph=goal),
            DocxBlock(2, "table", table=table),
            DocxBlock(3, "paragraph", paragraph=source),
        ),
    )


def program_document(path: Path) -> DocxDocument:
    texts = (
        "6.1.4. Обеспечение технологической независимости в отрасли БАС",
        "Стимулирование спроса на БАС обеспечивается посредством реализации:",
        "- проекта автономной навигации для БАС;",
        "Результатами достижения показателя станут отечественные БАС.",
        "6.1.4. Достигнутый уровень технологической независимости, %",
        "6.1.5. Следующий раздел",
        "6.3. Обеспечение к 2030 году научно-технологического лидерства",
        "Ключевыми факторами и инструментами станут:",
        "Поддержка исследований в области автономных систем.",
        "Подробнее факторы и инструменты перечислены далее.",
        "6.4. Увеличение к 2030 году внутренних затрат на исследования",
        "Ключевыми факторами и инструментами станут:",
        "Финансирование разработок электронных компонентов.",
        "Подробнее факторы и инструменты перечислены далее.",
        "6.5. Следующий раздел",
    )
    paragraphs = tuple(
        DocxParagraph(index, text, "ConsPlusTitle" if text.startswith("6.") else "Normal")
        for index, text in enumerate(texts)
    )
    return DocxDocument(path=path, paragraphs=paragraphs, tables=())
