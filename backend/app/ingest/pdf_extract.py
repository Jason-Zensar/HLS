"""Stage 2 - PDF extraction.

Primary extractor: PyMuPDF (text lines with font metrics and bounding boxes, plus
PyMuPDF's table finder on pages that contain ruling graphics or table captions).
Fallback: RapidOCR (local ONNX model, no network) for pages without a usable text layer.

Design choice: Docling was evaluated but not adopted - it pulls in PyTorch and large
layout models, which makes a 200-document local deployment slow and heavy. PyMuPDF
gives us page-exact text, coordinates, fonts (for heading recognition) and tables,
which is what downstream provenance needs. See docs/ARCHITECTURE.md.

Output is a plain JSON-serialisable dict so it can be checkpointed to disk.
"""
from __future__ import annotations

import logging
import re
from collections import Counter
from typing import Any

import pymupdf

log = logging.getLogger(__name__)

_ocr_engine = None


def _get_ocr():
    global _ocr_engine
    if _ocr_engine is None:
        from rapidocr_onnxruntime import RapidOCR  # imported lazily: heavy

        _ocr_engine = RapidOCR()
    return _ocr_engine


# ---------------------------------------------------------------------------
# Word reconstruction for PDFs whose text layer is letter-spaced
# ("Pal b ocicli b"). Detected per line; normal lines keep PyMuPDF's own spacing.
# ---------------------------------------------------------------------------

def _otsu_threshold(vals: list[float]) -> tuple[float, float, float] | None:
    v = sorted(vals)
    best = None
    for i in range(1, len(v)):
        a, b = v[:i], v[i:]
        ma, mb = sum(a) / len(a), sum(b) / len(b)
        score = len(a) * len(b) * (ma - mb) ** 2
        if best is None or score > best[0]:
            best = (score, (v[i - 1] + v[i]) / 2, ma, mb)
    return (best[1], best[2], best[3]) if best else None


def _is_letter_spaced(text: str) -> bool:
    toks = text.split()
    if len(toks) < 5:
        return False
    singles = sum(1 for t in toks if len(t) == 1 and t.isalpha())
    return singles / len(toks) > 0.3


def _rebuild_words(raw_line: dict) -> str:
    chars = [c for s in raw_line["spans"] for c in s["chars"] if not c["c"].isspace()]
    if not chars:
        return ""
    size = max((s["size"] for s in raw_line["spans"]), default=10) or 10
    gaps = [chars[i]["bbox"][0] - chars[i - 1]["bbox"][2] for i in range(1, len(chars))]
    thr = 0.25 * size
    if len(gaps) >= 6:
        o = _otsu_threshold(gaps)
        if o and o[2] - o[1] > 0.12 * size:
            thr = max(o[0], 0.1 * size)
    out = [chars[0]["c"]]
    for i in range(1, len(chars)):
        if gaps[i - 1] > thr:
            out.append(" ")
        out.append(chars[i]["c"])
    return "".join(out)


# ---------------------------------------------------------------------------

_TABLE_CAPTION = re.compile(r"^\s*(Table|TABLE)\s+[\dA-Z]+[\.:\s-]")
_NUM_RE = re.compile(r"\d+")


def _norm_furniture(t: str) -> str:
    return _NUM_RE.sub("#", t.strip().lower())


def _clean(t: str) -> str:
    t = t.replace(" ", " ").replace("�", "'").replace("’", "'").replace("‘", "'")
    t = t.replace("“", '"').replace("”", '"').replace("–", "-").replace("—", "-")
    t = t.replace("‐", "-").replace("‑", "-").replace("", "•").replace("∀", "•")
    return re.sub(r"[ \t]+", " ", t).strip()


def classify_document(doc: pymupdf.Document, min_chars: int) -> dict[str, Any]:
    """Text-based / image-based / mixed detection, done before full extraction."""
    empty_pages = []
    for i, page in enumerate(doc):
        if len(page.get_text("text").strip()) < min_chars:
            empty_pages.append(i + 1)
    n = len(doc)
    ratio = len(empty_pages) / n if n else 1
    kind = "text" if ratio < 0.05 else ("scanned" if ratio > 0.8 else "mixed")
    return {"kind": kind, "low_text_pages": empty_pages}


