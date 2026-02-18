"""Shared helpers for FSCP scripts."""

from .files import (
    build_archive_destination,
    build_destination,
    collect_files,
    move_to_dir,
)
from .metadata import (
    build_xmp_mm_metadata,
    extract_pdf_document_id,
    generate_document_id,
    normalize_document_id,
    resolve_excel_document_id,
    set_xmp_mm_metadata_inplace,
)
from .settings import get_settings_path, load_settings, save_settings

__all__ = [
    "build_archive_destination",
    "build_destination",
    "collect_files",
    "move_to_dir",
    "build_xmp_mm_metadata",
    "extract_pdf_document_id",
    "generate_document_id",
    "normalize_document_id",
    "resolve_excel_document_id",
    "set_xmp_mm_metadata_inplace",
    "get_settings_path",
    "load_settings",
    "save_settings",
]
