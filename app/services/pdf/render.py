from __future__ import annotations

import asyncio
from pathlib import Path

import pypdfium2 as pdfium

from app.core.settings import get_settings

# pypdfium2 / PDFium is not safe to open concurrently across threads. Open and
# render under this lock so only one PdfDocument context is active at a time.
# This doesn't hurt throughput because rendering is ~100-200 ms per page while
# the per-page LLM call is seconds; the LLM step still runs in parallel.
_PDFIUM_LOCK = asyncio.Lock()


def _count_sync(pdf_path: Path) -> int:
    pdf = pdfium.PdfDocument(str(pdf_path))
    try:
        return len(pdf)
    finally:
        pdf.close()


async def count_pages(pdf_path: Path) -> int:
    async with _PDFIUM_LOCK:
        return await asyncio.to_thread(_count_sync, pdf_path)


def _render_one_sync(pdf_path: Path, out_dir: Path, index: int, dpi: int) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf = pdfium.PdfDocument(str(pdf_path))
    try:
        scale = dpi / 72.0
        bitmap = pdf[index].render(scale=scale)
        image = bitmap.to_pil()
        p = out_dir / f"page_{index:04d}.png"
        image.save(p, format="PNG")
        return p
    finally:
        pdf.close()


async def render_page(
    pdf_path: Path, out_dir: Path, index: int, dpi: int | None = None
) -> Path:
    dpi = dpi or get_settings().pdf_render_dpi
    async with _PDFIUM_LOCK:
        return await asyncio.to_thread(_render_one_sync, pdf_path, out_dir, index, dpi)
