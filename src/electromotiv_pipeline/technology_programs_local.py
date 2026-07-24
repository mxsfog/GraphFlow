from __future__ import annotations

import re
from dataclasses import dataclass
from itertools import combinations

from electromotiv_pipeline.docx_reader import DocxDocument, DocxParagraph
from electromotiv_pipeline.technology_graph import (
    GraphBundle,
    add_edge,
    graph_node,
    merge_strings,
    property_value,
    set_property,
    stable_suffix,
)

SCIENCE_MAP = "Госпрограмма «Наука»"
BAS_MAP = "Федеральный проект БАС"
PLAN_STATUS = "План"
ACTIVE_STATUS = "Действует"
PLAN_END_DATE = "2030-12-31"
PRODUCT_IDS = ("product:robots", "product:batteries", "product:microchips")


@dataclass(frozen=True)
class BasActivitySpec:
    key: str
    label: str
    prefix: str


@dataclass(frozen=True)
class ScienceActivitySpec:
    key: str
    label: str
    prefix: str
    project_label: str


BAS_ACTIVITIES = (
    BasActivitySpec(
        "demand",
        "Стимулирование спроса на БАС",
        "Стимулирование спроса на БАС",
    ),
    BasActivitySpec(
        "production",
        "Разработка, стандартизация и серийное производство БАС и комплектующих",
        "Разработка, стандартизация и серийное производство",
    ),
    BasActivitySpec(
        "infrastructure",
        "Инфраструктура, безопасность и сертификация БАС",
        "Развитие инфраструктуры, обеспечение безопасности",
    ),
    BasActivitySpec(
        "workforce",
        "Формирование кадрового потенциала отрасли БАС",
        "Формирование кадрового потенциала",
    ),
    BasActivitySpec(
        "future-technologies",
        "Разработка перспективных технологий БАС",
        "Разработка перспективных технологий",
    ),
)

SCIENCE_ACTIVITIES = (
    ScienceActivitySpec(
        "research-results",
        "Вклад результатов исследований в социально-экономическое развитие",
        "Увеличение вклада результатов научных исследований",
        "Приоритизация научно-технических программ",
    ),
    ScienceActivitySpec(
        "incentives",
        "Стимулы к научной деятельности и внедрению результатов",
        "Формирование стимулов к научной деятельности",
        "Модель квалифицированного заказчика и трансфер технологий",
    ),
    ScienceActivitySpec(
        "integration",
        "Интеграция исследований и производственно-технологической деятельности",
        "Развитие новых форм интеграции",
        "Исследовательские консорциумы и кооперация с бизнесом",
    ),
    ScienceActivitySpec(
        "financing",
        "Финансирование инновационных проектов полного цикла",
        "Формирование механизмов финансирования",
        "Финансирование проектов полного инновационного цикла",
    ),
    ScienceActivitySpec(
        "equipment",
        "Технологическое перевооружение науки",
        "Обеспечение технологического перевооружения",
        "Отечественное научное оборудование и исследовательская инфраструктура",
    ),
    ScienceActivitySpec(
        "workforce",
        "Развитие кадрового потенциала исследований и разработок",
        "Развитие кадрового потенциала",
        "Привлечение и закрепление научных кадров",
    ),
    ScienceActivitySpec(
        "small-companies",
        "Поддержка малых технологических компаний",
        "Поддержка малых технологических компаний",
        "Упрощённая поддержка малых технологических компаний",
    ),
)

TOKEN_STOP_WORDS = {
    "автоматизированный",
    "выполнение",
    "изготовление",
    "использование",
    "контроль",
    "обеспечение",
    "обработка",
    "операция",
    "производство",
    "разработка",
    "система",
    "создание",
    "технология",
    "устройство",
}


