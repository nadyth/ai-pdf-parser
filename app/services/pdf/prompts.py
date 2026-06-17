"""Prompts for the default + rule-based extraction tasks."""

PAGE_VISION_PROMPT = """You are an OCR + layout-aware document understanding model.

Examine the page image and return the FULL textual content as accurately as possible.
Preserve reading order, paragraph breaks, list structure, table layout (use markdown
tables), headings, and column boundaries. Do NOT summarize, translate, or invent
content. If a region is unreadable, write [unreadable].

Output: ONLY the page text. No preamble, no commentary.
"""

CONSOLIDATION_PROMPT_TEMPLATE = """You merge two extractions of the SAME page into one
authoritative transcription.

You have:
1) VISION_TEXT: a layout-aware vision model's reading of the page image. Better at
   structure (columns, tables, ordering) but may misspell or hallucinate small tokens.
2) PLUMBER_TEXT: text extracted by pdfplumber directly from the PDF. Spelling and
   numbers are usually exact, but structure may be wrong.

Produce a single consolidated transcription:
- Trust PLUMBER_TEXT for exact tokens (words, numbers, IDs, names) when they overlap.
- Trust VISION_TEXT for layout, reading order, tables, headings.
- Keep markdown structure (headings, lists, tables).
- Do not summarize. Do not omit content present in either source.
- Output the consolidated page text only. No preamble.

---VISION_TEXT---
{vision_text}

---PLUMBER_TEXT---
{plumber_text}
"""

RULE_EXTRACTION_PROMPT_TEMPLATE = """You apply a user-defined extraction rule to a
document's consolidated text.

The rule (in markdown) describes what the document is, what to extract, and the
desired output format. Follow it literally.

Rules:
- Output MUST be valid JSON, no surrounding prose, no code fences.
- If the rule specifies a schema, conform exactly.
- If the rule asks for an array, return a JSON array at the top level.
- If something can't be extracted, use null (not made-up values).

---RULE (markdown)---
{rule_md}

---DOCUMENT TEXT---
{document_text}
"""

CHUNKED_RULE_EXTRACTION_PROMPT_TEMPLATE = """You apply a user-defined extraction rule
to ONE CHUNK of a long document. The document is too large to fit in one prompt, so
you are seeing part {chunk_idx} of {total_chunks} (covering pages {page_start}–{page_end},
1-indexed). Other chunks are processed independently; their outputs will be merged.

Rules:
- Apply the user rule to THIS CHUNK as if it were a standalone document.
- Output MUST be valid JSON, no surrounding prose, no code fences.
- If the rule asks for an array, return only the items that appear in this chunk.
- If the chunk contains no matching content, return [] (or {{}} if the rule asks
  for an object).
- Do NOT renumber items globally — return them as they appear here.
- If something can't be extracted, use null (not made-up values).

---RULE (markdown)---
{rule_md}

---CHUNK TEXT---
{chunk_text}
"""
