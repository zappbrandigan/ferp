"""Shared helpers for FSCP scripts."""

from .files import (
    build_archive_destination,
    build_destination,
    collect_files,
    move_to_dir,
)
from .metadata import (
    FerpAgreement,
    FerpEffectiveDate,
    FerpXmpMetadata,
    build_xmp_mm_metadata,
    extract_pdf_ferp_metadata,
    extract_pdf_document_id,
    extract_pdf_xmp_text,
    generate_document_id,
    normalize_document_id,
    parse_ferp_xmp,
    read_pdf_ferp_metadata,
    resolve_excel_document_id,
    set_xmp_mm_metadata_inplace,
)
from .settings import get_settings_path, load_settings, save_settings

__all__ = [
    "build_archive_destination",
    "build_destination",
    "collect_files",
    "move_to_dir",
    "FerpAgreement",
    "FerpEffectiveDate",
    "FerpXmpMetadata",
    "build_xmp_mm_metadata",
    "extract_pdf_ferp_metadata",
    "extract_pdf_document_id",
    "extract_pdf_xmp_text",
    "generate_document_id",
    "normalize_document_id",
    "parse_ferp_xmp",
    "read_pdf_ferp_metadata",
    "resolve_excel_document_id",
    "set_xmp_mm_metadata_inplace",
    "get_settings_path",
    "load_settings",
    "save_settings",
]