def build_program_graph_locally(
    *,
    document: DocxDocument,
    technology_graph: GraphBundle,
) -> GraphBundle:
    nodes_by_id: dict[str, dict[str, object]] = {}
    edges_by_key: dict[tuple[str, str, str], dict[str, object]] = {}
    bas = section_paragraphs(document, "6.1.4.", ("6.1.5.",))
    science = section_paragraphs(document, "6.3.", ("6.5.",))

    bas_context = build_bas_graph(document, bas, nodes_by_id, edges_by_key)
    science_context = build_science_graph(document, science, nodes_by_id, edges_by_key)
    add_program_support_edges(
        document=document,
        bas=bas_context,
        science=science_context,
        technology_graph=technology_graph,
        edges_by_key=edges_by_key,
    )
    add_technology_intersections(technology_graph, edges_by_key, document.path.name)
    mark_shared_technologies(technology_graph)
    return GraphBundle(nodes=list(nodes_by_id.values()), edges=list(edges_by_key.values()))


def build_bas_graph(
    document: DocxDocument,
    paragraphs: list[DocxParagraph],
    nodes_by_id: dict[str, dict[str, object]],
    edges_by_key: dict[tuple[str, str, str], dict[str, object]],
) -> dict[str, object]:
    goal = find_paragraph(paragraphs, "6.1.4.")
    program_source = find_containing(paragraphs, "национального проекта")
    nodes_by_id["program:bas"] = program_node(
        node_id="program:bas",
        label="НПТЛ «Беспилотные авиационные системы»",
        direction=BAS_MAP,
        source=source_reference(document, program_source, "6.1.4"),
        description=program_source.text,
    )
    nodes_by_id["goal:bas:independence"] = program_element_node(
        node_id="goal:bas:independence",
        label=strip_section_number(goal.text),
        node_type="program_goal",
        direction=BAS_MAP,
        paragraph=goal,
        document=document,
        section="6.1.4",
    )
    add_program_edge(
        edges_by_key,
        "program:bas",
        "goal:bas:independence",
        "has_goal",
        "включает цель",
        document,
        goal,
    )

    indicator = find_containing(paragraphs, "Достигнутый уровень технологической")
    indicator_id = "indicator:bas:independence"
    nodes_by_id[indicator_id] = program_element_node(
        node_id=indicator_id,
        label=strip_section_number(indicator.text),
        node_type="indicator",
        direction=BAS_MAP,
        paragraph=indicator,
        document=document,
        section="6.1.4",
        extra={"planned": "81,1", "unit": "%", "year": "2030"},
    )
    add_program_edge(
        edges_by_key,
        "goal:bas:independence",
        indicator_id,
        "has_indicator",
        "измеряется показателем",
        document,
        indicator,
    )

    activity_paragraphs = [
        (spec, find_paragraph(paragraphs, spec.prefix)) for spec in BAS_ACTIVITIES
    ]
    project_ids: dict[str, str] = {}
    previous_activity_id = ""
    for index, (spec, paragraph) in enumerate(activity_paragraphs):
        activity_id = f"activity:bas:{spec.key}"
        nodes_by_id[activity_id] = program_element_node(
            node_id=activity_id,
            label=spec.label,
            node_type="activity",
            direction=BAS_MAP,
            paragraph=paragraph,
            document=document,
            section="6.1.4",
        )
        add_program_edge(
            edges_by_key,
            "goal:bas:independence",
            activity_id,
            "has_activity",
            "включает мероприятие",
            document,
            paragraph,
        )
        add_program_edge(
            edges_by_key,
            "program:bas",
            activity_id,
            "implements",
            "реализует",
            document,
            paragraph,
        )
        if previous_activity_id:
            add_program_edge(
                edges_by_key,
                previous_activity_id,
                activity_id,
                "follow",
                "следует",
                document,
                paragraph,
            )
        previous_activity_id = activity_id
        next_index = (
            activity_paragraphs[index + 1][1].index
            if index + 1 < len(activity_paragraphs)
            else paragraph.index + 1
        )
        projects = [
            item
            for item in paragraphs
            if paragraph.index < item.index < next_index and item.text.startswith("-")
        ]
        if spec.key == "future-technologies":
            projects = [paragraph]
        for project in projects:
            project_id = f"project:bas:{stable_suffix(project.text)}"
            project_ids[project.text] = project_id
            nodes_by_id[project_id] = program_element_node(
                node_id=project_id,
                label=project_label(project.text, spec.key),
                node_type="project",
                direction=BAS_MAP,
                paragraph=project,
                document=document,
                section="6.1.4",
            )
            add_program_edge(
                edges_by_key,
                activity_id,
                project_id,
                "has_project",
                "включает проект",
                document,
                project,
            )
            add_program_edge(
                edges_by_key,
                activity_id,
                project_id,
                "todo",
                "к реализации",
                document,
                project,
            )

    result_market = find_containing(paragraphs, "Результатами достижения показателя станут")
    result_technologies = find_paragraph(paragraphs, "Для обеспечения технологической")
    results = (
        (
            "result:bas:market",
            "Рост рынка и доли отечественных БАС",
            result_market,
        ),
        (
            "result:bas:technologies",
            "14 заказчиков, 5 исполнителей и 9 технологий",
            result_technologies,
        ),
    )
    for result_id, label, paragraph in results:
        nodes_by_id[result_id] = program_element_node(
            node_id=result_id,
            label=label,
            node_type="expected_result",
            direction=BAS_MAP,
            paragraph=paragraph,
            document=document,
            section="6.1.4",
        )
        add_program_edge(
            edges_by_key,
            "goal:bas:independence",
            result_id,
            "produces_result",
            "ожидаемый результат",
            document,
            paragraph,
        )

    future_project_id = project_ids[
        find_paragraph(paragraphs, "Разработка перспективных технологий").text
    ]
    add_program_edge(
        edges_by_key,
        future_project_id,
        "result:bas:technologies",
        "make",
        "создаёт",
        document,
        result_technologies,
    )
    return {
        "activities": {spec.key: f"activity:bas:{spec.key}" for spec in BAS_ACTIVITIES},
        "projects": project_ids,
        "program_source": program_source,
        "future_source": find_paragraph(paragraphs, "Разработка перспективных технологий"),
    }


