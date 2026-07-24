from __future__ import annotations

import json
from pathlib import Path

from electromotiv_pipeline.docx_reader import DocxDocument, DocxParagraph, DocxTable
from electromotiv_pipeline.graph_api import apply_readiness_style
from electromotiv_pipeline.technology_graph import (
    REQUIRED_PROPERTY_KEYS,
    GraphBundle,
    arrange_graph,
    build_technology_maps,
    graph_node,
    normalize_bundle,
    property_value,
)
from electromotiv_pipeline.technology_programs import (
    extract_program_context,
    parse_program_graph,
)
from electromotiv_pipeline.technology_programs_local import build_program_graph_locally

TECHNOLOGY_HEADER = (
    "Блок",
    "Процесс создания",
    "Технологии создания",
    "Готовность",
    "Обоснование",
    "Источники",
)


def test_build_technology_maps_preserves_hierarchy_and_shared_technology() -> None:
    document = technology_document()

    graph = normalize_bundle(build_technology_maps(document))

    node_types = [str(node["type"]) for node in graph.nodes]
    edge_types = [str(edge["type"]) for edge in graph.edges]
    assert node_types.count("product") == 3
    assert node_types.count("technology_block") == 3
    assert node_types.count("process") == 3
    assert node_types.count("technology") == 1
    assert edge_types.count("has_block") == 3
    assert edge_types.count("has_process") == 3
    assert edge_types.count("uses_technology") == 3

    technology = next(node for node in graph.nodes if node["type"] == "technology")
    assert property_value(technology, "direction") == "Аккумуляторы; Микросхемы; Роботы"
    assert property_value(technology, "status") == "Красный"
    assert "Роботы: Зелёный" in property_value(technology, "direction_statuses")

    for item in [*graph.nodes, *graph.edges]:
        keys = {str(prop["key"]) for prop in item["properties"]}
        assert set(REQUIRED_PROPERTY_KEYS) <= keys


def test_program_graph_keeps_domain_nodes_separate_from_program_roots() -> None:
    content = json.dumps(
        {
            "nodes": [
                program_node(
                    "science",
                    "ГП Научно-технологическое развитие Российской Федерации",
                    "program",
                    "Госпрограмма «Наука»",
                ),
                program_node(
                    "bas",
                    "НПТЛ Беспилотные авиационные системы",
                    "program",
                    "Федеральный проект БАС",
                ),
                program_node(
                    "goal-science",
                    "Обеспечить научно-технологическое развитие",
                    "program_goal",
                    "Госпрограмма «Наука»",
                ),
                program_node(
                    "shared-activity-science",
                    "Создание отечественной электронной компонентной базы",
                    "activity",
                    "Госпрограмма «Наука»",
                ),
                program_node(
                    "shared-activity-bas",
                    "Создание отечественной электронной компонентной базы",
                    "activity",
                    "Федеральный проект БАС",
                ),
            ],
            "edges": [
                program_edge("science", "goal-science", "has_goal"),
                program_edge("science", "shared-activity-science", "has_activity"),
                program_edge("bas", "shared-activity-bas", "has_activity"),
                program_edge(
                    "shared-activity-science",
                    "technology:shared",
                    "supports",
                ),
            ],
        },
        ensure_ascii=False,
    )

    graph = parse_program_graph(
        content,
        technology_node_ids={"technology:shared"},
        source_name="plan.docx",
    )

    assert len(graph.nodes) == 4
    assert {str(node["id"]) for node in graph.nodes} >= {
        "program:science",
        "program:bas",
    }
    goal = next(node for node in graph.nodes if node["type"] == "program_goal")
    assert goal["id"] not in {"program:science", "program:bas"}
    shared = next(node for node in graph.nodes if node["type"] == "activity")
    assert property_value(shared, "direction") == ("Госпрограмма «Наука»; Федеральный проект БАС")
    assert len(graph.edges) == 4


