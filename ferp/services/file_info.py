from __future__ import annotations

import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class FileInfoResult:
    path: Path
    data: dict[str, str]
    pdf_data: dict[str, str] | None = None
    excel_data: dict[str, str] | None = None
    error: str | None = None


def build_file_info(path: Path) -> FileInfoResult:
    try:
        stat = path.stat()
    except OSError as exc:
        return FileInfoResult(path=path, data={}, error=str(exc))

    name_label = "Folder Name" if path.is_dir() else "File Name"
    display_name = path.name or str(path)
    info: dict[str, str] = {
        name_label: display_name,
        "Name Length": str(len(display_name)),
        "Modified": _format_timestamp(stat.st_mtime),
        "Created": _format_timestamp(stat.st_ctime),
        "Size": _format_bytes(stat.st_size),
    }

    pdf_info: dict[str, str] | None = None
    excel_info: dict[str, str] | None = None
    if path.is_file() and path.suffix.lower() == ".pdf":
        pdf_info = {}
        _append_pdf_metadata(path, pdf_info)
    elif path.is_file():
        excel_info = {}
        _append_excel_document_id(path, excel_info)
        if not excel_info:
            excel_info = None

    return FileInfoResult(
        path=path,
        data=info,
        pdf_data=pdf_info,
        excel_data=excel_info,
        error=None,
    )


def _file_type_label(path: Path) -> str:
    suffix = path.suffix.lstrip(".").lower()
    return suffix if suffix else "File"


def _format_timestamp(value: float) -> str:
    try:
        return datetime.fromtimestamp(value).strftime("%Y-%m-%d %H:%M:%S")
    except (OSError, ValueError):
        return "Unknown"


def _format_bytes(value: int) -> str:
    size = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024.0:
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} PB"


def _append_pdf_metadata(path: Path, info: dict[str, str]) -> None:
    try:
        from pypdf import PdfReader  # type: ignore[import-untyped]
    except Exception:
        info["PDF Metadata"] = "Unavailable (pypdf not installed)"
        return

    try:
        reader = PdfReader(str(path))
    except Exception as exc:
        info["PDF Metadata"] = f"Unavailable ({exc})"
        return

    xmp_text = _extract_xmp_text(reader)
    metadata = reader.metadata or {}
    fields = {
        "/Title": "Title",
        "/Author": "Author",
        "/Subject": "Subject",
        "/Creator": "Creator",
        "/Producer": "Producer",
        "/CreationDate": "CreationDate",
        "/ModDate": "ModDate",
        "/Keywords": "Keywords",
    }

    if xmp_text:
        ferp_fields = _extract_ferp_summary(xmp_text)
        info.update(ferp_fields)

    for key, label in fields.items():
        value = metadata.get(key)
        if value:
            info[label] = str(value)

    if xmp_text:
        dc_fields = _extract_dublin_core(xmp_text)
        info.update(dc_fields)
        xmp_fields = _extract_xmp_fields(xmp_text)
        info.update(xmp_fields)


def _append_excel_document_id(path: Path, info: dict[str, str]) -> None:
    if path.suffix.lower() not in {".xlsx", ".xlsm", ".xltx", ".xltm"}:
        return
    try:
        with zipfile.ZipFile(path) as archive:
            try:
                raw = archive.read("docProps/custom.xml")
            except KeyError:
                return
    except Exception:
        return

    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return

    cp_ns = "http://schemas.openxmlformats.org/officeDocument/2006/custom-properties"
    vt_ns = "http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"
    for prop in root.findall(f".//{{{cp_ns}}}property"):
        if prop.get("name") != "ferp:DocumentID":
            continue
        value = ""
        for child in prop:
            if child.tag.startswith(f"{{{vt_ns}}}") and child.text:
                value = child.text.strip()
                break
        if value:
            info["DocumentID"] = value
        return


def _extract_xmp_text(reader: Any) -> str | None:
    try:
        xmp = getattr(reader, "xmp_metadata", None)
        if xmp is not None:
            raw = getattr(xmp, "xmpmeta", None)
            if raw:
                return str(raw)
    except Exception:
        pass
    try:
        root = reader.trailer.get("/Root", {})
        metadata = root.get("/Metadata")
        if metadata is None:
            return None
        raw = metadata.get_data()
        if not raw:
            return None
        return raw.decode("utf-8", errors="ignore")
    except Exception:
        return None