def build_science_graph(
    document: DocxDocument,
    paragraphs: list[DocxParagraph],
    nodes_by_id: dict[str, dict[str, object]],
    edges_by_key: dict[tuple[str, str, str], dict[str, object]],
) -> dict[str, object]:
    program_source = find_containing(
        paragraphs,
        'ГП "Научно-технологическое развитие Российской Федерации"',
    )
    nodes_by_id["program:science"] = program_node(
        node_id="program:science",
        label="ГП «Научно-технологическое развитие Российской Федерации»",
        direction=SCIENCE_MAP,
        source=source_reference(document, program_source, "6.3–6.4"),
        description=program_source.text,
    )

    goal_specs = (
        (
            "goal:science:top-ten",
            "6.3.",
            "6.4.",
            "result:science:top-ten",
            "Вхождение России в десятку ведущих стран по объёму исследований",
        ),
        (
            "goal:science:rd-spending",
            "6.4.",
            "6.5.",
            "result:science:rd-spending",
            "Затраты на исследования не менее 2% ВВП",
        ),
    )
    goal_segments: dict[str, list[DocxParagraph]] = {}
    for goal_id, start, end, result_id, result_label in goal_specs:
        segment = section_paragraphs_from_list(paragraphs, start, (end,))
        goal_segments[goal_id] = segment
        goal = segment[0]
        nodes_by_id[goal_id] = program_element_node(
            node_id=goal_id,
            label=strip_section_number(goal.text),
            node_type="program_goal",
            direction=SCIENCE_MAP,
            paragraph=goal,
            document=document,
            section=start.rstrip("."),
        )
        add_program_edge(
            edges_by_key,
            "program:science",
            goal_id,
            "has_goal",
            "включает цель",
            document,
            goal,
        )
        nodes_by_id[result_id] = program_element_node(
            node_id=result_id,
            label=result_label,
            node_type="expected_result",
            direction=SCIENCE_MAP,
            paragraph=goal,
            document=document,
            section=start.rstrip("."),
        )
        add_program_edge(
            edges_by_key,
            goal_id,
            result_id,
            "produces_result",
            "ожидаемый результат",
            document,
            goal,
        )

    indicators = (
        (
            "indicator:science:research-volume",
            "goal:science:top-ten",
            "6.3. Место Российской Федерации в мире по объему",
            "8",
            "место",
        ),
        (
            "indicator:science:researchers",
            "goal:science:top-ten",
            "Место Российской Федерации по численности исследователей",
            "6",
            "место",
        ),
        (
            "indicator:science:research-spending-rank",
            "goal:science:top-ten",
            "Место Российской Федерации по объему затрат",
            "10",
            "место",
        ),
        (
            "indicator:science:rd-gdp",
            "goal:science:rd-spending",
            "6.4.а. Внутренние затраты",
            "2",
            "% ВВП",
        ),
        (
            "indicator:science:private-share",
            "goal:science:rd-spending",
            "6.4.б. Удельный вес внебюджетных",
            "43,0",
            "%",
        ),
    )
    for indicator_id, goal_id, prefix, planned, unit in indicators:
        paragraph = find_paragraph(paragraphs, prefix)
        nodes_by_id[indicator_id] = program_element_node(
            node_id=indicator_id,
            label=strip_section_number(paragraph.text),
            node_type="indicator",
            direction=SCIENCE_MAP,
            paragraph=paragraph,
            document=document,
            section="6.3" if goal_id == "goal:science:top-ten" else "6.4",
            extra={"planned": planned, "unit": unit, "year": "2030"},
        )
        add_program_edge(
            edges_by_key,
            goal_id,
            indicator_id,
            "has_indicator",
            "измеряется показателем",
            document,
            paragraph,
        )

    activities_by_goal: dict[str, list[str]] = {}
    for goal_id, segment in goal_segments.items():
        factors = factor_paragraphs(segment)
        previous_activity_id = ""
        activities_by_goal[goal_id] = []
        for spec in SCIENCE_ACTIVITIES:
            paragraph = next(
                (item for item in factors if item.text.startswith(spec.prefix)),
                None,
            )
            if paragraph is None:
                continue
            activity_id = f"activity:science:{spec.key}"
            activities_by_goal[goal_id].append(activity_id)
            if activity_id not in nodes_by_id:
                nodes_by_id[activity_id] = program_element_node(
                    node_id=activity_id,
                    label=spec.label,
                    node_type="activity",
                    direction=SCIENCE_MAP,
                    paragraph=paragraph,
                    document=document,
                    section="6.3" if goal_id == "goal:science:top-ten" else "6.4",
                )
            else:
                merge_node_source(nodes_by_id[activity_id], document, paragraph)
            add_program_edge(
                edges_by_key,
                goal_id,
                activity_id,
                "has_activity",
                "включает мероприятие",
                document,
                paragraph,
            )
            if previous_activity_id:
                add_program_edge(
                    edges_by_key,
                    previous_activity_id,
                    activity_id,
                    "follow",
                    "следует",
                    document,
                    paragraph,
                )
            previous_activity_id = activity_id

    for spec in SCIENCE_ACTIVITIES:
        activity_id = f"activity:science:{spec.key}"
        activity = nodes_by_id.get(activity_id)
        if activity is None:
            continue
        project_id = f"project:science:{spec.key}"
        source = property_value(activity, "source")
        description = property_value(activity, "description")
        nodes_by_id[project_id] = graph_node(
            node_id=project_id,
            label=spec.project_label,
            node_type="project",
            direction=SCIENCE_MAP,
            source=source,
            description=description,
            status=PLAN_STATUS,
            end_date=PLAN_END_DATE,
        )
        paragraph = find_paragraph(paragraphs, spec.prefix)
        add_program_edge(
            edges_by_key,
            activity_id,
            project_id,
            "has_project",
            "включает проект",
            document,
            paragraph,
        )
        add_program_edge(
            edges_by_key,
            activity_id,
            project_id,
            "todo",
            "к реализации",
            document,
            paragraph,
        )
    financing = find_paragraph(paragraphs, "Формирование механизмов финансирования")
    add_program_edge(
        edges_by_key,
        "program:science",
        "activity:science:financing",
        "implements",
        "реализует",
        document,
        financing,
    )
    return {
        "activities": {
            spec.key: f"activity:science:{spec.key}"
            for spec in SCIENCE_ACTIVITIES
            if f"activity:science:{spec.key}" in nodes_by_id
        },
        "program_source": program_source,
    }


