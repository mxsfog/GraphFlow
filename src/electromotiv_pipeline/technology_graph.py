from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass

from electromotiv_pipeline.docx_reader import DocxDocument, DocxTable
from electromotiv_pipeline.graph_api import normalize_custom_edge, normalize_custom_node

REQUIRED_PROPERTY_KEYS = ("start_date", "end_date", "source", "description", "status")
TECHNOLOGY_SOURCE_TITLE = "Технологические карты: роботы, аккумуляторы, микросхемы"
LANE_ORDER = (
    "Роботы",
    "Аккумуляторы",
    "Микросхемы",
    "Госпрограмма «Наука»",
    "Федеральный проект БАС",
    "Пересечения",
)
NODE_LEVELS = {
    "product": 0,
    "program": 0,
    "technology_block": 1,
    "program_goal": 1,
    "process": 2,
    "indicator": 2,
    "technology": 3,
    "activity": 3,
    "project": 4,
    "expected_result": 5,
}
NODE_SHAPES = {
    "product": "component",
    "program": "component",
    "technology_block": "rounded_rectangle",
    "program_goal": "ellipse",
    "process": "rounded_rectangle",
    "indicator": "document",
    "technology": "rounded_rectangle",
    "activity": "rounded_rectangle",
    "project": "component",
    "expected_result": "document",
}
READINESS_ORDER = {"": 0, "Зелёный": 1, "Оранжевый": 2, "Красный": 3}
LAYOUT_MAX_ROWS = 10
LAYOUT_COLUMN_GAP = 300
LAYOUT_ROW_GAP = 125
LAYOUT_LANE_WIDTH = 3_600
LAYOUT_LANE_HEIGHT = 1_550
LAYOUT_3D_COLUMN_GAP = 110
LAYOUT_3D_ROW_GAP = 32
LAYOUT_3D_LANE_GAP = 220
LAYOUT_LANE_ORIGINS = {
    "Роботы": (0.0, 0.0),
    "Аккумуляторы": (1.0, 0.0),
    "Микросхемы": (0.0, 1.0),
    "Госпрограмма «Наука»": (1.0, 1.0),
    "Федеральный проект БАС": (0.0, 2.0),
    "Пересечения": (0.5, 0.5),
}
LAYOUT_3D_LANES = {
    lane: (index - (len(LANE_ORDER) - 2) / 2) * LAYOUT_3D_LANE_GAP
    for index, lane in enumerate(LANE_ORDER[:-1])
}


@dataclass
class GraphBundle:
    nodes: list[dict[str, object]]
    edges: list[dict[str, object]]


@dataclass(frozen=True)
class DirectionSpec:
    key: str
    label: str
    product_label: str
    table_index: int
    first_process_row: int


DIRECTIONS = (
    DirectionSpec(
        key="robots",
        label="Роботы",
        product_label="Безмаркерный AMR грузоподъёмностью 1500 кг",
        table_index=1,
        first_process_row=1,
    ),
    DirectionSpec(
        key="batteries",
        label="Аккумуляторы",
        product_label="Тяговая аккумуляторная система для робототехники",
        table_index=2,
        first_process_row=2,
    ),
    DirectionSpec(
        key="microchips",
        label="Микросхемы",
        product_label="Специализированная микросхема/SoC для автономной робототехники",
        table_index=3,
        first_process_row=2,
    ),
)