def test_extract_program_context_uses_semantic_sections() -> None:
    paragraphs = (
        DocxParagraph(0, "ТЕХНОЛОГИЧЕСКОЕ ЛИДЕРСТВО", "Title"),
        DocxParagraph(1, "Общая рамка технологического лидерства Российской Федерации.", ""),
        DocxParagraph(2, "Индикатор, характеризующий завершение вводного раздела.", ""),
        DocxParagraph(3, "6.1.4. Беспилотные авиационные системы", "Title"),
        DocxParagraph(4, "Мероприятия по развитию беспилотных авиационных систем.", ""),
        DocxParagraph(5, "6.1.5. Следующий раздел", "Title"),
        DocxParagraph(6, "6.3. Научно-технологическое развитие", "Title"),
        DocxParagraph(7, "Государственная программа поддержки исследований и разработок.", ""),
        DocxParagraph(8, "6.4. Исследования и разработки", "Title"),
        DocxParagraph(9, "Проекты по созданию отечественных технологий и оборудования.", ""),
        DocxParagraph(10, "6.5. Следующий раздел", "Title"),
    )
    document = DocxDocument(Path("plan.docx"), paragraphs, ())

    context = extract_program_context(document)

    assert "Беспилотные авиационные системы" in context
    assert "Государственная программа поддержки" in context
    assert "Следующий раздел" not in context


def test_apply_readiness_style_overrides_type_palette() -> None:
    base = {"background": "#ffffff", "borderColor": "#000000"}

    styled = apply_readiness_style(
        base,
        [{"key": "status", "value": "Оранжевый: требуется адаптация"}],
    )

    assert styled["background"] == "#ffedd5"
    assert styled["borderColor"] == "#c2410c"


def test_local_program_extractor_builds_complete_program_hierarchy() -> None:
    technology_graph = build_technology_maps(technology_document())

    program_graph = build_program_graph_locally(
        document=local_plan_document(),
        technology_graph=technology_graph,
    )
    graph = normalize_bundle(
        GraphBundle(
            nodes=[*technology_graph.nodes, *program_graph.nodes],
            edges=[*technology_graph.edges, *program_graph.edges],
        )
    )

    node_ids = {str(node["id"]) for node in graph.nodes}
    edge_types = {str(edge["type"]) for edge in graph.edges}
    assert {"program:science", "program:bas"} <= node_ids
    assert {
        "has_goal",
        "has_indicator",
        "has_activity",
        "has_project",
        "produces_result",
        "follow",
        "todo",
        "implements",
        "make",
        "intersects_with",
        "supports",
        "develops",
    } <= edge_types
    assert sum(node_id.startswith("activity:science:") for node_id in node_ids) == 7
    assert all(property_value(node, "end_date") == "2030-12-31" for node in program_graph.nodes)


def test_arrange_graph_limits_rows_and_separates_direction_planes() -> None:
    robots = [
        graph_node(
            node_id=f"technology:test:{index}",
            label=f"Технология {index:02d}",
            node_type="technology",
            direction="Роботы",
            source="test",
            description="test",
            status="Зелёный",
        )
        for index in range(25)
    ]
    science = graph_node(
        node_id="program:test",
        label="Программа",
        node_type="program",
        direction="Госпрограмма «Наука»",
        source="test",
        description="test",
        status="План",
    )

    graph = arrange_graph(GraphBundle(nodes=[*robots, science], edges=[]))

    robot_x = {int(node["x"]) for node in graph.nodes[:-1]}
    robot_y = {int(node["y"]) for node in graph.nodes[:-1]}
    assert len(robot_x) == 3
    assert max(robot_y) <= 9 * 125
    assert int(science["x"]) >= 3_600
    assert int(science["y"]) >= 1_550
    assert science["position3d"]["z"] != robots[0]["position3d"]["z"]