def add_program_support_edges(
    *,
    document: DocxDocument,
    bas: dict[str, object],
    science: dict[str, object],
    technology_graph: GraphBundle,
    edges_by_key: dict[tuple[str, str, str], dict[str, object]],
) -> None:
    bas_activities = dict(bas["activities"])
    science_activities = dict(science["activities"])
    bas_source = bas["program_source"]
    science_source = science["program_source"]
    future_source = bas["future_source"]
    if (
        not isinstance(bas_source, DocxParagraph)
        or not isinstance(science_source, DocxParagraph)
        or not isinstance(future_source, DocxParagraph)
    ):
        raise RuntimeError("Не удалось определить источники программ поддержки.")

    add_supports(
        edges_by_key,
        source="program:bas",
        targets=("product:robots",),
        edge_type="supports",
        label="поддерживает направление",
        document=document,
        paragraph=bas_source,
    )
    add_supports(
        edges_by_key,
        source=str(bas_activities["production"]),
        targets=PRODUCT_IDS,
        edge_type="supports",
        label="поддерживает локализацию",
        document=document,
        paragraph=bas_source,
    )
    add_supports(
        edges_by_key,
        source=str(bas_activities["future-technologies"]),
        targets=PRODUCT_IDS,
        edge_type="develops",
        label="развивает технологии",
        document=document,
        paragraph=bas_source,
    )

    science_target_map = {
        "research-results": PRODUCT_IDS,
        "incentives": PRODUCT_IDS,
        "integration": PRODUCT_IDS,
        "financing": PRODUCT_IDS,
        "equipment": ("product:robots", "product:microchips"),
        "small-companies": PRODUCT_IDS,
    }
    for key, targets in science_target_map.items():
        activity_id = science_activities.get(key)
        if activity_id:
            add_supports(
                edges_by_key,
                source=str(activity_id),
                targets=targets,
                edge_type="supports",
                label="поддерживает направление",
                document=document,
                paragraph=science_source,
            )

    add_program_edge(
        edges_by_key,
        "program:science",
        "goal:bas:independence",
        "supports",
        "поддерживает",
        document,
        bas_source,
    )
    add_program_edge(
        edges_by_key,
        "program:science",
        "program:bas",
        "intersects_with",
        "пересекается",
        document,
        science_source,
    )
    add_bas_technology_supports(
        technology_graph=technology_graph,
        edges_by_key=edges_by_key,
        document=document,
        paragraph=future_source,
    )


