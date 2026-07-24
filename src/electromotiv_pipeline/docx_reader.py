from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from zipfile import BadZipFile, ZipFile

WORD_NAMESPACE = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
WORD = f"{{{WORD_NAMESPACE}}}"
NAMESPACES = {"w": WORD_NAMESPACE}
MAX_DOCX_BYTES = 25_000_000
MAX_DOCUMENT_XML_BYTES = 50_000_000


@dataclass(frozen=True)
class DocxParagraph:
    index: int
    text: str
    style: str


@dataclass(frozen=True)
class DocxTable:
    rows: tuple[tuple[str, ...], ...]


@dataclass(frozen=True)
class DocxDocument:
    path: Path
    paragraphs: tuple[DocxParagraph, ...]
    tables: tuple[DocxTable, ...]


def read_docx(path: Path) -> DocxDocument:
    if not path.is_file():
        raise RuntimeError(f"DOCX-файл не найден: {path}")
    if path.suffix.casefold() != ".docx":
        raise RuntimeError(f"Ожидается DOCX-файл: {path}")
    if path.stat().st_size > MAX_DOCX_BYTES:
        raise RuntimeError(f"DOCX-файл превышает лимит {MAX_DOCX_BYTES} байт: {path}")

    try:
        with ZipFile(path) as archive:
            document_xml = read_archive_member(
                archive,
                "word/document.xml",
                max_bytes=MAX_DOCUMENT_XML_BYTES,
            )
            try:
                styles_xml = read_archive_member(
                    archive,
                    "word/styles.xml",
                    max_bytes=5_000_000,
                )
            except RuntimeError:
                styles_xml = b""
    except BadZipFile as exc:
        raise RuntimeError(f"Некорректный DOCX-контейнер: {path}") from exc

    try:
        root = ET.fromstring(document_xml)
        style_names = parse_style_names(styles_xml)
    except ET.ParseError as exc:
        raise RuntimeError(f"Некорректный XML внутри DOCX: {path}") from exc

    paragraphs = tuple(
        DocxParagraph(
            index=index,
            text=text,
            style=paragraph_style(paragraph, style_names),
        )
        for index, paragraph in enumerate(root.findall(".//w:p", NAMESPACES))
        if (text := paragraph_text(paragraph))
    )
    tables = tuple(parse_table(table) for table in root.findall(".//w:tbl", NAMESPACES))
    return DocxDocument(path=path, paragraphs=paragraphs, tables=tables)


def read_archive_member(archive: ZipFile, name: str, *, max_bytes: int) -> bytes:
    try:
        info = archive.getinfo(name)
    except KeyError as exc:
        raise RuntimeError(f"DOCX не содержит обязательный файл {name}.") from exc
    if info.file_size > max_bytes:
        raise RuntimeError(f"Раздел {name} превышает лимит {max_bytes} байт.")
    return archive.read(info)


def parse_style_names(payload: bytes) -> dict[str, str]:
    if not payload:
        return {}
    root = ET.fromstring(payload)
    result: dict[str, str] = {}
    for style in root.findall("w:style", NAMESPACES):
        style_id = style.get(WORD + "styleId", "")
        name = style.find("w:name", NAMESPACES)
        if style_id:
            result[style_id] = name.get(WORD + "val", style_id) if name is not None else style_id
    return result


def paragraph_text(paragraph: ET.Element) -> str:
    return " ".join(
        "".join(node.text or "" for node in paragraph.findall(".//w:t", NAMESPACES)).split()
    )


def paragraph_style(paragraph: ET.Element, style_names: dict[str, str]) -> str:
    style = paragraph.find("w:pPr/w:pStyle", NAMESPACES)
    if style is None:
        return ""
    style_id = style.get(WORD + "val", "")
    return style_names.get(style_id, style_id)


def parse_table(table: ET.Element) -> DocxTable:
    rows: list[tuple[str, ...]] = []
    for row in table.findall("./w:tr", NAMESPACES):
        cells: list[str] = []
        for cell in row.findall("./w:tc", NAMESPACES):
            parts = [
                text
                for paragraph in cell.findall(".//w:p", NAMESPACES)
                if (text := paragraph_text(paragraph))
            ]
            cells.append(" / ".join(parts))
        rows.append(tuple(cells))
    return DocxTable(rows=tuple(rows))
