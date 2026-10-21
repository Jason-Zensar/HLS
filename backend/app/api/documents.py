"""Document library endpoints: upload, folder import, listing, inspection, retry, deletion, source viewing."""
from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Optional

import pymupdf
from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from app.config import get_settings
from app.core import metadb
from app.ingest import pipeline
from app.ingest.worker import enqueue, get_worker

router = APIRouter(prefix="/api/documents", tags=["documents"])


class UploadResult(BaseModel):
    filename: str
    status: str                  # queued | duplicate | rejected
    document_id: Optional[str] = None
    message: Optional[str] = None


class ImportResult(BaseModel):
    scanned: int
    queued: int
    duplicates: int
    rejected: int
    results: list[UploadResult]


@router.post("", response_model=list[UploadResult], summary="Upload one or more PDF protocols")
async def upload(files: list[UploadFile] = File(...)):
    out = []
    for f in files:
        data = await f.read()
        try:
            r = pipeline.register_pdf(data, f.filename or "upload.pdf", "upload")
            out.append(UploadResult(filename=r["filename"], status="queued", document_id=r["id"]))
        except pipeline.DuplicateDocument as e:
            out.append(UploadResult(filename=f.filename or "", status="duplicate", document_id=e.existing_id,
                                    message="Identical file already indexed (same SHA-256)"))
        except ValueError as e:
            out.append(UploadResult(filename=f.filename or "", status="rejected", message=str(e)))
    return out


# Folders under the project root that never contain dataset PDFs (documentation, code, runtime data).
IMPORT_SKIP = {"docs", "backend", "frontend", "scripts", "data", ".git", ".venv", "node_modules", "dist"}


def import_dataset_folder() -> ImportResult:
    s = get_settings()
    root = Path(s.import_dir)
    files = sorted(p for p in root.rglob("*.pdf")
                   if s.data_dir not in p.parents and not (set(p.relative_to(root).parts[:-1]) & IMPORT_SKIP))
    results, q, dup, rej = [], 0, 0, 0
    for p in files:
        try:
            r = pipeline.register_pdf(p.read_bytes(), p.name, "folder-import")
            results.append(UploadResult(filename=p.name, status="queued", document_id=r["id"]))
            q += 1
        except pipeline.DuplicateDocument as e:
            results.append(UploadResult(filename=p.name, status="duplicate", document_id=e.existing_id))
            dup += 1
        except ValueError as e:
            results.append(UploadResult(filename=p.name, status="rejected", message=str(e)))
            rej += 1
    metadb.audit("import.folder", f"Folder import: {q} queued, {dup} duplicates, {rej} rejected")
    return ImportResult(scanned=len(files), queued=q, duplicates=dup, rejected=rej, results=results)


@router.post("/import-folder", response_model=ImportResult, summary="Queue every PDF in the server-side import folder")
def import_folder():
    return import_dataset_folder()