def add_bas_technology_supports(
    *,
    technology_graph: GraphBundle,
    edges_by_key: dict[tuple[str, str, str], dict[str, object]],
    document: DocxDocument,
    paragraph: DocxParagraph,
) -> None:
    pattern = re.compile(
        r"навигац|локализ|маршрут|зрени|камер|лидар|управлен|связ|"
        r"вычисл|микроконтрол|энерг|силов|привод",
        re.IGNORECASE,
    )
    targets = sorted(
        (
            node
            for node in technology_graph.nodes
            if str(node.get("type")) == "technology"
            and pattern.search(str(node.get("label") or ""))
        ),
        key=lambda node: str(node.get("label") or "").casefold(),
    )
    for target in targets[:18]:
        add_program_edge(
            edges_by_key,
            "activity:bas:future-technologies",
            str(target["id"]),
            "develops",
            "развивает технологию",
            document,
            paragraph,
            description=(
                "Связь определена по совпадению технологического приоритета БАС "
                f"с технологией «{target['label']}»."
            ),
        )


def add_supports(
    edges_by_key: dict[tuple[str, str, str], dict[str, object]],
    *,
    source: str,
    targets: tuple[str, ...],
    edge_type: str,
    label: str,
    document: DocxDocument,
    paragraph: DocxParagraph,
) -> None:
    for target in targets:
        add_program_edge(
            edges_by_key,
            source,
            target,
            edge_type,
            label,
            document,
            paragraph,
            description=(
                f"Связь определена по предметному соответствию мероприятия и направления. "
                f"Основание: {paragraph.text}"
            ),
        )