def build_technology_maps(document: DocxDocument) -> GraphBundle:
    if len(document.tables) < 4:
        raise RuntimeError("Документ технологических карт должен содержать четыре таблицы.")
    sources = source_catalog(document)
    nodes_by_id: dict[str, dict[str, object]] = {}
    edges_by_key: dict[tuple[str, str, str], dict[str, object]] = {}

    for spec in DIRECTIONS:
        table = document.tables[spec.table_index]
        validate_technology_table(table, spec.label)
        rows = list(table.rows[spec.first_process_row :])
        if not rows:
            raise RuntimeError(f"Таблица направления «{spec.label}» не содержит процессов.")
        product_description, product_status, product_source = product_metadata(
            document,
            table,
            spec,
            sources,
        )
        product_id = f"product:{spec.key}"
        nodes_by_id[product_id] = graph_node(
            node_id=product_id,
            label=spec.product_label,
            node_type="product",
            direction=spec.label,
            source=product_source,
            description=product_description,
            status=product_status,
        )
        block_rows: dict[str, list[tuple[str, ...]]] = {}
        for row in rows:
            block_rows.setdefault(block_label(row[0]), []).append(row)

        for block_index, (block, related_rows) in enumerate(block_rows.items(), start=1):
            block_id = f"block:{spec.key}:{stable_suffix(block)}"
            block_sources = merge_strings(
                resolve_sources(row[5], sources, document.path.name) for row in related_rows
            )
            block_status = worst_readiness(row[3] for row in related_rows)
            nodes_by_id[block_id] = graph_node(
                node_id=block_id,
                label=block,
                node_type="technology_block",
                direction=spec.label,
                source=block_sources,
                description=f"Технологический блок направления «{spec.label}».",
                status=block_status,
            )
            add_edge(
                edges_by_key,
                source=product_id,
                target=block_id,
                edge_type="has_block",
                label="включает блок",
                source_name=document.path.name,
                description=f"Продукт включает технологический блок «{block}».",
                status=block_status,
            )
            for row_index, row in enumerate(related_rows, start=1):
                add_process_row(
                    nodes_by_id=nodes_by_id,
                    edges_by_key=edges_by_key,
                    spec=spec,
                    block_id=block_id,
                    block_index=block_index,
                    row_index=row_index,
                    row=row,
                    sources=sources,
                    document_name=document.path.name,
                )

        aggregate_status = worst_readiness(
            property_value(node, "status")
            for node in nodes_by_id.values()
            if property_value(node, "direction") == spec.label
            and str(node.get("type")) == "technology"
        )
        set_property(nodes_by_id[product_id], "status", product_status or aggregate_status)

    return GraphBundle(nodes=list(nodes_by_id.values()), edges=list(edges_by_key.values()))


def add_process_row(
    *,
    nodes_by_id: dict[str, dict[str, object]],
    edges_by_key: dict[tuple[str, str, str], dict[str, object]],
    spec: DirectionSpec,
    block_id: str,
    block_index: int,
    row_index: int,
    row: tuple[str, ...],
    sources: dict[str, str],
    document_name: str,
) -> None:
    _, process, technologies, readiness, reason, references = row
    source = resolve_sources(references, sources, document_name)
    status = normalize_readiness(readiness)
    process_id = f"process:{spec.key}:{block_index}:{row_index}"
    nodes_by_id[process_id] = graph_node(
        node_id=process_id,
        label=process,
        node_type="process",
        direction=spec.label,
        source=source,
        description=process,
        status=status,
        extra={"readiness_reason": reason},
    )
    add_edge(
        edges_by_key,
        source=block_id,
        target=process_id,
        edge_type="has_process",
        label="включает процесс",
        source_name=source,
        description=process,
        status=status,
    )

    for technology in split_technologies(technologies):
        technology_id = f"technology:{stable_suffix(technology)}"
        existing = nodes_by_id.get(technology_id)
        if existing is None:
            nodes_by_id[technology_id] = graph_node(
                node_id=technology_id,
                label=technology,
                node_type="technology",
                direction=spec.label,
                source=source,
                description=reason,
                status=status,
                extra={
                    "readiness_reason": reason,
                    "direction_statuses": f"{spec.label}: {status}",
                },
            )
        else:
            merge_technology_context(
                existing,
                direction=spec.label,
                source=source,
                description=reason,
                status=status,
            )
        add_edge(
            edges_by_key,
            source=process_id,
            target=technology_id,
            edge_type="uses_technology",
            label="использует технологию",
            source_name=source,
            description=f"Процесс «{process}» реализуется через технологию «{technology}».",
            status=status,
        )