@router.get("", summary="List documents with filters")
def list_documents(q: str = "", status: str = "", limit: int = Query(500, le=2000), offset: int = 0):
    where, params = [], []
    if q:
        where.append("(filename LIKE ? OR title LIKE ? OR nct_id LIKE ? OR id LIKE ? OR sponsor LIKE ?)")
        params += [f"%{q}%"] * 5
    if status:
        where.append("status = ?")
        params.append(status)
    sql = ("SELECT d.*, (SELECT count(*) FROM warnings w WHERE w.doc_id=d.id AND w.severity IN ('warning','error')) AS warning_count "
           "FROM documents d" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY uploaded_at DESC LIMIT ? OFFSET ?")
    rows = metadb.q(sql, params + [limit, offset])
    for r in rows:
        r.pop("stored_name", None)
    total = metadb.q1("SELECT count(*) c FROM documents" + (" WHERE " + " AND ".join(where) if where else ""), params)["c"]
    return {"total": total, "items": rows}


def _doc_or_404(doc_id: str) -> dict:
    d = metadb.q1("SELECT * FROM documents WHERE id = ?", (doc_id,))
    if not d:
        raise HTTPException(404, "Document not found")
    return d


@router.get("/{doc_id}", summary="Document detail with extraction structure summary")
def get_document(doc_id: str):
    d = _doc_or_404(doc_id)
    d.pop("stored_name", None)
    d["warnings"] = metadb.q("SELECT page, stage, severity, code, message FROM warnings WHERE doc_id=? ORDER BY severity DESC, page", (doc_id,))
    d["jobs"] = metadb.q("SELECT id, kind, status, stage, attempts, error, created_at, updated_at, duration_s FROM jobs WHERE doc_id=? ORDER BY created_at DESC", (doc_id,))
    d["section_categories"] = metadb.q("SELECT category, count(*) n FROM sections WHERE doc_id=? GROUP BY category ORDER BY n DESC", (doc_id,))
    d["chunk_types"] = metadb.q("SELECT chunk_type, count(*) n FROM chunks WHERE doc_id=? GROUP BY chunk_type", (doc_id,))
    d["protocol_node_id"] = f"protocol:{doc_id}"
    d["review_items"] = metadb.q1("SELECT count(*) c FROM resolution_review WHERE doc_id=? AND status='pending'", (doc_id,))["c"]
    return d


@router.get("/{doc_id}/sections", summary="Detected section hierarchy")
def sections(doc_id: str):
    _doc_or_404(doc_id)
    rows = metadb.q("""SELECT s.*, (SELECT count(*) FROM chunks c WHERE c.section_id = s.id) AS chunk_count
                       FROM sections s WHERE doc_id=? ORDER BY ord""", (doc_id,))
    return rows


@router.get("/{doc_id}/chunks", summary="Evidence chunks (optionally by section or page)")
def chunks(doc_id: str, section_id: str = "", page: int = 0, chunk_type: str = "", limit: int = Query(200, le=2000), offset: int = 0):
    _doc_or_404(doc_id)
    where, params = ["doc_id = ?"], [doc_id]
    if section_id:
        where.append("section_id = ?")
        params.append(section_id)
    if page:
        where.append("page_start <= ? AND page_end >= ?")
        params += [page, page]
    if chunk_type:
        where.append("chunk_type = ?")
        params.append(chunk_type)
    rows = metadb.q(f"SELECT * FROM chunks WHERE {' AND '.join(where)} ORDER BY ord LIMIT ? OFFSET ?", params + [limit, offset])
    for r in rows:
        r["bbox"] = json.loads(r["bbox"]) if r["bbox"] else []
    return rows


@router.get("/{doc_id}/tables", summary="Extracted tables with preserved cell structure")
def tables(doc_id: str):
    _doc_or_404(doc_id)
    rows = metadb.q("SELECT * FROM doc_tables WHERE doc_id=? ORDER BY page", (doc_id,))
    for r in rows:
        r["cells"] = json.loads(r["cells"])
        r["bbox"] = json.loads(r["bbox"])
        r["warnings"] = json.loads(r["warnings"])
    return rows


@router.get("/{doc_id}/entities", summary="Entities mentioned in the document with mention counts")
def doc_entities(doc_id: str):
    _doc_or_404(doc_id)
    return metadb.q("""SELECT entity_id, count(*) AS mentions, count(DISTINCT page) AS pages, min(page) AS first_page,
                              group_concat(DISTINCT surface) AS surfaces
                       FROM mentions WHERE doc_id=? GROUP BY entity_id ORDER BY mentions DESC""", (doc_id,))


@router.get("/{doc_id}/file", summary="Original PDF (inline)")
def file(doc_id: str):
    d = _doc_or_404(doc_id)
    p = get_settings().pdf_dir / d["stored_name"]
    if not p.exists():
        raise HTTPException(410, "Original file is no longer stored")
    return FileResponse(p, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{d["id"]}.pdf"'})


@router.get("/{doc_id}/pages/{page}/image", summary="Render a page as PNG, highlighting a chunk's bounding boxes")
def page_image(doc_id: str, page: int, chunk_id: str = "", zoom: float = Query(1.6, ge=0.5, le=3.0)):
    d = _doc_or_404(doc_id)
    p = get_settings().pdf_dir / d["stored_name"]
    doc = pymupdf.open(p)
    if page < 1 or page > len(doc):
        raise HTTPException(404, "Page out of range")
    pg = doc[page - 1]
    highlighted = False
    if chunk_id:
        c = metadb.q1("SELECT bbox FROM chunks WHERE id=? AND doc_id=?", (chunk_id, doc_id))
        if c and c["bbox"]:
            for b in json.loads(c["bbox"]):
                if b[0] == page:
                    r = pymupdf.Rect(b[1] - 2, b[2] - 2, b[3] + 2, b[4] + 2)
                    pg.draw_rect(r, color=(0.95, 0.6, 0.0), fill=(1.0, 0.85, 0.2), fill_opacity=0.28, width=1.2, overlay=True)
                    highlighted = True
    pix = pg.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))
    data = pix.tobytes("png")
    doc.close()
    return Response(data, media_type="image/png", headers={"X-Highlighted": "1" if highlighted else "0", "Cache-Control": "max-age=300"})


@router.post("/{doc_id}/retry", summary="Retry a failed / interrupted ingestion from its last checkpoint")
def retry(doc_id: str):
    d = _doc_or_404(doc_id)
    if d["status"] == "processing":
        raise HTTPException(409, "Document is currently processing")
    jid = enqueue(doc_id)
    metadb.audit("document.retry", f"Retry queued for {d['filename']}", doc_id)
    return {"job_id": jid}


@router.post("/{doc_id}/reprocess", summary="Re-run extraction from scratch (discards checkpoints for this document only)")
def reprocess(doc_id: str):
    d = _doc_or_404(doc_id)
    if d["status"] == "processing":
        raise HTTPException(409, "Document is currently processing")
    import shutil
    shutil.rmtree(get_settings().artifact_dir / doc_id, ignore_errors=True)
    jid = enqueue(doc_id, reset_stage="registered")
    metadb.audit("document.reprocess", f"Full reprocess queued for {d['filename']}", doc_id)
    return {"job_id": jid}


@router.delete("/{doc_id}", summary="Delete a document, its stored file and all of its graph contributions")
def delete(doc_id: str):
    d = _doc_or_404(doc_id)
    if d["status"] == "processing":
        raise HTTPException(409, "Document is currently processing")
    pipeline.delete_document_everywhere(doc_id)
    return {"deleted": doc_id, "note": "Document-owned nodes, evidence, claims and relationships were removed; shared canonical "
                                      "entities remain if other documents still reference them."}


jobs_router = APIRouter(prefix="/api/jobs", tags=["documents"])


@jobs_router.get("", summary="Ingestion jobs and worker status")
def jobs(status: str = "", limit: int = 200):
    where = "WHERE j.status = ?" if status else ""
    rows = metadb.q(f"""SELECT j.*, d.filename FROM jobs j JOIN documents d ON d.id = j.doc_id {where}
                        ORDER BY j.updated_at DESC LIMIT ?""", ([status] if status else []) + [limit])
    return {"worker": get_worker().status(), "items": rows}


@jobs_router.post("/pause", summary="Pause / resume dispatching new ingestion jobs")
def pause(paused: bool = True):
    get_worker().paused = paused
    return get_worker().status()
