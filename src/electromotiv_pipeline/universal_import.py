from __future__ import annotations

import json
import re
from collections import defaultdict, deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from electromotiv_pipeline.docx_reader import DocxBlock, DocxDocument, DocxParagraph, DocxTable
from electromotiv_pipeline.technology_graph import (
    GraphBundle,
    add_edge,
    canonical_text,
    clean_text,
    graph_node,
    merge_strings,
    normalize_bundle,
    normalize_readiness,
    property_value,
    resolve_sources,
    set_property,
    source_catalog,
    stable_suffix,
)

PROFILE_SCHEMA_VERSION = 1
DEFAULT_STATUS_ORDER = ("", "Зелёный", "Оранжевый", "Красный")
DEFAULT_NODE_SHAPES = {
    "document": "document",
    "section": "document",
    "paragraph": "rounded_rectangle",
    "list_item": "rounded_rectangle",
    "table": "component",
    "table_row": "rounded_rectangle",
}
SUPPORTED_PROFILE_SHAPES = {
    "rounded_rectangle",
    "document",
    "diamond",
    "ellipse",
    "circle",
    "actor",
    "component",
    "class",
    "database",
}
NON_HIERARCHICAL_EDGES = {
    "follow",
    "todo",
    "supports",
    "develops",
    "intersects_with",
    "properties",
}
MAX_PROFILE_BYTES = 1_000_000
MAX_STRUCTURAL_NODES = 500
LAYOUT_ROWS = 11
LAYOUT_COLUMN_GAP = 320
LAYOUT_ROW_GAP = 135
LAYOUT_LANE_WIDTH = 3_200
LAYOUT_LANE_HEIGHT = 1_750


@dataclass(frozen=True)
class ImportProfile:
    profile_id: str
    schema_version: int
    document_rules: tuple[dict[str, object], ...]
    node_shapes: dict[str, str]
    status_order: tuple[str, ...]
    topics: dict[str, tuple[str, ...]]
    cross_links: tuple[dict[str, object], ...]
    token_stop_words: frozenset[str]


@dataclass(frozen=True)
class UniversalImportResult:
    graph: GraphBundle
    profile_id: str
    diagnostics: tuple[dict[str, object], ...]


