from __future__ import annotations

import re
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject, NumberObject, StreamObject

_DOC_ID_RE = re.compile(r"ferp:DocumentID=\{(uuid:)?([0-9a-fA-F-]+)\}")
_DOC_ID_PROP_NAME = "ferp:DocumentID"
_MSO_PROPERTY_TYPE_STRING = 4
_FERP_NS = "https://tulbox.app/ferp/xmp/1.0"
_RDF_NS = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
_XMP_MM_NS = "http://ns.adobe.com/xap/1.0/mm/"
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass(frozen=True)
class FerpEffectiveDate:
    date: str
    territories: tuple[str, ...]


@dataclass(frozen=True)
class FerpAgreement:
    publishers: tuple[str, ...]
    effective_dates: tuple[FerpEffectiveDate, ...]


@dataclass(frozen=True)
class FerpXmpMetadata:
    administrator: str
    catalog_code: str
    data_added_date: str
    stamp_spec_version: str
    document_id: str | None
    instance_id: str | None
    agreements: tuple[FerpAgreement, ...]


def generate_document_id() -> str:
    return f"uuid:{uuid.uuid4()}"


def normalize_document_id(value: str) -> str | None:
    if not value:
        return None
    raw = value.strip()
    if raw.lower().startswith("uuid:"):
        raw = raw[5:]
    try:
        normalized = str(uuid.UUID(raw))
    except ValueError:
        return None
    return f"uuid:{normalized}"


def _extract_document_id_from_custom_property(workbook) -> str | None:
    try:
        props = workbook.CustomDocumentProperties
    except Exception:
        return None
    try:
        prop = props(_DOC_ID_PROP_NAME)
    except Exception:
        return None
    return normalize_document_id(str(getattr(prop, "Value", "")).strip())


def _extract_document_id_from_right_footer(worksheet) -> str | None:
    footer = getattr(worksheet.PageSetup, "RightFooter", "")
    if not footer:
        return None
    match = _DOC_ID_RE.search(str(footer))
    if not match:
        return None
    prefix, value = match.groups()
    raw = f"{prefix or ''}{value}"
    return normalize_document_id(raw)


def _set_document_id_property(workbook, document_id: str) -> None:
    try:
        props = workbook.CustomDocumentProperties
    except Exception:
        return
    try:
        prop = props(_DOC_ID_PROP_NAME)
        prop.Value = document_id
        return
    except Exception:
        pass
    try:
        props.Add(_DOC_ID_PROP_NAME, False, _MSO_PROPERTY_TYPE_STRING, document_id)
    except Exception:
        return


def _set_right_footer_document_id(worksheet, document_id: str) -> None:
    worksheet.PageSetup.RightFooter = f"&KFFFFFFferp:DocumentID={{{document_id}}}"


def resolve_excel_document_id(workbook, worksheet) -> str:
    document_id = _extract_document_id_from_custom_property(workbook)
    if document_id:
        _set_right_footer_document_id(worksheet, document_id)
        _set_document_id_property(workbook, document_id)
        return document_id
    document_id = _extract_document_id_from_right_footer(worksheet)
    if document_id:
        _set_right_footer_document_id(worksheet, document_id)
        _set_document_id_property(workbook, document_id)
        return document_id
    document_id = generate_document_id()
    _set_document_id_property(workbook, document_id)
    _set_right_footer_document_id(worksheet, document_id)
    return document_id


def _extract_xmp_mm_id_text(xmp_text: str) -> tuple[str | None, str | None]:
    root = _parse_xmp_root(xmp_text)
    if root is None:
        return None, None
    doc_elem = root.find(f".//{{{_XMP_MM_NS}}}DocumentID")
    inst_elem = root.find(f".//{{{_XMP_MM_NS}}}InstanceID")
    doc_id = doc_elem.text.strip() if doc_elem is not None and doc_elem.text else None
    inst_id = inst_elem.text.strip() if inst_elem is not None and inst_elem.text else None
    return doc_id, inst_id


