"""MimeDetectProcessor (M25 P3 #7, D276).

MIME-type detection по magic bytes (Ponytail YAGNI: stdlib only).
Pattern (D276): thin wrapper.
"""
# ruff: noqa: E501
from __future__ import annotations

from src.backend.core.logging import get_logger

_logger = get_logger("dsl.rpa.mime_detect")

__all__ = ("MimeDetectProcessor",)


# Magic bytes signatures (top 8 bytes per format)
# Format: (signature, offset, mime_type)
_MAGIC_SIGNATURES: tuple[tuple[bytes, int, str], ...] = (
    (b"%PDF-", 0, "application/pdf"),
    (b"\x89PNG\r\n\x1a\n", 0, "image/png"),
    (b"\xff\xd8\xff", 0, "image/jpeg"),
    (b"GIF87a", 0, "image/gif"),
    (b"GIF89a", 0, "image/gif"),
    (b"PK\x03\x04", 0, "application/zip"),
    (b"PK\x05\x06", 0, "application/zip"),
    (b"\x1f\x8b", 0, "application/gzip"),
    (b"BZh", 0, "application/x-bzip2"),
    (b"7z\xbc\xaf\x27\x1c", 0, "application/x-7z-compressed"),
    (b"Rar!\x1a\x07", 0, "application/vnd.rar"),
    (b"\x7fELF", 0, "application/x-elf"),
    (b"MZ", 0, "application/x-dosexec"),
    (b"\x1a\x45\xdf\xa3", 0, "video/x-matroska"),
    (b"fLaC", 0, "audio/flac"),
    (b"ID3", 0, "audio/mpeg"),
    (b"OggS", 0, "audio/ogg"),
    (b"RIFF", 0, "audio/wav"),
    (b"OggS", 0, "video/ogg"),
    (b"<?xml", 0, "application/xml"),
    (b"<!DOCTYPE html", 0, "text/html"),
    (b"<!doctype html", 0, "text/html"),
    (b"<html", 0, "text/html"),
    (b"#!", 0, "text/x-shellscript"),
    (b"#!/bin/sh", 0, "text/x-shellscript"),
    (b"#!/usr/bin/env", 0, "text/x-shellscript"),
    (b"SQLite format 3", 0, "application/x-sqlite3"),
)


class MimeDetectProcessor:
    """MIME-type detection по magic bytes (stdlib only, D276)."""

    def detect(self, data: bytes) -> str:
        """Detect MIME-type по magic bytes.

        Args:
            data: file content (первые 16 байт достаточно).

        Returns:
            MIME-type string (default: application/octet-stream).
        """
        if not data:
            return "application/octet-stream"
        head = data[:16]
        for sig, offset, mime in _MAGIC_SIGNATURES:
            if head[offset:offset + len(sig)] == sig:
                return mime
        return "application/octet-stream"