def add_technology_intersections(
    technology_graph: GraphBundle,
    edges_by_key: dict[tuple[str, str, str], dict[str, object]],
    document_name: str,
) -> None:
    technologies = [
        node for node in technology_graph.nodes if str(node.get("type")) == "technology"
    ]
    candidates: list[tuple[int, str, str, set[str]]] = []
    for left, right in combinations(technologies, 2):
        left_directions = value_set(property_value(left, "direction"))
        right_directions = value_set(property_value(right, "direction"))
        if left_directions & right_directions:
            continue
        common = technology_tokens(str(left["label"])) & technology_tokens(str(right["label"]))
        if len(common) >= 2:
            candidates.append((len(common), str(left["id"]), str(right["id"]), common))
    candidates.sort(key=lambda item: (-item[0], item[1], item[2]))
    for _, source, target, common in candidates[:24]:
        add_edge(
            edges_by_key,
            source=source,
            target=target,
            edge_type="intersects_with",
            label="пересекается",
            source_name=document_name,
            description=(
                "Лексическое пересечение технологических формулировок: "
                + ", ".join(sorted(common))
                + "."
            ),
        )


def mark_shared_technologies(technology_graph: GraphBundle) -> None:
    for node in technology_graph.nodes:
        if str(node.get("type")) != "technology":
            continue
        if len(value_set(property_value(node, "direction"))) > 1:
            set_property(node, "shared_between_maps", "true")


def program_node(
    *,
    node_id: str,
    label: str,
    direction: str,
    source: str,
    description: str,
) -> dict[str, object]:
    return graph_node(
        node_id=node_id,
        label=label,
        node_type="program",
        direction=direction,
        source=source,
        description=description,
        status=ACTIVE_STATUS,
        end_date=PLAN_END_DATE,
    )


def program_element_node(
    *,
    node_id: str,
    label: str,
    node_type: str,
    direction: str,
    paragraph: DocxParagraph,
    document: DocxDocument,
    section: str,
    extra: dict[str, str] | None = None,
) -> dict[str, object]:
    return graph_node(
        node_id=node_id,
        label=label,
        node_type=node_type,
        direction=direction,
        source=source_reference(document, paragraph, section),
        description=paragraph.text,
        status=PLAN_STATUS,
        end_date=PLAN_END_DATE,
        extra=extra,
    )


def add_program_edge(
    edges_by_key: dict[tuple[str, str, str], dict[str, object]],
    source: str,
    target: str,
    edge_type: str,
    label: str,
    document: DocxDocument,
    paragraph: DocxParagraph,
    *,
    description: str | None = None,
) -> None:
    add_edge(
        edges_by_key,
        source=source,
        target=target,
        edge_type=edge_type,
        label=label,
        source_name=source_reference(document, paragraph, ""),
        description=description or paragraph.text,
        status=PLAN_STATUS,
        end_date=PLAN_END_DATE,
    )