def _extract_xmp_mm_ids(xmp_text: str) -> tuple[str | None, str | None]:
    raw_doc_id, raw_inst_id = _extract_xmp_mm_id_text(xmp_text)
    doc_id = normalize_document_id(raw_doc_id or "") if raw_doc_id else None
    inst_id = normalize_document_id(raw_inst_id or "") if raw_inst_id else None
    return doc_id, inst_id


def _get_existing_xmp_mm_ids(reader: PdfReader) -> tuple[str | None, str | None]:
    try:
        xmp_text = extract_pdf_xmp_text(reader)
        if xmp_text:
            return _extract_xmp_mm_ids(xmp_text)
    except Exception:
        pass

    return None, None


def extract_pdf_document_id(reader: PdfReader) -> str | None:
    document_id, _instance_id = _get_existing_xmp_mm_ids(reader)
    if document_id:
        return document_id

    raw_doc_id, _raw_instance = _get_existing_xmp_mm_id_text(reader)
    if not raw_doc_id:
        return None
    return raw_doc_id


def _get_existing_xmp_mm_id_text(reader: PdfReader) -> tuple[str | None, str | None]:
    try:
        xmp_text = extract_pdf_xmp_text(reader)
        if xmp_text:
            return _extract_xmp_mm_id_text(xmp_text)
    except Exception:
        pass

    return None, None


def _extract_xmp_payload(xmp_text: str) -> str:
    match = re.search(r"(<x:xmpmeta\b.*?</x:xmpmeta>)", xmp_text, re.DOTALL)
    return match.group(1) if match else xmp_text


def _parse_xmp_root(xmp_text: str) -> ET.Element | None:
    try:
        return ET.fromstring(_extract_xmp_payload(xmp_text))
    except ET.ParseError:
        return None


def _normalize_text_value(value: str) -> str:
    return " ".join(value.split()).strip()


def _normalize_unique_values(values: Iterable[str], *, sort_values: bool = False) -> tuple[str, ...]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = _normalize_text_value(raw)
        if not value or value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    if sort_values:
        normalized.sort()
    return tuple(normalized)


def _collect_xmp_text_values(elem: ET.Element) -> list[str]:
    values: list[str] = []
    if elem.text and elem.text.strip():
        values.append(elem.text.strip())
    for child in elem.iter():
        if child is elem:
            continue
        if child.text and child.text.strip():
            values.append(child.text.strip())
    return values


def _normalize_date_values(values: Iterable[str]) -> tuple[str, ...]:
    normalized = _normalize_unique_values(values)
    valid = [value for value in normalized if _DATE_RE.fullmatch(value)]
    invalid = [value for value in normalized if not _DATE_RE.fullmatch(value)]
    return tuple(sorted(valid) + invalid)


def extract_pdf_xmp_text(reader: PdfReader) -> str | None:
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
        if hasattr(root, "get_object"):
            root = root.get_object()
        metadata = root.get("/Metadata")
        if metadata is None:
            return None
        if hasattr(metadata, "get_object"):
            metadata = metadata.get_object()
        raw = metadata.get_data()
        if not raw:
            return None
        return raw.decode("utf-8", errors="ignore")
    except Exception:
        return None