def extract_pdf(path: str, *, ocr_enabled: bool = True, min_chars: int = 40, tables: bool = True) -> dict[str, Any]:
    doc = pymupdf.open(path)
    if doc.needs_pass:
        raise ValueError("Document is encrypted and cannot be read without a password")
    if len(doc) == 0:
        raise ValueError("Document has no pages")

    cls = classify_document(doc, min_chars)
    pages: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    spaced_lines = 0

    for pno in range(len(doc)):
        page = doc[pno]
        pw, ph = page.rect.width, page.rect.height
        page_rec: dict[str, Any] = {"page": pno + 1, "width": pw, "height": ph, "lines": [], "tables": [],
                                    "method": "pymupdf", "confidence": 1.0}
        try:
            raw = page.get_text("rawdict", flags=pymupdf.TEXT_PRESERVE_WHITESPACE)
        except Exception as e:  # corrupted content stream
            warnings.append({"page": pno + 1, "severity": "error", "code": "page_unreadable", "message": str(e)[:300]})
            raw = {"blocks": []}

        for bno, block in enumerate(raw.get("blocks", [])):
            for line in block.get("lines", []):
                spans = line.get("spans", [])
                if not spans:
                    continue
                native = "".join("".join(c["c"] for c in s["chars"]) for s in spans)
                spaced = _is_letter_spaced(native)
                text = _rebuild_words(line) if spaced else native
                text = _clean(text)
                if not text:
                    continue
                if spaced:
                    spaced_lines += 1
                sizes = [s["size"] for s in spans if "".join(c["c"] for c in s["chars"]).strip()]
                bold = any((s["flags"] & 16) or "bold" in s.get("font", "").lower() for s in spans
                           if "".join(c["c"] for c in s["chars"]).strip())
                x0, y0, x1, y1 = line["bbox"]
                page_rec["lines"].append({
                    "text": text, "size": round(max(sizes) if sizes else spans[0]["size"], 1), "bold": bool(bold),
                    "bbox": [round(x0, 1), round(y0, 1), round(x1, 1), round(y1, 1)], "block": bno,
                    "spaced": spaced,
                })

        text_chars = sum(len(l["text"]) for l in page_rec["lines"])
        if text_chars < min_chars:
            has_images = bool(page.get_images(full=False))
            if ocr_enabled and has_images:
                try:
                    page_rec["lines"], conf = _ocr_page(page)
                    page_rec["method"], page_rec["confidence"] = "ocr", conf
                    warnings.append({"page": pno + 1, "severity": "info", "code": "ocr_used",
                                     "message": f"No text layer; OCR applied (mean confidence {conf:.2f})"})
                    if conf < 0.8:
                        warnings.append({"page": pno + 1, "severity": "warning", "code": "low_ocr_confidence",
                                         "message": f"OCR confidence {conf:.2f} is below 0.80"})
                except Exception as e:
                    warnings.append({"page": pno + 1, "severity": "error", "code": "ocr_failed", "message": str(e)[:300]})
            elif has_images:
                warnings.append({"page": pno + 1, "severity": "warning", "code": "no_text_layer",
                                 "message": "Page has no text layer and OCR is disabled"})
            elif text_chars == 0:
                warnings.append({"page": pno + 1, "severity": "info", "code": "blank_page", "message": "Page is blank"})

        if tables and page_rec["method"] == "pymupdf":
            page_rec["tables"] = _find_tables(page, page_rec["lines"], warnings, pno + 1)
        pages.append(page_rec)

    _strip_furniture(pages)
    if spaced_lines:
        warnings.append({"page": None, "severity": "warning", "code": "letter_spaced_text",
                         "message": f"{spaced_lines} lines had a letter-spaced text layer; word boundaries were "
                                    f"reconstructed geometrically and may contain errors"})
    meta = doc.metadata or {}
    toc = doc.get_toc(simple=True)
    result = {
        "page_count": len(doc), "kind": cls["kind"], "low_text_pages": cls["low_text_pages"],
        "pdf_title": (meta.get("title") or "").strip(), "toc": [[lvl, _clean(t), p] for lvl, t, p in toc],
        "pages": pages, "warnings": warnings,
    }
    doc.close()
    return result


