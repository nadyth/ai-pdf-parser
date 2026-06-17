from __future__ import annotations

import asyncio
from pathlib import Path

import pdfplumber

from app.services.pdf.text import clean_text


def _extract_one_sync(pdf_path: Path, index: int) -> str:
    with pdfplumber.open(pdf_path) as pdf:
        if index >= len(pdf.pages):
            return ""
        raw = pdf.pages[index].extract_text() or ""
        # Strip NUL bytes (unmapped glyphs in non-Latin scripts) before they
        # ever reach the LLM or Postgres.
        return clean_text(raw) or ""


async def extract_page_text(pdf_path: Path, index: int) -> str:
    return await asyncio.to_thread(_extract_one_sync, pdf_path, index)