def merge_node_source(
    node: dict[str, object],
    document: DocxDocument,
    paragraph: DocxParagraph,
) -> None:
    set_property(
        node,
        "source",
        merge_strings(
            (
                property_value(node, "source"),
                source_reference(document, paragraph, ""),
            )
        ),
    )
    set_property(
        node,
        "description",
        merge_strings((property_value(node, "description"), paragraph.text)),
    )


def section_paragraphs(
    document: DocxDocument,
    start: str,
    ends: tuple[str, ...],
) -> list[DocxParagraph]:
    return section_paragraphs_from_list(list(document.paragraphs), start, ends)


def section_paragraphs_from_list(
    paragraphs: list[DocxParagraph],
    start: str,
    ends: tuple[str, ...],
) -> list[DocxParagraph]:
    start_position = next(
        (
            position
            for position, paragraph in enumerate(paragraphs)
            if paragraph.text.startswith(start)
        ),
        None,
    )
    if start_position is None:
        raise RuntimeError(f"В плане не найден раздел «{start}».")
    end_position = next(
        (
            position
            for position, paragraph in enumerate(paragraphs[start_position + 1 :])
            if paragraph.text.startswith(ends)
        ),
        len(paragraphs) - start_position - 1,
    )
    return paragraphs[start_position : start_position + 1 + end_position]


def factor_paragraphs(segment: list[DocxParagraph]) -> list[DocxParagraph]:
    start = next(
        (
            position
            for position, paragraph in enumerate(segment)
            if paragraph.text.startswith("Ключевыми факторами")
        ),
        None,
    )
    if start is None:
        raise RuntimeError("В разделе программы не найден перечень факторов.")
    end = next(
        (
            position
            for position, paragraph in enumerate(segment[start + 1 :], start + 1)
            if paragraph.text.startswith("Подробнее факторы")
        ),
        len(segment),
    )
    return segment[start + 1 : end]


def find_paragraph(paragraphs: list[DocxParagraph], prefix: str) -> DocxParagraph:
    paragraph = next((item for item in paragraphs if item.text.startswith(prefix)), None)
    if paragraph is None:
        raise RuntimeError(f"В плане не найдена строка «{prefix}».")
    return paragraph


def find_containing(paragraphs: list[DocxParagraph], fragment: str) -> DocxParagraph:
    paragraph = next((item for item in paragraphs if fragment in item.text), None)
    if paragraph is None:
        raise RuntimeError(f"В плане не найден фрагмент «{fragment}».")
    return paragraph


def source_reference(
    document: DocxDocument,
    paragraph: DocxParagraph,
    section: str,
) -> str:
    section_part = f", раздел {section}" if section else ""
    return f"{document.path.name}{section_part}, абзац {paragraph.index}"


def strip_section_number(value: str) -> str:
    return re.sub(r"^\d+(?:\.\d+)*(?:\.[а-я])?\.\s*", "", value).strip(' "')


def project_label(value: str, activity_key: str) -> str:
    if activity_key == "future-technologies":
        return "НИОКР по перспективным технологиям БАС"
    text = value.removeprefix("-").strip().rstrip(".;")
    text = re.sub(r"^(механизма|механизмов)\s+", "", text, flags=re.IGNORECASE)
    words = text.split()
    label = " ".join(words[:18])
    if len(words) > 18:
        label += "…"
    return label[:220].capitalize()


def value_set(value: str) -> set[str]:
    return {item.strip() for item in value.split(";") if item.strip()}


def technology_tokens(value: str) -> set[str]:
    words = re.findall(r"[a-zа-яё0-9]+", value.casefold())
    return {word[:8] for word in words if len(word) >= 5 and word not in TOKEN_STOP_WORDS}