def graph_node(
    *,
    node_id: str,
    label: str,
    node_type: str,
    direction: str,
    source: str,
    description: str,
    status: str,
    start_date: str = "",
    end_date: str = "",
    extra: dict[str, str] | None = None,
) -> dict[str, object]:
    properties = required_properties(
        start_date=start_date,
        end_date=end_date,
        source=source,
        description=description,
        status=status,
        extra={"direction": direction, **(extra or {})},
    )
    return normalize_custom_node(
        {
            "id": node_id,
            "label": clean_text(label),
            "type": node_type,
            "shape": NODE_SHAPES.get(node_type, "rounded_rectangle"),
            "created_at": iso_date_or_empty(start_date),
            "ended_at": iso_date_or_empty(end_date),
            "properties": properties,
        }
    )


def add_edge(
    edges_by_key: dict[tuple[str, str, str], dict[str, object]],
    *,
    source: str,
    target: str,
    edge_type: str,
    label: str,
    source_name: str,
    description: str,
    status: str = "",
    start_date: str = "",
    end_date: str = "",
) -> None:
    key = (source, target, edge_type)
    if key in edges_by_key:
        return
    edge_id = f"edge:{stable_suffix('|'.join(key))}"
    edges_by_key[key] = {
        "id": edge_id,
        "source": source,
        "target": target,
        "type": edge_type,
        "label": label,
        "properties": required_properties(
            start_date=start_date,
            end_date=end_date,
            source=source_name,
            description=description,
            status=status,
        ),
    }


def normalize_bundle(bundle: GraphBundle) -> GraphBundle:
    nodes = [normalize_custom_node(node) for node in bundle.nodes]
    node_ids = {str(node["id"]) for node in nodes}
    if len(node_ids) != len(nodes):
        raise RuntimeError("Граф содержит повторяющиеся идентификаторы узлов.")
    edges = [normalize_custom_edge(edge, node_ids=node_ids) for edge in bundle.edges]
    if len({str(edge["id"]) for edge in edges}) != len(edges):
        raise RuntimeError("Граф содержит повторяющиеся идентификаторы связей.")
    validate_required_properties(nodes, edges)
    return GraphBundle(nodes=nodes, edges=edges)


