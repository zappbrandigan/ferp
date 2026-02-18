from __future__ import annotations

import re
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject, NumberObject, StreamObject

_DOC_ID_RE = re.compile(r"ferp:DocumentID=\{(uuid:)?([0-9a-fA-F-]+)\}")
_DOC_ID_PROP_NAME = "ferp:DocumentID"
_MSO_PROPERTY_TYPE_STRING = 4


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
    match = re.search(r"(<x:xmpmeta\b.*?</x:xmpmeta>)", xmp_text, re.DOTALL)
    xml_payload = match.group(1) if match else xmp_text
    try:
        root = ET.fromstring(xml_payload)
    except ET.ParseError:
        return None, None
    ns = "http://ns.adobe.com/xap/1.0/mm/"
    doc_elem = root.find(f".//{{{ns}}}DocumentID")
    inst_elem = root.find(f".//{{{ns}}}InstanceID")
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
        xmp = getattr(reader, "xmp_metadata", None)
        if xmp is not None:
            raw = getattr(xmp, "xmpmeta", None)
            if raw:
                return _extract_xmp_mm_ids(str(raw))
    except Exception:
        pass

    try:
        root = reader.trailer.get("/Root", {})
        metadata = root.get("/Metadata")
        if metadata is None:
            return None, None
        raw = metadata.get_data()
        if not raw:
            return None, None
        text = raw.decode("utf-8", errors="ignore")
        return _extract_xmp_mm_ids(text)
    except Exception:
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
        xmp = getattr(reader, "xmp_metadata", None)
        if xmp is not None:
            raw = getattr(xmp, "xmpmeta", None)
            if raw:
                return _extract_xmp_mm_id_text(str(raw))
    except Exception:
        pass

    try:
        root = reader.trailer.get("/Root", {})
        metadata = root.get("/Metadata")
        if metadata is None:
            return None, None
        raw = metadata.get_data()
        if not raw:
            return None, None
        text = raw.decode("utf-8", errors="ignore")
        return _extract_xmp_mm_id_text(text)
    except Exception:
        return None, None


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