def parse_ferp_xmp(xmp_text: str) -> FerpXmpMetadata | None:
    root = _parse_xmp_root(xmp_text)
    if root is None:
        return None

    namespaces = {"ferp": _FERP_NS, "rdf": _RDF_NS}

    def scalar(path: str) -> str:
        elem = root.find(path, namespaces)
        if elem is None:
            return ""
        values = _normalize_unique_values(_collect_xmp_text_values(elem))
        return values[0] if values else ""

    agreements: list[FerpAgreement] = []
    for agreement_node in root.findall(".//ferp:agreements/rdf:Bag/rdf:li", namespaces):
        publishers = _normalize_unique_values(
            li.text or ""
            for li in agreement_node.findall(".//ferp:publishers/rdf:Bag/rdf:li", namespaces)
        )
        effective_dates: list[FerpEffectiveDate] = []
        for effective_node in agreement_node.findall(
            ".//ferp:effectiveDates/rdf:Seq/rdf:li", namespaces
        ):
            date_elem = effective_node.find("./ferp:date", namespaces)
            date_values = _normalize_date_values(
                _collect_xmp_text_values(date_elem) if date_elem is not None else []
            )
            territories = _normalize_unique_values(
                li.text or ""
                for li in effective_node.findall(
                    ".//ferp:territories/rdf:Bag/rdf:li", namespaces
                )
            )
            if not date_values and not territories:
                continue
            effective_dates.append(
                FerpEffectiveDate(
                    date=date_values[0] if date_values else "",
                    territories=territories,
                )
            )
        if publishers or effective_dates:
            agreements.append(
                FerpAgreement(
                    publishers=publishers,
                    effective_dates=tuple(effective_dates),
                )
            )

    document_id, instance_id = _extract_xmp_mm_ids(xmp_text)
    metadata = FerpXmpMetadata(
        administrator=scalar(".//ferp:administrator"),
        catalog_code=scalar(".//ferp:catalogCode"),
        data_added_date=scalar(".//ferp:dataAddedDate"),
        stamp_spec_version=scalar(".//ferp:stampSpecVersion"),
        document_id=document_id,
        instance_id=instance_id,
        agreements=tuple(agreements),
    )
    has_data = any(
        [
            metadata.administrator,
            metadata.catalog_code,
            metadata.data_added_date,
            metadata.stamp_spec_version,
            metadata.document_id,
            metadata.instance_id,
            metadata.agreements,
        ]
    )
    return metadata if has_data else None


def extract_pdf_ferp_metadata(reader: PdfReader) -> FerpXmpMetadata | None:
    xmp_text = extract_pdf_xmp_text(reader)
    if not xmp_text:
        return None
    return parse_ferp_xmp(xmp_text)


def read_pdf_ferp_metadata(pdf_path: Path) -> FerpXmpMetadata | None:
    reader = PdfReader(str(pdf_path))
    return extract_pdf_ferp_metadata(reader)


def build_xmp_mm_metadata(document_id: str | None) -> bytes:
    if document_id:
        normalized = normalize_document_id(document_id)
        document_id = normalized or document_id.strip()
    if not document_id:
        document_id = f"uuid:{uuid.uuid4()}"
    instance_id = f"uuid:{uuid.uuid4()}"
    xmp = f"""<?xpacket begin='' id='W5M0MpCehiHzreSzNTczkc9d'?>
<x:xmpmeta xmlns:x="adobe:ns:meta/">
  <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
    <rdf:Description xmlns:xmpMM="http://ns.adobe.com/xap/1.0/mm/">
      <xmpMM:DocumentID>{document_id}</xmpMM:DocumentID>
      <xmpMM:InstanceID>{instance_id}</xmpMM:InstanceID>
    </rdf:Description>
  </rdf:RDF>
</x:xmpmeta>
<?xpacket end='w'?>"""
    return xmp.encode("utf-8")


def set_xmp_mm_metadata_inplace(pdf_path: Path, document_id: str | None) -> bool:
    document_id = normalize_document_id(document_id or "")
    if not document_id:
        return False

    reader = PdfReader(str(pdf_path))
    existing_doc_id, _existing_instance = _get_existing_xmp_mm_ids(reader)
    if existing_doc_id == document_id:
        return False

    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)

    info: dict[str, str] = {}
    if reader.metadata:
        for k, v in reader.metadata.items():
            if isinstance(k, str) and k.startswith("/") and v is not None:
                info[k] = str(v)
    if info:
        writer.add_metadata(info)

    xmp_bytes = build_xmp_mm_metadata(document_id)
    md_stream = StreamObject()
    set_data = getattr(md_stream, "set_data", None)
    if callable(set_data):
        set_data(xmp_bytes)
    else:
        md_stream._data = xmp_bytes
        md_stream.update({NameObject("/Length"): NumberObject(len(xmp_bytes))})
    md_stream.update(
        {
            NameObject("/Type"): NameObject("/Metadata"),
            NameObject("/Subtype"): NameObject("/XML"),
        }
    )

    md_ref = writer._add_object(md_stream)
    writer._root_object.update({NameObject("/Metadata"): md_ref})

    tmp_path = pdf_path.with_suffix(f"{pdf_path.suffix}.tmp")
    try:
        with tmp_path.open("wb") as handle:
            writer.write(handle)
        tmp_path.replace(pdf_path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()
    return True