def arrange_graph(bundle: GraphBundle) -> GraphBundle:
    nodes_by_lane: dict[str, list[dict[str, object]]] = {}
    for node in bundle.nodes:
        direction = property_value(node, "direction")
        lane = direction if direction in LANE_ORDER else "Пересечения"
        if ";" in direction:
            lane = "Пересечения"
        nodes_by_lane.setdefault(lane, []).append(node)

    for lane in LANE_ORDER:
        lane_nodes = nodes_by_lane.get(lane, [])
        levels: dict[int, list[dict[str, object]]] = {}
        for node in lane_nodes:
            level = NODE_LEVELS.get(str(node.get("type") or ""), 3)
            levels.setdefault(level, []).append(node)
        for level_nodes in levels.values():
            level_nodes.sort(key=lambda item: str(item.get("label") or "").casefold())

        level_offsets: dict[int, int] = {}
        next_column = 0
        for level in sorted(levels):
            level_offsets[level] = next_column
            column_count = max(1, (len(levels[level]) + LAYOUT_MAX_ROWS - 1) // LAYOUT_MAX_ROWS)
            next_column += column_count + 1

        for level in sorted(levels):
            level_nodes = levels[level]
            visible_rows = min(len(level_nodes), LAYOUT_MAX_ROWS)
            for index, node in enumerate(level_nodes):
                local_column = level_offsets[level] + index // LAYOUT_MAX_ROWS
                local_row = index % LAYOUT_MAX_ROWS
                origin_x, origin_y, origin_z = layout_origin(
                    property_value(node, "direction"),
                    lane,
                )
                x = round(origin_x + local_column * LAYOUT_COLUMN_GAP)
                y = round(origin_y + local_row * LAYOUT_ROW_GAP)
                node["x"] = x
                node["y"] = y
                node["position3d"] = {
                    "x": float(local_column * LAYOUT_3D_COLUMN_GAP),
                    "y": float((local_row - (visible_rows - 1) / 2) * LAYOUT_3D_ROW_GAP),
                    "z": float(origin_z),
                }
    return bundle


def layout_origin(direction: str, lane: str) -> tuple[float, float, float]:
    directions = [
        item
        for item in split_values(direction)
        if item in LAYOUT_LANE_ORIGINS and item != "Пересечения"
    ]
    if not directions:
        directions = [lane]
    origins = [LAYOUT_LANE_ORIGINS[item] for item in directions]
    x = sum(origin[0] for origin in origins) / len(origins) * LAYOUT_LANE_WIDTH
    y = sum(origin[1] for origin in origins) / len(origins) * LAYOUT_LANE_HEIGHT
    z_values = [LAYOUT_3D_LANES.get(item, 0.0) for item in directions]
    return x, y, sum(z_values) / len(z_values)


def technology_catalog(bundle: GraphBundle) -> list[dict[str, str]]:
    allowed = {"product", "technology_block", "technology"}
    return [
        {
            "id": str(node["id"]),
            "label": str(node["label"]),
            "type": str(node["type"]),
            "direction": property_value(node, "direction"),
            "status": property_value(node, "status"),
        }
        for node in bundle.nodes
        if str(node.get("type") or "") in allowed
    ]


def required_properties(
    *,
    start_date: str,
    end_date: str,
    source: str,
    description: str,
    status: str,
    extra: dict[str, str] | None = None,
) -> list[dict[str, str]]:
    values = {
        "start_date": clean_text(start_date),
        "end_date": clean_text(end_date),
        "source": clean_text(source)[:2000],
        "description": clean_text(description)[:2000],
        "status": clean_text(status),
        **{key: clean_text(value)[:2000] for key, value in (extra or {}).items()},
    }
    return [{"key": key, "value": value} for key, value in values.items()]


def validate_required_properties(
    nodes: list[dict[str, object]],
    edges: list[dict[str, object]],
) -> None:
    for kind, items in (("узел", nodes), ("связь", edges)):
        for item in items:
            keys = {
                str(prop.get("key") or "")
                for prop in item.get("properties", [])
                if isinstance(prop, dict)
            }
            missing = set(REQUIRED_PROPERTY_KEYS) - keys
            if missing:
                raise RuntimeError(
                    f"{kind.capitalize()} {item.get('id')} не содержит поле {sorted(missing)[0]}."
                )


def property_value(item: dict[str, object], key: str) -> str:
    for prop in item.get("properties", []):
        if isinstance(prop, dict) and str(prop.get("key") or "") == key:
            return str(prop.get("value") or "")
    return ""


def set_property(item: dict[str, object], key: str, value: str) -> None:
    properties = item.get("properties")
    if not isinstance(properties, list):
        properties = []
        item["properties"] = properties
    for prop in properties:
        if isinstance(prop, dict) and str(prop.get("key") or "") == key:
            prop["value"] = clean_text(value)[:2000]
            return
    properties.append({"key": key, "value": clean_text(value)[:2000]})


def merge_technology_context(
    node: dict[str, object],
    *,
    direction: str,
    source: str,
    description: str,
    status: str,
) -> None:
    directions = split_values(property_value(node, "direction"))
    directions.add(direction)
    set_property(node, "direction", "; ".join(sorted(directions)))
    set_property(
        node,
        "source",
        merge_strings((property_value(node, "source"), source)),
    )
    set_property(
        node,
        "description",
        merge_strings((property_value(node, "description"), description)),
    )
    current_status = property_value(node, "status")
    set_property(node, "status", worst_readiness((current_status, status)))
    statuses = property_value(node, "direction_statuses")
    status_entry = f"{direction}: {status}"
    set_property(
        node,
        "direction_statuses",
        merge_strings((statuses, status_entry), separator="; "),
    )


def validate_technology_table(table: DocxTable, direction: str) -> None:
    if len(table.rows) < 2:
        raise RuntimeError(f"Таблица направления «{direction}» пуста.")
    expected = (
        "блок",
        "процесс создания",
        "технологии создания",
        "готовность",
        "обоснование",
        "источники",
    )
    header = tuple(clean_text(value).casefold() for value in table.rows[0])
    if header != expected:
        raise RuntimeError(f"Таблица направления «{direction}» имеет неизвестную структуру.")
    if any(len(row) != len(expected) for row in table.rows[1:]):
        raise RuntimeError(f"Таблица направления «{direction}» содержит неполную строку.")


def product_metadata(
    document: DocxDocument,
    table: DocxTable,
    spec: DirectionSpec,
    sources: dict[str, str],
) -> tuple[str, str, str]:
    if spec.key == "robots":
        description = next(
            (
                paragraph.text.removeprefix("Конкретная цель:").strip()
                for paragraph in document.paragraphs
                if paragraph.text.startswith("Конкретная цель:")
            ),
            spec.product_label,
        )
        status = ""
        references = "R1, R12"
    else:
        product_row = table.rows[1]
        description = merge_strings((product_row[1], product_row[2]), separator=" ")
        status = normalize_readiness(product_row[3])
        references = product_row[5]
    return (
        description,
        status,
        resolve_sources(references, sources, document.path.name),
    )


def source_catalog(document: DocxDocument) -> dict[str, str]:
    result: dict[str, str] = {}
    pattern = re.compile(r"^\[?(R\d+)\]?\s+(.+)$", re.IGNORECASE)
    for paragraph in document.paragraphs:
        match = pattern.match(paragraph.text)
        if match:
            result[match.group(1).upper()] = match.group(2).strip()
    return result


def resolve_sources(references: str, catalog: dict[str, str], document_name: str) -> str:
    keys = re.findall(r"R\d+", references.upper())
    details = [f"{key}: {catalog[key]}" for key in keys if key in catalog]
    return merge_strings((document_name, *details))


def block_label(value: str) -> str:
    return clean_text(value.split("/", 1)[0])


def split_technologies(value: str) -> list[str]:
    result = [clean_text(item).rstrip(".") for item in value.split(";")]
    return [item for item in result if item]


def normalize_readiness(value: str) -> str:
    normalized = clean_text(value).casefold().replace("ё", "е")
    if normalized.startswith("зелен"):
        return "Зелёный"
    if normalized.startswith("оранж"):
        return "Оранжевый"
    if normalized.startswith("красн"):
        return "Красный"
    return clean_text(value)


def worst_readiness(values) -> str:
    normalized = [normalize_readiness(str(value or "")) for value in values]
    return max(normalized, key=lambda value: READINESS_ORDER.get(value, 0), default="")


def stable_suffix(value: str) -> str:
    normalized = canonical_text(value).encode("utf-8")
    return hashlib.sha256(normalized).hexdigest()[:16]


def canonical_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold().replace("ё", "е")
    return re.sub(r"\s+", " ", normalized).strip(" .")


def clean_text(value: str) -> str:
    return " ".join(str(value or "").split())


def merge_strings(values, *, separator: str = " | ") -> str:
    unique: list[str] = []
    for value in values:
        cleaned = clean_text(str(value or ""))
        if cleaned and cleaned not in unique:
            unique.append(cleaned)
    return separator.join(unique)


def split_values(value: str) -> set[str]:
    return {item.strip() for item in value.split(";") if item.strip()}


def iso_date_or_empty(value: str) -> str:
    cleaned = clean_text(value)
    return f"{cleaned}T00:00:00Z" if re.fullmatch(r"\d{4}-\d{2}-\d{2}", cleaned) else ""