def _extract_dublin_core(xmp_text: str) -> dict[str, str]:
    try:
        root = ET.fromstring(xmp_text)
    except ET.ParseError:
        return {}

    dc_ns = "http://purl.org/dc/elements/1.1/"
    fields = (
        "publisher",
        "identifier",
    )
    results: dict[str, str] = {}
    for field in fields:
        values = []
        for elem in root.findall(f".//{{{dc_ns}}}{field}"):
            values.extend(_collect_xmp_values(elem))
        if values:
            label = f"DC {field.title()}"
            results[label] = ", ".join(sorted(set(values)))
    return results


def _collect_xmp_values(elem: Any) -> list[str]:
    values: list[str] = []
    if elem.text and elem.text.strip():
        values.append(elem.text.strip())
    for child in elem.iter():
        if child is elem:
            continue
        if child.text and child.text.strip():
            values.append(child.text.strip())
    return values


def _extract_xmp_fields(xmp_text: str) -> dict[str, str]:
    try:
        root = ET.fromstring(xmp_text)
    except ET.ParseError:
        return {}

    namespaces = {
        "xmp": "http://ns.adobe.com/xap/1.0/",
        "pdf": "http://ns.adobe.com/pdf/1.3/",
        "xmpMM": "http://ns.adobe.com/xap/1.0/mm/",
    }
    fields = {
        "xmp:CreatorTool": "XMP CreatorTool",
        "pdf:Producer": "XMP Producer",
        "xmpMM:DocumentID": "XMP DocumentID",
        "xmpMM:InstanceID": "XMP InstanceID",
    }
    results: dict[str, str] = {}
    for field, label in fields.items():
        prefix, local = field.split(":", 1)
        ns = namespaces.get(prefix)
        if not ns:
            continue
        values: list[str] = []
        for elem in root.findall(f".//{{{ns}}}{local}"):
            values.extend(_collect_xmp_values(elem))
        if values:
            results[label] = ", ".join(sorted(set(values)))
    return results


def _extract_ferp_summary(xmp_text: str) -> dict[str, str]:
    try:
        root = ET.fromstring(xmp_text)
    except ET.ParseError:
        return {}

    ferp_ns = "https://tulbox.app/ferp/xmp/1.0"
    rdf_ns = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
    ferp_items: list[tuple[str, str]] = []
    admin = root.find(f".//{{{ferp_ns}}}administrator")
    if admin is not None:
        values = _collect_xmp_values(admin)
        if values:
            ferp_items.append(("Stamp Administrator", values[0]))
    catalog_code = root.find(f".//{{{ferp_ns}}}catalogCode")
    if catalog_code is not None:
        values = _collect_xmp_values(catalog_code)
        if values:
            ferp_items.append(("Stamp Catalog Code", values[0]))
    added_date = root.find(f".//{{{ferp_ns}}}dataAddedDate")
    if added_date is not None:
        values = _collect_xmp_values(added_date)
        if values:
            ferp_items.append(("Stamp Data Added", values[0]))
    spec_version = root.find(f".//{{{ferp_ns}}}stampSpecVersion")
    if spec_version is not None:
        values = _collect_xmp_values(spec_version)
        if values:
            ferp_items.append(("Stamp Spec Version", values[0]))

    agreements_elem = root.find(f".//{{{ferp_ns}}}agreements")
    agreement_items: list[ET.Element] = []
    if agreements_elem is not None:
        bag = agreements_elem.find(f"./{{{rdf_ns}}}Bag")
        if bag is not None:
            agreement_items = list(bag.findall(f"./{{{rdf_ns}}}li"))
    if agreement_items:
        publishers: list[str] = []
        for agreement in agreement_items:
            for pub in agreement.findall(f".//{{{ferp_ns}}}publishers//{{{rdf_ns}}}li"):
                publishers.extend(_collect_xmp_values(pub))
        if publishers:
            ferp_items.append(("Stamp Publishers", ", ".join(sorted(set(publishers)))))

    if not ferp_items:
        return {}

    results: dict[str, str] = dict(ferp_items)
    results["---"] = "---"
    return results
