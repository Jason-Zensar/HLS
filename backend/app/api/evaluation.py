"""Evaluation endpoints."""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException

from app.core import metadb

router = APIRouter(prefix="/api/evaluation", tags=["evaluation"])


@router.post("/run", summary="Run the reproducible evaluation suite against the current index")
def run():
    from app.evaluation.runner import run_evaluation
    return run_evaluation()


@router.get("/runs", summary="Evaluation history")
def runs(limit: int = 20):
    rows = metadb.q("SELECT id, ts, summary FROM eval_runs ORDER BY ts DESC LIMIT ?", (limit,))
    for r in rows:
        r["summary"] = json.loads(r["summary"])
    return rows


@router.get("/runs/{run_id}", summary="Evaluation run details")
def run_detail(run_id: str):
    r = metadb.q1("SELECT * FROM eval_runs WHERE id = ?", (run_id,))
    if not r:
        raise HTTPException(404, "Run not found")
    r["summary"] = json.loads(r["summary"])
    r["details"] = json.loads(r["details"])
    return r
