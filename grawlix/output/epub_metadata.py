"""Update an EPUB package document with Grawlix book metadata."""

from __future__ import annotations

import copy
import shutil
import tempfile
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZIP_STORED, ZipFile

from grawlix.book import Metadata

CONTAINER_NS = "urn:oasis:names:tc:opendocument:xmlns:container"
DC_NS = "http://purl.org/dc/elements/1.1/"


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _find_metadata(root: ET.Element) -> ET.Element:
    metadata = next(
        (element for element in root.iter() if _local_name(element.tag) == "metadata"),
        None,
    )
    if metadata is None:
        raise ValueError("EPUB package document does not contain metadata")
    return metadata


def _set_dc_values(metadata: ET.Element, name: str, values: list[str]) -> None:
    existing = [element for element in metadata if element.tag == f"{{{DC_NS}}}{name}"]
    insertion_index = list(metadata).index(existing[0]) if existing else len(metadata)
    for element in existing:
        metadata.remove(element)
    for offset, value in enumerate(values):
        element = ET.Element(f"{{{DC_NS}}}{name}")
        element.text = value
        metadata.insert(insertion_index + offset, element)


def _set_dc_identifier(metadata: ET.Element, value: str) -> None:
    """Update the package identifier without dropping its referenced id attribute."""
    existing = [
        element for element in metadata if element.tag == f"{{{DC_NS}}}identifier"
    ]
    if existing:
        existing[0].text = value
        for element in existing[1:]:
            metadata.remove(element)
        return
    element = ET.Element(f"{{{DC_NS}}}identifier")
    element.text = value
    metadata.append(element)


def _set_named_meta(metadata: ET.Element, name: str, content: str) -> None:
    element = next(
        (
            child
            for child in metadata
            if _local_name(child.tag) == "meta" and child.get("name") == name
        ),
        None,
    )
    if element is None:
        namespace = metadata.tag.removesuffix("metadata")
        element = ET.SubElement(metadata, f"{namespace}meta")
        element.set("name", name)
    element.set("content", content)


def _unique_id(root: ET.Element, preferred: str) -> str:
    existing = {element.get("id") for element in root.iter() if element.get("id")}
    candidate = preferred
    suffix = 2
    while candidate in existing:
        candidate = f"{preferred}-{suffix}"
        suffix += 1
    return candidate


def _find_epub3_series(metadata: ET.Element) -> ET.Element | None:
    collections = [
        element
        for element in metadata
        if _local_name(element.tag) == "meta"
        and element.get("property") == "belongs-to-collection"
    ]
    for collection in collections:
        collection_id = collection.get("id")
        if not collection_id:
            continue
        collection_type = next(
            (
                element
                for element in metadata
                if _local_name(element.tag) == "meta"
                and element.get("refines") == f"#{collection_id}"
                and element.get("property") == "collection-type"
            ),
            None,
        )
        if collection_type is not None and (collection_type.text or "").strip() == "series":
            return collection
    return None


def _set_refinement(
    metadata: ET.Element,
    collection_id: str,
    property_name: str,
    value: str,
) -> None:
    element = next(
        (
            child
            for child in metadata
            if _local_name(child.tag) == "meta"
            and child.get("refines") == f"#{collection_id}"
            and child.get("property") == property_name
        ),
        None,
    )
    if element is None:
        namespace = metadata.tag.removesuffix("metadata")
        element = ET.SubElement(metadata, f"{namespace}meta")
        element.set("refines", f"#{collection_id}")
        element.set("property", property_name)
    element.text = value


def _set_series(
    package: ET.Element,
    metadata: ET.Element,
    series: str,
    index: int | float | str | None,
) -> None:
    # Calibre reads these OPF metadata names for its Series and Series index fields.
    _set_named_meta(metadata, "calibre:series", series)
    if index is not None:
        _set_named_meta(metadata, "calibre:series_index", str(index))

    if not (package.get("version") or "").startswith("3"):
        return
    collection = _find_epub3_series(metadata)
    if collection is None:
        namespace = metadata.tag.removesuffix("metadata")
        collection = ET.SubElement(metadata, f"{namespace}meta")
        collection.set("property", "belongs-to-collection")
        collection.set("id", _unique_id(package, "grawlix-series"))
    collection.text = series
    collection_id = collection.get("id")
    assert collection_id is not None
    _set_refinement(metadata, collection_id, "collection-type", "series")
    if index is not None:
        _set_refinement(metadata, collection_id, "group-position", str(index))


def normalize_epub_metadata(file_path: str | Path, book_metadata: Metadata) -> None:
    """Atomically write authoritative Grawlix metadata into an EPUB's OPF file."""
    path = Path(file_path)
    with ZipFile(path, "r") as source:
        container = ET.fromstring(source.read("META-INF/container.xml"))
        rootfile = container.find(f".//{{{CONTAINER_NS}}}rootfile")
        if rootfile is None or not rootfile.get("full-path"):
            raise ValueError("EPUB container does not identify an OPF package document")
        opf_path = rootfile.get("full-path")
        assert opf_path is not None

        opf_root = ET.fromstring(source.read(opf_path))
        metadata = _find_metadata(opf_root)
        _set_dc_values(metadata, "title", [book_metadata.title])

        authors = [author.strip() for author in book_metadata.authors if author.strip()]
        if authors:
            _set_dc_values(metadata, "creator", authors)
        if book_metadata.series:
            _set_series(opf_root, metadata, book_metadata.series, book_metadata.index)
        if book_metadata.description:
            _set_dc_values(metadata, "description", [book_metadata.description])
        if book_metadata.language:
            _set_dc_values(metadata, "language", [book_metadata.language])
        if book_metadata.publisher:
            _set_dc_values(metadata, "publisher", [book_metadata.publisher])
        if book_metadata.identifier:
            _set_dc_identifier(metadata, book_metadata.identifier)
        if book_metadata.release_date:
            _set_dc_values(metadata, "date", [book_metadata.release_date.isoformat()])

        ET.register_namespace("dc", DC_NS)
        updated_opf = ET.tostring(opf_root, encoding="utf-8", xml_declaration=True)
        entries = [(copy.copy(info), source.read(info.filename)) for info in source.infolist()]

    with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".epub", delete=False) as temp:
        temporary_path = Path(temp.name)
    try:
        with ZipFile(temporary_path, "w") as destination:
            for info, content in entries:
                if info.filename == "mimetype":
                    info.compress_type = ZIP_STORED
                destination.writestr(
                    info,
                    updated_opf if info.filename == opf_path else content,
                )
        shutil.copymode(path, temporary_path)
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)
