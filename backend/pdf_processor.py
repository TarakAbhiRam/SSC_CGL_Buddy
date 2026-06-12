"""PDF text extraction + chunking.

Shared by the offline prep pipeline (``scripts/``) and the runtime user-upload
path. Digital PDFs are read directly via PyMuPDF; pages with no extractable
text (scanned images) are routed to an OCR hook that is currently a **stub**.

Real-world (especially free) SSC PDFs are noisy: watermarks, Telegram/website
promos, page numbers, decorative rules, repeated headers/footers. We filter
that junk at the line level, drop repeated boilerplate, and classify the
surviving chunks as ``question`` vs ``passage`` so downstream generation works
from clean, relevant context.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

# Minimum characters on a page before we assume it has real (non-scanned) text.
_MIN_PAGE_TEXT = 20

# --- Scanned-import (Gemini vision OCR) limits -------------------------------
# Typical question papers are short; cap pages/size to protect the user's API
# quota and keep payloads small. Only used by the structured-import path.
MAX_OCR_PAGES = 20
MAX_IMPORT_BYTES = 15 * 1024 * 1024  # ~15 MB
OCR_DPI = 200
IMPORT_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}

# --- Junk / quality heuristics -----------------------------------------------

# Promotional / boilerplate noise common in free exam PDFs.
_JUNK_PATTERNS = [
    re.compile(r"https?://|www\.", re.I),
    re.compile(r"\.(com|in|org|net|co)\b", re.I),
    re.compile(r"\b(telegram|whatsapp|youtube|facebook|instagram|t\.me|gmail)\b", re.I),
    re.compile(r"\b(subscribe|join (us|our)|follow us|click here|download (now|the|pdf|free)|visit (us|our))\b", re.I),
    re.compile(r"\ball rights reserved\b|©|\bcopyright\b", re.I),
    re.compile(r"^\s*page\s*\d+\s*(of\s*\d+)?\s*$", re.I),
]

# Signals that a chunk contains actual question content.
_QUESTION_HINTS = re.compile(
    r"\?"
    r"|\b(directions?|which|what|who|whom|when|where|why|how|find|calculate|"
    r"choose|select|identify|correct|incorrect|following|statement|option)\b"
    r"|\(\s*[a-dA-D1-4]\s*\)"            # (a) (b) ... or (1) (2) ...
    r"|(^|\s)[a-dA-D1-4][\.\)]\s",       # a. b)  1. 2) option markers
    re.I | re.M,
)

# Minimum words / alphabetic ratio for a chunk to be considered useful.
_MIN_CHUNK_WORDS = 15
_MIN_ALPHA_RATIO = 0.45


def _normalize_line(line: str) -> str:
    return re.sub(r"\s+", " ", line).strip()


def is_junk_line(line: str) -> bool:
    """True if a single line is boilerplate/noise rather than real content."""
    s = _normalize_line(line)
    if not s:
        return True
    if len(s) <= 2:
        return True
    # Bare page numbers / roman numerals / decorative separators.
    if re.fullmatch(r"[\divxlcdmIVXLCDM.\-—–_|•·*=~]+", s):
        return True
    for pat in _JUNK_PATTERNS:
        if pat.search(s):
            return True
    # Mostly non-alphanumeric (rules of dots/dashes, decoration).
    alnum = sum(c.isalnum() for c in s)
    if alnum / max(1, len(s)) < 0.4:
        return True
    return False


def clean_text(text: str, boilerplate: Optional[set] = None) -> str:
    """Drop junk lines (and known repeated boilerplate) from a block of text."""
    boilerplate = boilerplate or set()
    kept: List[str] = []
    for raw in text.splitlines():
        line = _normalize_line(raw)
        if not line:
            continue
        if line in boilerplate:
            continue
        if is_junk_line(line):
            continue
        kept.append(line)
    return "\n".join(kept)


def _detect_boilerplate(page_texts: List[str], min_fraction: float = 0.5) -> set:
    """Find short lines repeated across many pages (headers/footers/watermarks)."""
    if len(page_texts) < 3:
        return set()
    counts: Counter = Counter()
    for text in page_texts:
        seen = {
            _normalize_line(l)
            for l in text.splitlines()
            if 0 < len(_normalize_line(l)) <= 80
        }
        counts.update(seen)
    threshold = max(2, int(len(page_texts) * min_fraction))
    return {line for line, n in counts.items() if n >= threshold}


def classify_chunk(text: str) -> Optional[str]:
    """Classify a chunk's content type, or return ``None`` if it's junk.

    Returns ``"question"`` for MCQ/question-like text, ``"passage"`` for other
    substantive prose, or ``None`` when the chunk is too short / too noisy to
    keep.
    """
    words = text.split()
    if len(words) < _MIN_CHUNK_WORDS:
        return None
    alpha = sum(c.isalpha() for c in text)
    if alpha / max(1, len(text)) < _MIN_ALPHA_RATIO:
        return None
    return "question" if _QUESTION_HINTS.search(text) else "passage"


class OCRNotConfigured(RuntimeError):
    """Raised when a scanned page needs OCR but no engine is wired up yet."""


class ImportTooLarge(RuntimeError):
    """Raised when a file exceeds the scanned-import page/size limits."""


def render_pdf_pages_png(
    pdf_path: Path,
    dpi: int = OCR_DPI,
    max_pages: int = MAX_OCR_PAGES,
) -> List[Dict[str, Any]]:
    """Render each PDF page to PNG bytes for vision OCR.

    Returns ``[{page_number, png}]``. Raises :class:`ImportTooLarge` if the file
    is too big or has more pages than ``max_pages``.
    """
    import fitz  # PyMuPDF

    pdf_path = Path(pdf_path)
    if pdf_path.stat().st_size > MAX_IMPORT_BYTES:
        raise ImportTooLarge(
            f"This file is larger than {MAX_IMPORT_BYTES // (1024 * 1024)} MB."
        )
    out: List[Dict[str, Any]] = []
    with fitz.open(pdf_path) as doc:
        if doc.page_count > max_pages:
            raise ImportTooLarge(
                f"This PDF has {doc.page_count} pages; scanned import is capped at "
                f"{max_pages} to protect your API quota. Split it into smaller files."
            )
        for index, page in enumerate(doc):
            pix = page.get_pixmap(dpi=dpi)
            out.append({"page_number": index + 1, "png": pix.tobytes("png")})
    return out


def render_image_png(img_path: Path) -> bytes:
    """Load an image file and return normalised PNG bytes for vision OCR.

    Raises :class:`ImportTooLarge` if the file exceeds the size cap.
    """
    import fitz  # PyMuPDF

    img_path = Path(img_path)
    if img_path.stat().st_size > MAX_IMPORT_BYTES:
        raise ImportTooLarge(
            f"This image is larger than {MAX_IMPORT_BYTES // (1024 * 1024)} MB."
        )
    pix = fitz.Pixmap(str(img_path))
    # Drop alpha / convert exotic colourspaces (e.g. CMYK) to RGB for PNG output.
    if pix.alpha or pix.n > 3:
        pix = fitz.Pixmap(fitz.csRGB, pix)
    return pix.tobytes("png")


# --- Structured MCQ parsing from digital PDFs (no LLM) -----------------------
# Reads ready-made MCQs straight out of a text-based PDF so importing questions
# costs nothing and needs no API key. Scanned/image PDFs (no extractable text)
# yield nothing here and should be imported as images via vision OCR instead.

_OPT_INDEX = {"a": 0, "b": 1, "c": 2, "d": 3, "1": 0, "2": 1, "3": 2, "4": 3}

# Question start: optional "Q"/"Q." prefix, a number, then . ) or :  then text.
_QSTART_RE = re.compile(r"^(?:Q\s*\.?\s*)?(\d{1,3})\s*[\.\)\:]\s*(.+)$", re.I)
# A single option line: optional "(", a label a-d/1-4, then ) or . then text.
_OPT_RE = re.compile(r"^\(?\s*([A-Da-d1-4])\s*[\)\.]\s*(.+)$")
# An answer line: "Ans", "Answer", "Correct answer/option", etc. + a label.
_ANS_RE = re.compile(
    r"^(?:ans(?:wer)?|correct\s*(?:answer|option)?)\s*[\.\:\-\)]*\s*"
    r"\(?\s*([A-Da-d1-4])\s*\)?",
    re.I,
)
# Inline option markers like "(a)" used when all options sit on one line.
_INLINE_OPT_RE = re.compile(r"\(\s*([A-Da-d1-4])\s*\)")


def _split_inline_options(blob: str):
    """Split "stem (a) X (b) Y (c) Z (d) W" into (stem, [X, Y, Z, W]).

    Returns ``(stem, options)`` where options is empty if fewer than two inline
    markers are present (i.e. not an inline-option layout).
    """
    marks = list(_INLINE_OPT_RE.finditer(blob))
    if len(marks) < 2:
        return blob.strip(), []
    stem = blob[: marks[0].start()].strip()
    options = []
    for i, m in enumerate(marks):
        start = m.end()
        end = marks[i + 1].start() if i + 1 < len(marks) else len(blob)
        options.append(blob[start:end].strip())
    return stem, options


def _finalize(cur, out):
    """Append a completed question to ``out`` if it has a stem, 4 options, ans."""
    if not cur:
        return
    stem = (cur.get("stem") or "").strip()
    opts = [o.strip() for o in cur.get("options", []) if o.strip()]
    ans = cur.get("answer")
    if stem and len(opts) == 4 and ans is not None and 0 <= ans < 4:
        out.append({
            "question": stem,
            "options": opts,
            "correct_index": ans,
            "category": None,
            "difficulty": "medium",
            "explanation": "",
        })


def parse_mcqs_from_text(text: str) -> List[Dict[str, Any]]:
    """Parse MCQs from plain text extracted from a digital PDF.

    Recognises numbered questions, options labelled a-d or 1-4 (one per line or
    inline on a single line), and an answer line ("Ans.", "Answer:", etc.).
    Only questions with exactly four options *and* a detected answer are kept.
    """
    out: List[Dict[str, Any]] = []
    cur: Optional[Dict[str, Any]] = None
    mode: Optional[str] = None  # "stem" | "options"

    for raw in (ln.strip() for ln in text.splitlines()):
        if not raw:
            continue

        # 1) Answer line (only meaningful while a question is open).
        if cur is not None:
            m = _ANS_RE.match(raw)
            if m:
                idx = _OPT_INDEX.get(m.group(1).lower())
                if idx is not None:
                    cur["answer"] = idx
                continue

        # 2) Inline options for the current question ("(a) X (b) Y ...").
        if cur is not None and not cur["options"]:
            _, inline = _split_inline_options(raw)
            if len(inline) >= 2:
                cur["options"] = inline[:4]
                mode = "options"
                continue

        # 3) Single option line, taken only if it's the next expected label
        #    (a/1 first, then b/2, ...). This disambiguates numeric options
        #    from question numbers.
        m_opt = _OPT_RE.match(raw)
        if m_opt and cur is not None and len(cur["options"]) < 4:
            idx = _OPT_INDEX[m_opt.group(1).lower()]
            if idx == len(cur["options"]):
                cur["options"].append(m_opt.group(2).strip())
                mode = "options"
                continue

        # 4) New question start.
        m_q = _QSTART_RE.match(raw)
        if m_q:
            _finalize(cur, out)
            stem, inline = _split_inline_options(m_q.group(2))
            cur = {"stem": stem, "options": inline[:4], "answer": None}
            mode = "options" if inline else "stem"
            continue

        # 5) Continuation of the current stem or last option.
        if cur is not None:
            if mode == "options" and cur["options"]:
                cur["options"][-1] += " " + raw
            elif mode == "stem":
                cur["stem"] += " " + raw

    _finalize(cur, out)
    return out


def parse_mcqs_from_pdf(pdf_path: Path) -> List[Dict[str, Any]]:
    """Extract MCQs from a digital (text-based) PDF without any LLM call.

    Returns ``[]`` for scanned/image PDFs that have no extractable text.
    Raises :class:`ImportTooLarge` if the file is over the size cap.
    """
    import fitz  # PyMuPDF

    pdf_path = Path(pdf_path)
    if pdf_path.stat().st_size > MAX_IMPORT_BYTES:
        raise ImportTooLarge(
            f"This file is larger than {MAX_IMPORT_BYTES // (1024 * 1024)} MB."
        )
    parts: List[str] = []
    with fitz.open(pdf_path) as doc:
        for page in doc:
            parts.append(page.get_text() or "")
    return parse_mcqs_from_text("\n".join(parts))


def ocr_page(page) -> str:
    """OCR hook for image-only pages. STUB — wire to Tesseract/cloud later.

    Intended implementation (deferred):
        pix = page.get_pixmap(dpi=300)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        return pytesseract.image_to_string(img)
    """
    raise OCRNotConfigured(
        "Scanned/image page encountered but OCR is not configured. "
        "Wire up ocr_page() in backend/pdf_processor.py (e.g. pytesseract)."
    )


def extract_pages(pdf_path: Path, use_ocr: bool = False) -> Iterator[Dict[str, Any]]:
    """Yield ``{page_number, text}`` for each page of a PDF.

    If a page has no extractable text and ``use_ocr`` is True, attempts OCR.
    With ``use_ocr`` False, image-only pages are skipped (logged as empty).
    """
    import fitz  # PyMuPDF

    with fitz.open(pdf_path) as doc:
        for index, page in enumerate(doc):
            text = (page.get_text() or "").strip()
            if len(text) < _MIN_PAGE_TEXT and use_ocr:
                try:
                    text = (ocr_page(page) or "").strip()
                except OCRNotConfigured:
                    raise
            yield {"page_number": index + 1, "text": text}


def chunk_text(text: str, chunk_size: int = 800, overlap: int = 150) -> List[str]:
    """Split text into overlapping word-based chunks."""
    words = text.split()
    if not words:
        return []
    step = max(1, chunk_size - overlap)
    chunks: List[str] = []
    for start in range(0, len(words), step):
        window = words[start : start + chunk_size]
        if window:
            chunks.append(" ".join(window))
        if start + chunk_size >= len(words):
            break
    return chunks


def _chunk_id(source: str, page: int, index: int, text: str) -> str:
    digest = hashlib.sha1(f"{source}|{page}|{index}|{text}".encode("utf-8")).hexdigest()
    return digest[:16]


def process_pdf(
    pdf_path: Path,
    use_ocr: bool = False,
    topic_tag: Optional[str] = None,
    difficulty: Optional[str] = None,
    chunk_size: int = 800,
    overlap: int = 150,
) -> Dict[str, Any]:
    """Full pipeline for one PDF.

    Extracts text, strips junk lines + repeated boilerplate, chunks the clean
    text, and classifies each chunk (``question``/``passage``), dropping ones
    that are too short or too noisy to be useful.

    Returns ``{chunks, kept, skipped, total, questions, passages}`` where
    ``chunks`` is a list of ``{id, text, metadata}`` ready for the vector store.
    """
    pdf_path = Path(pdf_path)
    source = pdf_path.name

    # First pass: gather raw page text so we can spot repeated boilerplate.
    pages = list(extract_pages(pdf_path, use_ocr=use_ocr))
    boilerplate = _detect_boilerplate([p["text"] for p in pages])

    chunks: List[Dict[str, Any]] = []
    total = kept = skipped = questions = passages = 0

    for page in pages:
        cleaned = clean_text(page["text"], boilerplate)
        if not cleaned:
            continue
        for i, chunk in enumerate(chunk_text(cleaned, chunk_size, overlap)):
            total += 1
            content_type = classify_chunk(chunk)
            if content_type is None:
                skipped += 1
                continue
            kept += 1
            if content_type == "question":
                questions += 1
            else:
                passages += 1
            metadata: Dict[str, Any] = {
                "source_pdf": source,
                "page_number": page["page_number"],
                "content_type": content_type,
            }
            if topic_tag:
                metadata["topic_tag"] = topic_tag
            if difficulty:
                metadata["difficulty"] = difficulty
            chunks.append(
                {
                    "id": _chunk_id(source, page["page_number"], i, chunk),
                    "text": chunk,
                    "metadata": metadata,
                }
            )

    return {
        "chunks": chunks,
        "kept": kept,
        "skipped": skipped,
        "total": total,
        "questions": questions,
        "passages": passages,
    }