def technology_document() -> DocxDocument:
    product_row = (
        "Продукт",
        "Описание продукта",
        "Назначение продукта",
        "Зелёный",
        "Обоснование продукта",
        "R1",
    )
    return DocxDocument(
        path=Path("technology.docx"),
        paragraphs=(
            DocxParagraph(0, "Конкретная цель: Создать автономного робота.", ""),
            DocxParagraph(1, "R1 Официальный источник", ""),
        ),
        tables=(
            DocxTable((("Легенда",),)),
            DocxTable(
                (
                    TECHNOLOGY_HEADER,
                    technology_row("Роботы", "Зелёный"),
                )
            ),
            DocxTable(
                (
                    TECHNOLOGY_HEADER,
                    product_row,
                    technology_row("Аккумуляторы", "Оранжевый"),
                )
            ),
            DocxTable(
                (
                    TECHNOLOGY_HEADER,
                    product_row,
                    technology_row("Микросхемы", "Красный"),
                )
            ),
        ),
    )


def technology_row(direction: str, readiness: str) -> tuple[str, ...]:
    return (
        f"Блок {direction}",
        f"Процесс {direction}",
        "Общая технология",
        readiness,
        f"Обоснование {direction}",
        "R1",
    )


def program_node(node_id: str, label: str, node_type: str, map_name: str) -> dict[str, str]:
    return {
        "id": node_id,
        "label": label,
        "type": node_type,
        "map": map_name,
        "start_date": "",
        "end_date": "2030-12-31",
        "source": "Единый план",
        "description": label,
        "status": "",
    }


def program_edge(source: str, target: str, edge_type: str) -> dict[str, str]:
    return {
        "source": source,
        "target": target,
        "type": edge_type,
        "label": edge_type,
        "start_date": "",
        "end_date": "2030-12-31",
        "data_source": "Единый план",
        "description": edge_type,
        "status": "",
    }


def local_plan_document() -> DocxDocument:
    texts = [
        "6.1.4. Обеспечение технологической независимости в отрасли БАС",
        "Результатами достижения показателя станут рост рынка и доли отечественных БАС.",
        "Стимулирование спроса на БАС обеспечивается посредством реализации:",
        "- механизма поддержки эксплуатантов беспилотных авиационных систем;",
        "Разработка, стандартизация и серийное производство БАС обеспечивается:",
        "- механизма грантов на критически важные комплектующие;",
        "Развитие инфраструктуры, обеспечение безопасности и сертификации:",
        "- внедрения унифицированной инфраструктуры управления БАС;",
        "Формирование кадрового потенциала отрасли посредством:",
        "- создания системы подготовки специалистов;",
        "Разработка перспективных технологий в отрасли БАС.",
        "Для обеспечения технологической независимости будет разработано 9 технологий.",
        "Достижение обеспечивается мероприятиями национального проекта БАС.",
        "6.1.4. Достигнутый уровень технологической независимости в отрасли БАС, %",
        "6.1.5. Следующий раздел",
        "6.3. Вхождение России в число ведущих стран по исследованиям",
        "Ключевыми факторами и инструментами станут:",
        *science_factor_texts(),
        "Подробнее факторы перечислены в пункте 6.6.",
        'ГП "Научно-технологическое развитие Российской Федерации"',
        "6.3. Место Российской Федерации в мире по объему исследований, место",
        "Место Российской Федерации по численности исследователей, место",
        "Место Российской Федерации по объему затрат, место",
        "6.4. Увеличение затрат на исследования до 2 процентов ВВП",
        "Ключевыми факторами и инструментами станут:",
        *science_factor_texts(),
        "Подробнее факторы перечислены в пункте 6.6.",
        "6.4.а. Внутренние затраты на исследования, %",
        "6.4.б. Удельный вес внебюджетных источников, %",
        "6.5. Следующий раздел",
    ]
    paragraphs = tuple(
        DocxParagraph(index, text, "ConsPlusTitle" if text[0].isdigit() else "")
        for index, text in enumerate(texts)
    )
    return DocxDocument(Path("plan.docx"), paragraphs, ())


def science_factor_texts() -> list[str]:
    return [
        "Увеличение вклада результатов научных исследований в развитие.",
        "Формирование стимулов к научной деятельности и внедрению результатов.",
        "Развитие новых форм интеграции исследований и производства.",
        "Формирование механизмов финансирования инновационных проектов.",
        "Обеспечение технологического перевооружения науки.",
        "Развитие кадрового потенциала исследований.",
        "Поддержка малых технологических компаний.",
    ]