def _ocr_page(page: pymupdf.Page) -> tuple[list[dict], float]:
    zoom = 200 / 72
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), colorspace=pymupdf.csRGB)
    import numpy as np

    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
    result, _ = _get_ocr()(img)
    lines, confs = [], []
    for box, text, score in result or []:
        xs = [p[0] / zoom for p in box]
        ys = [p[1] / zoom for p in box]
        t = _clean(text)
        if not t:
            continue
        confs.append(float(score))
        lines.append({"text": t, "size": round((max(ys) - min(ys)) * 0.8, 1), "bold": False,
                      "bbox": [round(min(xs), 1), round(min(ys), 1), round(max(xs), 1), round(max(ys), 1)],
                      "block": 0, "spaced": False, "ocr_conf": round(float(score), 3)})
    lines.sort(key=lambda l: (round(l["bbox"][1] / 4), l["bbox"][0]))
    return lines, (sum(confs) / len(confs) if confs else 0.0)


def _find_tables(page: pymupdf.Page, lines: list[dict], warnings: list, pno: int) -> list[dict]:
    has_caption = any(_TABLE_CAPTION.match(l["text"]) for l in lines)
    try:
        n_draw = len(page.get_drawings())
    except Exception:
        n_draw = 0
    if n_draw < 6 and not has_caption:
        return []
    try:
        found = page.find_tables()
    except Exception as e:
        warnings.append({"page": pno, "severity": "warning", "code": "table_detection_failed", "message": str(e)[:200]})
        return []
    out = []
    for t in found.tables:
        try:
            cells = t.extract()
        except Exception as e:
            warnings.append({"page": pno, "severity": "warning", "code": "table_extract_failed", "message": str(e)[:200]})
            continue
        rows = [[_clean(c) if isinstance(c, str) else "" for c in row] for row in cells]
        rows = [r for r in rows if any(r)]
        if len(rows) < 2 or max((len(r) for r in rows), default=0) < 2:
            continue  # single-row / single-column boxes are usually framed paragraphs
        n_cells = sum(len(r) for r in rows)
        empty = sum(1 for r in rows for c in r if not c)
        tw = []
        if n_cells and empty / n_cells > 0.6:
            tw.append("sparse table: more than 60% of cells are empty (merged cells or rotated layout)")
        bx = [round(v, 1) for v in t.bbox]
        # caption = nearest "Table N" line directly above the table
        title = ""
        above = [l for l in lines if l["bbox"][3] <= bx[1] + 2 and _TABLE_CAPTION.match(l["text"])]
        if above:
            cap = max(above, key=lambda l: l["bbox"][3])
            if bx[1] - cap["bbox"][3] < 80:
                title = cap["text"]
                nxt = [l for l in lines if 0 < l["bbox"][1] - cap["bbox"][3] < 14 and l["bbox"][3] <= bx[1] + 2]
                if nxt and len(title) < 30:
                    title = f"{title} {nxt[0]['text']}"
        out.append({"bbox": bx, "rows": rows, "n_rows": len(rows), "n_cols": max(len(r) for r in rows),
                    "title": title, "warnings": tw})
    return out


def _strip_furniture(pages: list[dict]) -> None:
    """Remove running headers/footers: lines in the top/bottom 9% of the page whose
    digit-normalised text repeats on at least 30% of pages."""
    n = len(pages)
    if n < 4:
        return
    counter: Counter[str] = Counter()
    for p in pages:
        seen = set()
        for l in p["lines"]:
            y = l["bbox"][1]
            if y < p["height"] * 0.09 or y > p["height"] * 0.91:
                k = _norm_furniture(l["text"])
                if k not in seen:
                    counter[k] += 1
                    seen.add(k)
    furniture = {k for k, c in counter.items() if c >= max(3, 0.3 * n)}
    for p in pages:
        keep = []
        for l in p["lines"]:
            y = l["bbox"][1]
            edge = y < p["height"] * 0.09 or y > p["height"] * 0.91
            if edge and (_norm_furniture(l["text"]) in furniture or re.fullmatch(r"(page\s*)?\d+(\s*(of|/)\s*\d+)?", l["text"].lower())):
                continue
            keep.append(l)
        p["lines"] = keep