def load_import_profile(path: Path | None) -> ImportProfile:
    if path is None:
        return default_import_profile()
    if not path.is_file():
        raise RuntimeError(f"Профиль импорта не найден: {path}")
    if path.stat().st_size > MAX_PROFILE_BYTES:
        raise RuntimeError(f"Профиль импорта превышает лимит {MAX_PROFILE_BYTES} байт: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Не удалось прочитать профиль импорта: {path}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("Профиль импорта должен быть JSON-объектом.")
    schema_version = integer_field(payload, "schema_version")
    if schema_version != PROFILE_SCHEMA_VERSION:
        raise RuntimeError(
            f"Версия профиля {schema_version} не поддерживается; ожидается "
            f"{PROFILE_SCHEMA_VERSION}."
        )
    profile_id = string_field(payload, "profile_id")
    document_rules = tuple(mapping_items(payload.get("document_rules"), "document_rules"))
    node_shapes = {
        str(key): str(value)
        for key, value in mapping_field(payload, "node_shapes", required=False).items()
    }
    status_order = tuple(string_items(payload.get("status_order", DEFAULT_STATUS_ORDER)))
    topics = {
        str(name): tuple(string_items(values))
        for name, values in mapping_field(payload, "topics", required=False).items()
    }
    cross_links = tuple(mapping_items(payload.get("cross_links", []), "cross_links"))
    token_stop_words = frozenset(
        canonical_text(item) for item in string_items(payload.get("token_stop_words", []))
    )
    profile = ImportProfile(
        profile_id=profile_id,
        schema_version=schema_version,
        document_rules=document_rules,
        node_shapes={**DEFAULT_NODE_SHAPES, **node_shapes},
        status_order=status_order or DEFAULT_STATUS_ORDER,
        topics=topics,
        cross_links=cross_links,
        token_stop_words=token_stop_words,
    )
    validate_profile(profile)
    return profile


def default_import_profile() -> ImportProfile:
    return ImportProfile(
        profile_id="auto-structure",
        schema_version=PROFILE_SCHEMA_VERSION,
        document_rules=(),
        node_shapes=dict(DEFAULT_NODE_SHAPES),
        status_order=DEFAULT_STATUS_ORDER,
        topics={},
        cross_links=(),
        token_stop_words=frozenset(),
    )


def validate_profile(profile: ImportProfile) -> None:
    roles: set[str] = set()
    for rule in profile.document_rules:
        role = string_field(rule, "role")
        mode = string_field(rule, "mode")
        if role in roles:
            raise RuntimeError(f"Профиль содержит повторяющуюся роль документа: {role}")
        if mode not in {"table_hierarchy", "section_hierarchy", "structure"}:
            raise RuntimeError(f"Роль {role} содержит неизвестный режим: {mode}")
        roles.add(role)
        validate_match_rule(mapping_field(rule, "match"), role)
        if mode == "table_hierarchy":
            table_rules = mapping_items(rule.get("table_rules"), f"{role}.table_rules")
            if not table_rules:
                raise RuntimeError(f"Роль {role} не содержит table_rules.")
            for table_rule in table_rules:
                validate_table_rule(table_rule, role)
        if mode == "section_hierarchy":
            groups = mapping_items(rule.get("groups"), f"{role}.groups")
            if not groups:
                raise RuntimeError(f"Роль {role} не содержит groups.")
            for group in groups:
                validate_section_group(group, role)
    for pattern in profile.token_stop_words:
        if not pattern:
            raise RuntimeError("token_stop_words содержит пустое значение.")
    unknown_shapes = set(profile.node_shapes.values()) - SUPPORTED_PROFILE_SHAPES
    if unknown_shapes:
        raise RuntimeError(f"Профиль содержит неизвестную форму: {sorted(unknown_shapes)[0]}")


def validate_match_rule(match: Mapping[str, object], role: str) -> None:
    headers = tuple(string_items(match.get("required_table_headers", [])))
    patterns = tuple(string_items(match.get("required_paragraph_patterns", [])))
    if not headers and not patterns:
        raise RuntimeError(f"Роль {role} не содержит критериев сопоставления документа.")
    compile_patterns(patterns, f"{role}.match")


def validate_table_rule(rule: Mapping[str, object], role: str) -> None:
    string_field(rule, "id")
    headers = tuple(string_items(rule.get("required_headers")))
    if not headers:
        raise RuntimeError(f"Табличное правило роли {role} не содержит required_headers.")
    root = mapping_field(rule, "root")
    string_field(root, "type")
    levels = mapping_items(rule.get("levels"), f"{role}.levels")
    if not levels:
        raise RuntimeError(f"Табличное правило роли {role} не содержит levels.")
    for level in levels:
        for field in ("column", "type", "edge_type", "edge_label"):
            string_field(level, field)


def validate_section_group(group: Mapping[str, object], role: str) -> None:
    for field in ("id", "label", "type", "direction"):
        string_field(group, field)
    sections = mapping_items(group.get("sections"), f"{role}.sections")
    if not sections:
        raise RuntimeError(f"Группа роли {role} не содержит sections.")
    for section in sections:
        compile_patterns(
            (string_field(section, "start"), string_field(section, "end")),
            f"{role}.sections",
        )
    for rule in mapping_items(group.get("node_rules", []), f"{role}.node_rules"):
        compile_patterns((string_field(rule, "pattern"),), f"{role}.node_rules")
        string_field(rule, "type")
    for rule in mapping_items(group.get("range_rules", []), f"{role}.range_rules"):
        compile_patterns(
            (string_field(rule, "start"), string_field(rule, "end")),
            f"{role}.range_rules",
        )
        string_field(rule, "type")


def build_universal_graph(
    documents: Sequence[DocxDocument],
    profile: ImportProfile,
) -> UniversalImportResult:
    if not documents:
        raise RuntimeError("Для импорта требуется хотя бы один DOCX-документ.")
    nodes_by_id: dict[str, dict[str, object]] = {}
    edges_by_key: dict[tuple[str, str, str], dict[str, object]] = {}
    diagnostics: list[dict[str, object]] = []
    assignments = assign_document_rules(documents, profile.document_rules)

    for document, rule in assignments:
        mode = str(rule.get("mode") or "structure") if rule else "structure"
        role = str(rule.get("role") or "auto-structure") if rule else "auto-structure"
        before_nodes = len(nodes_by_id)
        before_edges = len(edges_by_key)
        if mode == "table_hierarchy":
            build_table_hierarchies(
                document=document,
                rule=rule,
                profile=profile,
                nodes_by_id=nodes_by_id,
                edges_by_key=edges_by_key,
            )
        elif mode == "section_hierarchy":
            build_section_hierarchies(
                document=document,
                rule=rule,
                profile=profile,
                nodes_by_id=nodes_by_id,
                edges_by_key=edges_by_key,
            )
        else:
            build_structural_graph(
                document=document,
                profile=profile,
                nodes_by_id=nodes_by_id,
                edges_by_key=edges_by_key,
                options=rule or {},
            )
        diagnostics.append(
            {
                "file": document.path.name,
                "role": role,
                "mode": mode,
                "nodes_added": len(nodes_by_id) - before_nodes,
                "edges_added": len(edges_by_key) - before_edges,
            }
        )

    apply_profile_shapes(nodes_by_id.values(), profile.node_shapes)
    annotate_topics(nodes_by_id.values(), profile)
    add_configured_cross_links(
        nodes_by_id=nodes_by_id,
        edges_by_key=edges_by_key,
        profile=profile,
    )
    graph = normalize_bundle(
        arrange_universal_graph(
            GraphBundle(nodes=list(nodes_by_id.values()), edges=list(edges_by_key.values()))
        )
    )
    return UniversalImportResult(
        graph=graph,
        profile_id=profile.profile_id,
        diagnostics=tuple(diagnostics),
    )


def assign_document_rules(
    documents: Sequence[DocxDocument],
    rules: Sequence[Mapping[str, object]],
) -> list[tuple[DocxDocument, dict[str, object] | None]]:
    if not rules:
        return [(document, None) for document in documents]
    available = set(range(len(documents)))
    assignments: list[tuple[DocxDocument, dict[str, object] | None]] = []
    for rule in rules:
        candidates = sorted(
            (
                (document_match_score(documents[index], mapping_field(rule, "match")), index)
                for index in available
            ),
            reverse=True,
        )
        score, index = candidates[0] if candidates else (0, -1)
        if score <= 0:
            if bool(rule.get("required", True)):
                raise RuntimeError(
                    f"Не найден документ для обязательной роли {string_field(rule, 'role')}."
                )
            continue
        assignments.append((documents[index], dict(rule)))
        available.remove(index)
    assignments.extend((documents[index], None) for index in sorted(available))
    return assignments


def document_match_score(document: DocxDocument, match: Mapping[str, object]) -> int:
    score = 0
    required_headers = tuple(string_items(match.get("required_table_headers", [])))
    if required_headers:
        if not any(table_header_matches(table, required_headers) for table in document.tables):
            return 0
        score += 10 + len(required_headers)
    for pattern in string_items(match.get("required_paragraph_patterns", [])):
        if not any(regex_search(pattern, paragraph.text) for paragraph in document.paragraphs):
            return 0
        score += 5
    return score


def build_table_hierarchies(
    *,
    document: DocxDocument,
    rule: Mapping[str, object],
    profile: ImportProfile,
    nodes_by_id: dict[str, dict[str, object]],
    edges_by_key: dict[tuple[str, str, str], dict[str, object]],
) -> None:
    table_rules = mapping_items(rule.get("table_rules"), "table_rules")
    latest_heading: DocxParagraph | None = None
    context: list[DocxParagraph] = []
    matched = 0
    for block in document_blocks(document):
        if block.kind == "paragraph" and block.paragraph is not None:
            paragraph = block.paragraph
            if heading_level(paragraph) > 0:
                latest_heading = paragraph
                context = []
            else:
                context.append(paragraph)
            continue
        if block.kind != "table" or block.table is None:
            continue
        table_rule = next(
            (
                candidate
                for candidate in table_rules
                if table_header_matches(
                    block.table,
                    tuple(string_items(candidate.get("required_headers"))),
                )
            ),
            None,
        )
        if table_rule is None:
            continue
        if latest_heading is None:
            raise RuntimeError(
                f"Перед таблицей {matched + 1} в {document.path.name} не найден заголовок."
            )
        build_table_hierarchy(
            document=document,
            table=block.table,
            heading=latest_heading,
            context=context,
            rule=table_rule,
            profile=profile,
            nodes_by_id=nodes_by_id,
            edges_by_key=edges_by_key,
        )
        matched += 1
    if matched == 0:
        raise RuntimeError(f"В документе {document.path.name} не найдены подходящие таблицы.")


def build_table_hierarchy(
    *,
    document: DocxDocument,
    table: DocxTable,
    heading: DocxParagraph,
    context: Sequence[DocxParagraph],
    rule: Mapping[str, object],
    profile: ImportProfile,
    nodes_by_id: dict[str, dict[str, object]],
    edges_by_key: dict[tuple[str, str, str], dict[str, object]],
) -> None:
    if not table.rows:
        return
    header = {canonical_text(value): index for index, value in enumerate(table.rows[0])}
    root_rule = mapping_field(rule, "root")
    direction = extract_heading_value(
        heading.text,
        str(root_rule.get("direction_from") or "before_colon"),
    )
    direction = direction_alias(direction, root_rule.get("direction_aliases", []))
    root_label = extract_heading_value(
        heading.text,
        str(root_rule.get("label_from") or "after_colon"),
    )
    root_ids = mapping_field(root_rule, "id_by_direction", required=False)
    topics_by_direction = mapping_field(root_rule, "topics_by_direction", required=False)
    direction_topics = string_items(topics_by_direction.get(direction, []))
    root_type = string_field(root_rule, "type")
    root_id = str(root_ids.get(direction) or f"{root_type}:{stable_suffix(root_label)}")
    description = context_description(context, str(root_rule.get("description_prefix") or ""))
    root = graph_node(
        node_id=root_id,
        label=root_label,
        node_type=root_type,
        direction=direction,
        source=document.path.name,
        description=description or heading.text,
        status=str(root_rule.get("status") or ""),
        start_date=str(root_rule.get("start_date") or ""),
        end_date=str(root_rule.get("end_date") or ""),
        extra={
            "profile_rule": string_field(rule, "id"),
            "topics": "; ".join(direction_topics),
        },
    )
    upsert_node(nodes_by_id, root, profile.status_order)
    levels = mapping_items(rule.get("levels"), "levels")
    property_columns = mapping_field(rule, "property_columns", required=False)
    catalog = source_catalog(document)

    for row_index, row in enumerate(table.rows[1:], start=1):
        if should_skip_row(row, header, rule.get("skip_rows", [])):
            continue
        row_values = {
            key: table_value(row, header, str(column)) for key, column in property_columns.items()
        }
        status = normalize_readiness(row_values.get("status", ""))
        source = resolve_sources(row_values.get("source", ""), catalog, document.path.name)
        description = row_values.get("description", "")
        merge_node_status(nodes_by_id[root_id], status, profile.status_order)
        parents = [root_id]
        for level in levels:
            raw_value = table_value(row, header, string_field(level, "column"))
            values = transform_values(raw_value, level)
            if not values:
                parents = []
                break
            next_parents: list[str] = []
            for parent_id in parents:
                for value in values:
                    node_type = string_field(level, "type")
                    node_id = hierarchy_node_id(
                        node_type=node_type,
                        label=value,
                        parent_id=parent_id,
                        row_index=row_index,
                        deduplicate=str(level.get("deduplicate") or "parent"),
                    )
                    node = graph_node(
                        node_id=node_id,
                        label=value,
                        node_type=node_type,
                        direction=direction,
                        source=source,
                        description=description or value,
                        status=status,
                        start_date=row_values.get("start_date", ""),
                        end_date=row_values.get("end_date", ""),
                        extra={
                            "profile_rule": string_field(rule, "id"),
                            "topics": "; ".join(direction_topics),
                        },
                    )
                    upsert_node(nodes_by_id, node, profile.status_order)
                    add_edge(
                        edges_by_key,
                        source=parent_id,
                        target=node_id,
                        edge_type=string_field(level, "edge_type"),
                        label=string_field(level, "edge_label"),
                        source_name=source,
                        description=description or value,
                        status=status,
                        start_date=row_values.get("start_date", ""),
                        end_date=row_values.get("end_date", ""),
                    )
                    next_parents.append(node_id)
            parents = next_parents


def build_section_hierarchies(
    *,
    document: DocxDocument,
    rule: Mapping[str, object],
    profile: ImportProfile,
    nodes_by_id: dict[str, dict[str, object]],
    edges_by_key: dict[tuple[str, str, str], dict[str, object]],
) -> None:
    groups = mapping_items(rule.get("groups"), "groups")
    for group in groups:
        build_section_group(
            document=document,
            group=group,
            profile=profile,
            nodes_by_id=nodes_by_id,
            edges_by_key=edges_by_key,
        )


def build_section_group(
    *,
    document: DocxDocument,
    group: Mapping[str, object],
    profile: ImportProfile,
    nodes_by_id: dict[str, dict[str, object]],
    edges_by_key: dict[tuple[str, str, str], dict[str, object]],
) -> None:
    group_id = string_field(group, "id")
    direction = string_field(group, "direction")
    group_node = graph_node(
        node_id=group_id,
        label=string_field(group, "label"),
        node_type=string_field(group, "type"),
        direction=direction,
        source=document.path.name,
        description=str(group.get("description") or string_field(group, "label")),
        status=str(group.get("status") or ""),
        start_date=str(group.get("start_date") or ""),
        end_date=str(group.get("end_date") or ""),
        extra={"topics": "; ".join(string_items(group.get("topics", [])))},
    )
    upsert_node(nodes_by_id, group_node, profile.status_order)
    paragraphs = list(document.paragraphs)
    matched_sections = 0
    for section in mapping_items(group.get("sections"), "sections"):
        segment = paragraph_segment(
            paragraphs,
            start_pattern=string_field(section, "start"),
            end_pattern=string_field(section, "end"),
        )
        if not segment:
            continue
        matched_sections += 1
        section_heading = segment[0]
        section_type = str(section.get("type") or group.get("section_type") or "section")
        section_label = transform_label(
            section_heading.text,
            str(section.get("label_transform") or "strip_section"),
        )
        section_id = f"{section_type}:{stable_suffix(group_id + '|' + section_label)}"
        section_node = graph_node(
            node_id=section_id,
            label=section_label,
            node_type=section_type,
            direction=direction,
            source=paragraph_source(document, section_heading),
            description=section_heading.text,
            status=str(group.get("status") or ""),
            start_date=str(group.get("start_date") or ""),
            end_date=str(group.get("end_date") or ""),
        )
        upsert_node(nodes_by_id, section_node, profile.status_order)
        add_edge(
            edges_by_key,
            source=group_id,
            target=section_id,
            edge_type=str(section.get("edge_type") or "include"),
            label=str(section.get("edge_label") or "включает раздел"),
            source_name=paragraph_source(document, section_heading),
            description=section_heading.text,
            status=str(group.get("status") or ""),
            start_date=str(group.get("start_date") or ""),
            end_date=str(group.get("end_date") or ""),
        )
        build_section_nodes(
            document=document,
            segment=segment[1:],
            group=group,
            group_id=group_id,
            section_id=section_id,
            direction=direction,
            profile=profile,
            nodes_by_id=nodes_by_id,
            edges_by_key=edges_by_key,
        )
    if matched_sections == 0:
        raise RuntimeError(
            f"Для группы {group_id} в документе {document.path.name} не найден ни один раздел."
        )


def build_section_nodes(
    *,
    document: DocxDocument,
    segment: Sequence[DocxParagraph],
    group: Mapping[str, object],
    group_id: str,
    section_id: str,
    direction: str,
    profile: ImportProfile,
    nodes_by_id: dict[str, dict[str, object]],
    edges_by_key: dict[tuple[str, str, str], dict[str, object]],
) -> None:
    node_rules = mapping_items(group.get("node_rules", []), "node_rules")
    range_rules = mapping_items(group.get("range_rules", []), "range_rules")
    active_range: Mapping[str, object] | None = None
    latest_by_type: dict[str, str] = {}
    previous_by_rule: dict[str, str] = {}

    for paragraph in segment:
        ending = next(
            (
                rule
                for rule in range_rules
                if active_range is rule and regex_search(string_field(rule, "end"), paragraph.text)
            ),
            None,
        )
        if ending is not None:
            active_range = None
            continue
        starting = next(
            (
                rule
                for rule in range_rules
                if regex_search(string_field(rule, "start"), paragraph.text)
            ),
            None,
        )
        if starting is not None:
            active_range = starting
            continue
        matched_rule = next(
            (
                rule
                for rule in node_rules
                if regex_search(string_field(rule, "pattern"), paragraph.text)
            ),
            None,
        )
        effective_rule = matched_rule or active_range
        if effective_rule is None or not paragraph.text.strip(" -–—"):
            continue
        node_type = string_field(effective_rule, "type")
        label = transform_label(
            paragraph.text,
            str(effective_rule.get("label_transform") or "truncate"),
        )
        deduplicate = str(effective_rule.get("deduplicate") or "section")
        node_id = section_node_id(
            node_type=node_type,
            label=label,
            group_id=group_id,
            section_id=section_id,
            paragraph_index=paragraph.index,
            deduplicate=deduplicate,
        )
        parent_id = resolve_section_parent(
            str(effective_rule.get("parent") or "section"),
            group_id=group_id,
            section_id=section_id,
            latest_by_type=latest_by_type,
        )
        source = paragraph_source(document, paragraph)
        node = graph_node(
            node_id=node_id,
            label=label,
            node_type=node_type,
            direction=direction,
            source=source,
            description=paragraph.text,
            status=str(effective_rule.get("status") or group.get("status") or ""),
            start_date=str(effective_rule.get("start_date") or group.get("start_date") or ""),
            end_date=str(effective_rule.get("end_date") or group.get("end_date") or ""),
        )
        upsert_node(nodes_by_id, node, profile.status_order)
        add_section_rule_edges(
            edges_by_key=edges_by_key,
            rule=effective_rule,
            parent_id=parent_id,
            group_id=group_id,
            node_id=node_id,
            source=source,
            description=paragraph.text,
            status=str(effective_rule.get("status") or group.get("status") or ""),
            start_date=str(effective_rule.get("start_date") or group.get("start_date") or ""),
            end_date=str(effective_rule.get("end_date") or group.get("end_date") or ""),
        )
        rule_key = str(effective_rule.get("id") or node_type)
        if bool(effective_rule.get("sequence")) and rule_key in previous_by_rule:
            add_edge(
                edges_by_key,
                source=previous_by_rule[rule_key],
                target=node_id,
                edge_type="follow",
                label="следует",
                source_name=source,
                description="Последовательность элементов в исходном документе.",
            )
        previous_by_rule[rule_key] = node_id
        latest_by_type[node_type] = node_id


def add_section_rule_edges(
    *,
    edges_by_key: dict[tuple[str, str, str], dict[str, object]],
    rule: Mapping[str, object],
    parent_id: str,
    group_id: str,
    node_id: str,
    source: str,
    description: str,
    status: str,
    start_date: str,
    end_date: str,
) -> None:
    edge_specs = mapping_items(rule.get("edges", []), "edges")
    if not edge_specs:
        edge_specs = (
            {
                "from": "parent",
                "type": str(rule.get("edge_type") or "include"),
                "label": str(rule.get("edge_label") or "включает"),
            },
        )
    for edge_spec in edge_specs:
        source_id = group_id if edge_spec.get("from") == "group" else parent_id
        add_edge(
            edges_by_key,
            source=source_id,
            target=node_id,
            edge_type=string_field(edge_spec, "type"),
            label=str(edge_spec.get("label") or ""),
            source_name=source,
            description=description,
            status=status,
            start_date=start_date,
            end_date=end_date,
        )


def build_structural_graph(
    *,
    document: DocxDocument,
    profile: ImportProfile,
    nodes_by_id: dict[str, dict[str, object]],
    edges_by_key: dict[tuple[str, str, str], dict[str, object]],
    options: Mapping[str, object],
) -> None:
    root_id = f"document:{stable_suffix(document.path.name)}"
    direction = str(options.get("direction") or document.path.stem)
    root = graph_node(
        node_id=root_id,
        label=str(options.get("title") or document.path.stem),
        node_type="document",
        direction=direction,
        source=document.path.name,
        description=f"Структурный импорт документа {document.path.name}.",
        status="",
    )
    upsert_node(nodes_by_id, root, profile.status_order)
    include_paragraphs = bool(options.get("include_paragraphs", True))
    max_nodes = int(options.get("max_nodes") or MAX_STRUCTURAL_NODES)
    heading_stack: list[tuple[int, str]] = []

    for block in document_blocks(document):
        if len(nodes_by_id) >= max_nodes:
            break
        if block.kind == "paragraph" and block.paragraph is not None:
            paragraph = block.paragraph
            level = heading_level(paragraph)
            if level > 0:
                while heading_stack and heading_stack[-1][0] >= level:
                    heading_stack.pop()
                parent_id = heading_stack[-1][1] if heading_stack else root_id
                node_id = f"section:{stable_suffix(root_id + '|' + paragraph.text)}"
                node = graph_node(
                    node_id=node_id,
                    label=transform_label(paragraph.text, "strip_section"),
                    node_type="section",
                    direction=direction,
                    source=paragraph_source(document, paragraph),
                    description=paragraph.text,
                    status="",
                )
                upsert_node(nodes_by_id, node, profile.status_order)
                add_edge(
                    edges_by_key,
                    source=parent_id,
                    target=node_id,
                    edge_type="include",
                    label="включает раздел",
                    source_name=paragraph_source(document, paragraph),
                    description=paragraph.text,
                )
                heading_stack.append((level, node_id))
            elif include_paragraphs:
                parent_id = heading_stack[-1][1] if heading_stack else root_id
                node_type = (
                    "list_item" if paragraph.text.lstrip().startswith(("-", "•")) else "paragraph"
                )
                node_id = f"{node_type}:{stable_suffix(root_id + '|' + str(paragraph.index))}"
                node = graph_node(
                    node_id=node_id,
                    label=transform_label(paragraph.text, "strip_bullet"),
                    node_type=node_type,
                    direction=direction,
                    source=paragraph_source(document, paragraph),
                    description=paragraph.text,
                    status="",
                )
                upsert_node(nodes_by_id, node, profile.status_order)
                add_edge(
                    edges_by_key,
                    source=parent_id,
                    target=node_id,
                    edge_type="include",
                    label="содержит",
                    source_name=paragraph_source(document, paragraph),
                    description=paragraph.text,
                )
        elif block.kind == "table" and block.table is not None:
            parent_id = heading_stack[-1][1] if heading_stack else root_id
            add_structural_table(
                document=document,
                table=block.table,
                block_index=block.index,
                parent_id=parent_id,
                direction=direction,
                profile=profile,
                nodes_by_id=nodes_by_id,
                edges_by_key=edges_by_key,
                max_nodes=max_nodes,
            )


def add_structural_table(
    *,
    document: DocxDocument,
    table: DocxTable,
    block_index: int,
    parent_id: str,
    direction: str,
    profile: ImportProfile,
    nodes_by_id: dict[str, dict[str, object]],
    edges_by_key: dict[tuple[str, str, str], dict[str, object]],
    max_nodes: int,
) -> None:
    if not table.rows:
        return
    table_id = f"table:{stable_suffix(document.path.name + '|' + str(block_index))}"
    headers = [
        clean_text(value) or f"column_{index + 1}" for index, value in enumerate(table.rows[0])
    ]
    table_node = graph_node(
        node_id=table_id,
        label=f"Таблица: {', '.join(headers[:3])}",
        node_type="table",
        direction=direction,
        source=document.path.name,
        description=f"Таблица из документа {document.path.name}.",
        status="",
    )
    upsert_node(nodes_by_id, table_node, profile.status_order)
    add_edge(
        edges_by_key,
        source=parent_id,
        target=table_id,
        edge_type="include",
        label="содержит таблицу",
        source_name=document.path.name,
        description=str(table_node["label"]),
    )
    for row_index, row in enumerate(table.rows[1:], start=1):
        if len(nodes_by_id) >= max_nodes:
            break
        values = [clean_text(value) for value in row]
        if not any(values):
            continue
        row_id = f"table_row:{stable_suffix(table_id + '|' + str(row_index))}"
        properties = {
            headers[index]: value
            for index, value in enumerate(values[:50])
            if value and index < len(headers)
        }
        row_node = graph_node(
            node_id=row_id,
            label=next((value for value in values if value), f"Строка {row_index}"),
            node_type="table_row",
            direction=direction,
            source=document.path.name,
            description=" | ".join(values),
            status="",
            extra=properties,
        )
        upsert_node(nodes_by_id, row_node, profile.status_order)
        add_edge(
            edges_by_key,
            source=table_id,
            target=row_id,
            edge_type="include",
            label="содержит строку",
            source_name=document.path.name,
            description=str(row_node["label"]),
        )


def annotate_topics(nodes: Iterable[dict[str, object]], profile: ImportProfile) -> None:
    for node in nodes:
        explicit = set(split_property_values(property_value(node, "topics")))
        if explicit:
            set_property(node, "topics", "; ".join(sorted(explicit)))
            continue
        content = canonical_text(
            " ".join(
                (
                    str(node.get("label") or ""),
                    property_value(node, "direction"),
                    property_value(node, "description"),
                )
            )
        )
        for topic, terms in profile.topics.items():
            if any(canonical_text(term) in content for term in terms):
                explicit.add(topic)
        if explicit:
            set_property(node, "topics", "; ".join(sorted(explicit)))


def add_configured_cross_links(
    *,
    nodes_by_id: dict[str, dict[str, object]],
    edges_by_key: dict[tuple[str, str, str], dict[str, object]],
    profile: ImportProfile,
) -> None:
    nodes = list(nodes_by_id.values())
    for specification in profile.cross_links:
        edge_type = string_field(specification, "edge_type")
        source_types = set(string_items(specification.get("source_types")))
        target_types = set(string_items(specification.get("target_types")))
        sources = [node for node in nodes if str(node.get("type")) in source_types]
        targets = [node for node in nodes if str(node.get("type")) in target_types]
        strategy = str(specification.get("strategy") or "topics")
        minimum = int(specification.get("minimum_score") or 1)
        maximum_per_source = int(specification.get("max_per_source") or 5)
        maximum_total = int(specification.get("max_total") or 100)
        symmetric = bool(specification.get("symmetric", edge_type == "intersects_with"))
        total = 0
        seen_pairs: set[tuple[str, str]] = set()
        for source in sorted(sources, key=node_sort_key):
            candidates: list[tuple[int, str, dict[str, object], tuple[str, ...]]] = []
            for target in targets:
                source_id = str(source["id"])
                target_id = str(target["id"])
                if source_id == target_id:
                    continue
                pair = (
                    tuple(sorted((source_id, target_id))) if symmetric else (source_id, target_id)
                )
                if pair in seen_pairs:
                    continue
                if bool(specification.get("different_direction")) and directions_overlap(
                    source, target
                ):
                    continue
                score, basis = relation_score(source, target, strategy, profile)
                if score >= minimum:
                    candidates.append((score, target_id, target, basis))
            candidates.sort(key=lambda item: (-item[0], item[1]))
            for score, target_id, target, basis in candidates[:maximum_per_source]:
                if total >= maximum_total:
                    break
                source_id = str(source["id"])
                pair = (
                    tuple(sorted((source_id, target_id))) if symmetric else (source_id, target_id)
                )
                seen_pairs.add(pair)
                description = (
                    f"Связь определена профилем {profile.profile_id}; основание: "
                    f"{', '.join(basis)}."
                )
                add_edge(
                    edges_by_key,
                    source=source_id,
                    target=target_id,
                    edge_type=edge_type,
                    label=str(specification.get("label") or edge_type),
                    source_name=merge_strings(
                        (property_value(source, "source"), property_value(target, "source"))
                    ),
                    description=description,
                )
                edge = edges_by_key[(source_id, target_id, edge_type)]
                edge["properties"].append({"key": "match_score", "value": str(score)})
                edge["properties"].append({"key": "match_basis", "value": "; ".join(basis)})
                total += 1
            if total >= maximum_total:
                break


def apply_profile_shapes(
    nodes: Iterable[dict[str, object]],
    shapes: Mapping[str, str],
) -> None:
    for node in nodes:
        shape = shapes.get(str(node.get("type") or ""))
        if shape:
            node["shape"] = shape


def relation_score(
    source: dict[str, object],
    target: dict[str, object],
    strategy: str,
    profile: ImportProfile,
) -> tuple[int, tuple[str, ...]]:
    if strategy == "topics":
        common = split_property_values(property_value(source, "topics")) & split_property_values(
            property_value(target, "topics")
        )
    elif strategy == "tokens":
        common = node_tokens(source, profile.token_stop_words) & node_tokens(
            target, profile.token_stop_words
        )
    else:
        raise RuntimeError(f"Неизвестная стратегия междокументной связи: {strategy}")
    return len(common), tuple(sorted(common))


def arrange_universal_graph(bundle: GraphBundle) -> GraphBundle:
    node_ids = [str(node["id"]) for node in bundle.nodes]
    adjacency = {node_id: set() for node_id in node_ids}
    indegree = {node_id: 0 for node_id in node_ids}
    levels = {node_id: 0 for node_id in node_ids}
    for edge in bundle.edges:
        if str(edge.get("type")) in NON_HIERARCHICAL_EDGES:
            continue
        source = str(edge["source"])
        target = str(edge["target"])
        if source == target or target in adjacency[source]:
            continue
        adjacency[source].add(target)
        indegree[target] += 1
    queue = deque(sorted(node_id for node_id in node_ids if indegree[node_id] == 0))
    while queue:
        source = queue.popleft()
        for target in sorted(adjacency[source]):
            levels[target] = max(levels[target], levels[source] + 1)
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)

    lanes: dict[str, list[dict[str, object]]] = defaultdict(list)
    for node in bundle.nodes:
        direction = property_value(node, "direction")
        lane = "Пересечения" if ";" in direction else direction or "Документ"
        lanes[lane].append(node)
    for lane_index, lane in enumerate(sorted(lanes, key=str.casefold)):
        lane_column = lane_index % 2
        lane_row = lane_index // 2
        by_level: dict[int, list[dict[str, object]]] = defaultdict(list)
        for node in lanes[lane]:
            by_level[levels[str(node["id"])]].append(node)
        level_offset = 0
        for level in sorted(by_level):
            group = sorted(by_level[level], key=node_sort_key)
            columns = max(1, (len(group) + LAYOUT_ROWS - 1) // LAYOUT_ROWS)
            for index, node in enumerate(group):
                local_column = level_offset + index // LAYOUT_ROWS
                local_row = index % LAYOUT_ROWS
                node["x"] = lane_column * LAYOUT_LANE_WIDTH + local_column * LAYOUT_COLUMN_GAP
                node["y"] = lane_row * LAYOUT_LANE_HEIGHT + local_row * LAYOUT_ROW_GAP
                node["position3d"] = {
                    "x": float(local_column * 110),
                    "y": float((local_row - min(len(group), LAYOUT_ROWS) / 2) * 34),
                    "z": float((lane_index - (len(lanes) - 1) / 2) * 220),
                }
            level_offset += columns + 1
    return bundle


def upsert_node(
    nodes_by_id: dict[str, dict[str, object]],
    node: dict[str, object],
    status_order: Sequence[str],
) -> None:
    node_id = str(node["id"])
    existing = nodes_by_id.get(node_id)
    if existing is None:
        nodes_by_id[node_id] = node
        return
    for key in ("direction", "source", "description", "topics"):
        value = property_value(node, key)
        if value:
            set_property(
                existing,
                key,
                merge_strings(
                    (property_value(existing, key), value),
                    separator="; " if key in {"direction", "topics"} else " | ",
                ),
            )
    merge_node_status(existing, property_value(node, "status"), status_order)


def merge_node_status(
    node: dict[str, object],
    incoming: str,
    status_order: Sequence[str],
) -> None:
    current = property_value(node, "status")
    if not incoming:
        return
    ranking = {canonical_text(value): index for index, value in enumerate(status_order)}
    current_rank = ranking.get(canonical_text(current), -1)
    incoming_rank = ranking.get(canonical_text(incoming), -1)
    if not current or incoming_rank > current_rank:
        set_property(node, "status", incoming)
    elif current_rank < 0 and incoming_rank < 0 and incoming != current:
        set_property(node, "status", merge_strings((current, incoming), separator="; "))


def document_blocks(document: DocxDocument) -> tuple[DocxBlock, ...]:
    if document.blocks:
        return document.blocks
    blocks = [
        DocxBlock(index=index, kind="paragraph", paragraph=paragraph)
        for index, paragraph in enumerate(document.paragraphs)
    ]
    start = len(blocks)
    blocks.extend(
        DocxBlock(index=start + index, kind="table", table=table)
        for index, table in enumerate(document.tables)
    )
    return tuple(blocks)


def heading_level(paragraph: DocxParagraph) -> int:
    style = canonical_text(paragraph.style)
    match = re.search(r"(?:heading|заголовок)\s*(\d+)", style)
    if match:
        return max(1, int(match.group(1)))
    number = re.match(r"^(\d+(?:\.\d+)*)\.\s+", paragraph.text)
    if number and ("title" in style or "заголов" in style or "heading" in style):
        return number.group(1).count(".") + 1
    if style in {"title", "consplustitle"}:
        return number.group(1).count(".") + 1 if number else 1
    return 0


def table_header_matches(table: DocxTable, required_headers: Sequence[str]) -> bool:
    if not table.rows:
        return False
    actual = {canonical_text(value) for value in table.rows[0]}
    return all(canonical_text(value) in actual for value in required_headers)


def table_value(row: Sequence[str], header: Mapping[str, int], column: str) -> str:
    index = header.get(canonical_text(column))
    return clean_text(row[index]) if index is not None and index < len(row) else ""


def should_skip_row(
    row: Sequence[str],
    header: Mapping[str, int],
    raw_rules: object,
) -> bool:
    for rule in mapping_items(raw_rules, "skip_rows"):
        value = canonical_text(table_value(row, header, string_field(rule, "column")))
        if value == canonical_text(string_field(rule, "equals")):
            return True
    return not any(clean_text(value) for value in row)


def transform_values(value: str, rule: Mapping[str, object]) -> list[str]:
    transformed = clean_text(value)
    if rule.get("transform") == "before_slash":
        transformed = clean_text(transformed.split("/", 1)[0])
    separator = str(rule.get("split") or "")
    values = transformed.split(separator) if separator else [transformed]
    return [clean_text(item).rstrip(".") for item in values if clean_text(item)]


def hierarchy_node_id(
    *,
    node_type: str,
    label: str,
    parent_id: str,
    row_index: int,
    deduplicate: str,
) -> str:
    if deduplicate == "global":
        scope = label
    elif deduplicate == "row":
        scope = f"{parent_id}|{row_index}|{label}"
    else:
        scope = f"{parent_id}|{label}"
    return f"{node_type}:{stable_suffix(scope)}"


def section_node_id(
    *,
    node_type: str,
    label: str,
    group_id: str,
    section_id: str,
    paragraph_index: int,
    deduplicate: str,
) -> str:
    if deduplicate == "global":
        scope = label
    elif deduplicate == "group":
        scope = f"{group_id}|{label}"
    elif deduplicate == "paragraph":
        scope = f"{section_id}|{paragraph_index}"
    else:
        scope = f"{section_id}|{label}"
    return f"{node_type}:{stable_suffix(scope)}"


def resolve_section_parent(
    parent: str,
    *,
    group_id: str,
    section_id: str,
    latest_by_type: Mapping[str, str],
) -> str:
    if parent == "group":
        return group_id
    if parent.startswith("last:"):
        return latest_by_type.get(parent.removeprefix("last:"), section_id)
    return section_id


def paragraph_segment(
    paragraphs: Sequence[DocxParagraph],
    *,
    start_pattern: str,
    end_pattern: str,
) -> list[DocxParagraph]:
    start = next(
        (
            index
            for index, paragraph in enumerate(paragraphs)
            if regex_search(start_pattern, paragraph.text)
        ),
        None,
    )
    if start is None:
        return []
    end = next(
        (
            index
            for index, paragraph in enumerate(paragraphs[start + 1 :], start + 1)
            if regex_search(end_pattern, paragraph.text)
        ),
        len(paragraphs),
    )
    return list(paragraphs[start:end])


def extract_heading_value(text: str, mode: str) -> str:
    stripped = re.sub(r"^\d+(?:\.\d+)*\.\s*", "", clean_text(text))
    if mode == "before_colon":
        return clean_text(stripped.split(":", 1)[0])
    if mode == "after_colon" and ":" in stripped:
        return clean_text(stripped.split(":", 1)[1])
    return stripped


def direction_alias(value: str, raw_aliases: object) -> str:
    for alias in mapping_items(raw_aliases, "direction_aliases"):
        if regex_search(string_field(alias, "pattern"), value):
            return string_field(alias, "value")
    return value


def context_description(paragraphs: Sequence[DocxParagraph], prefix: str) -> str:
    if not prefix:
        return ""
    return next(
        (
            clean_text(paragraph.text.removeprefix(prefix))
            for paragraph in paragraphs
            if paragraph.text.startswith(prefix)
        ),
        "",
    )


def transform_label(value: str, transform: str) -> str:
    text = clean_text(value)
    if transform == "strip_section":
        text = re.sub(r"^\d+(?:\.\d+)*(?:\.[а-яё])?\.\s*", "", text, flags=re.IGNORECASE)
    elif transform == "strip_bullet":
        text = re.sub(r"^[-•–—]\s*", "", text)
    if len(text) > 220:
        text = text[:217].rstrip() + "..."
    return text.strip(' "')


def paragraph_source(document: DocxDocument, paragraph: DocxParagraph) -> str:
    return f"{document.path.name}, абзац {paragraph.index}"


def directions_overlap(left: dict[str, object], right: dict[str, object]) -> bool:
    return bool(
        split_property_values(property_value(left, "direction"))
        & split_property_values(property_value(right, "direction"))
    )


def node_tokens(node: dict[str, object], stop_words: frozenset[str]) -> set[str]:
    content = " ".join(
        (
            str(node.get("label") or ""),
            property_value(node, "description"),
        )
    )
    words = re.findall(r"[a-zа-яё0-9]+", canonical_text(content))
    return {word[:8] for word in words if len(word) >= 5 and word not in stop_words}


def split_property_values(value: str) -> set[str]:
    return {clean_text(item) for item in value.split(";") if clean_text(item)}


def node_sort_key(node: dict[str, object]) -> tuple[str, str]:
    return (str(node.get("label") or "").casefold(), str(node.get("id") or ""))


def regex_search(pattern: str, value: str) -> bool:
    try:
        return re.search(pattern, value, flags=re.IGNORECASE) is not None
    except re.error as exc:
        raise RuntimeError(f"Некорректное регулярное выражение в профиле: {pattern}") from exc


def compile_patterns(patterns: Iterable[str], field: str) -> None:
    for pattern in patterns:
        try:
            re.compile(pattern, flags=re.IGNORECASE)
        except re.error as exc:
            raise RuntimeError(f"Поле {field} содержит некорректное выражение: {pattern}") from exc


def mapping_field(
    payload: Mapping[str, object],
    name: str,
    *,
    required: bool = True,
) -> Mapping[str, object]:
    value = payload.get(name)
    if value is None and not required:
        return {}
    if not isinstance(value, dict):
        raise RuntimeError(f"Поле профиля {name} должно быть JSON-объектом.")
    return value


def mapping_items(value: object, field: str) -> tuple[dict[str, object], ...]:
    if value is None:
        raise RuntimeError(f"Поле профиля {field} является обязательным.")
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise RuntimeError(f"Поле профиля {field} должно быть массивом JSON-объектов.")
    return tuple(dict(item) for item in value)


def string_field(payload: Mapping[str, object], name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"Поле профиля {name} должно быть непустой строкой.")
    return value.strip()


def integer_field(payload: Mapping[str, object], name: str) -> int:
    value = payload.get(name)
    if not isinstance(value, int) or isinstance(value, bool):
        raise RuntimeError(f"Поле профиля {name} должно быть целым числом.")
    return value


def string_items(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or any(not isinstance(item, str) for item in value):
        raise RuntimeError("Поле профиля должно быть массивом строк.")
    return tuple(item.strip() for item in value if item.strip())
