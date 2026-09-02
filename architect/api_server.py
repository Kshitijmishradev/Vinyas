from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Response, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from architect.engine import AnalysisCancelled, analyze_repository
from architect.explanations import explain_finding
from architect.storage import AnalysisStore

ALLOWED_ROOT = Path(
    os.environ.get("VINYAS_ROOT", os.environ.get("ARCHITECT_ROOT", os.getcwd()))
).expanduser().resolve()
DATA_DIR = Path(
    os.environ.get(
        "VINYAS_DATA_DIR",
        os.environ.get("ARCHITECT_DATA_DIR", ALLOWED_ROOT / ".vinyas"),
    )
)
STORE = AnalysisStore(DATA_DIR / "analyses.sqlite3")
EXECUTOR = ThreadPoolExecutor(
    max_workers=max(
        1,
        int(os.environ.get("VINYAS_MAX_JOBS", os.environ.get("ARCHITECT_MAX_JOBS", "2"))),
    )
)


class CreateAnalysisRequest(BaseModel):
    path: str | None = None


class ExplanationRequest(BaseModel):
    finding_fingerprint: str


app = FastAPI(title="Vinyas API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type"],
)


def _safe_root(requested: str | None) -> Path:
    candidate = Path(requested).expanduser().resolve() if requested else ALLOWED_ROOT
    try:
        candidate.relative_to(ALLOWED_ROOT)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="path is outside the server repository root") from exc
    if not candidate.is_dir():
        raise HTTPException(status_code=400, detail="repository path does not exist")
    return candidate


def _run_analysis(analysis_id: str, root: Path) -> None:
    try:
        STORE.update(analysis_id, status="running", progress=1, message="Starting analysis")
        graph = analyze_repository(
            root,
            progress=lambda value, message: STORE.update(analysis_id, progress=value, message=message),
            cancelled=lambda: STORE.cancelled(analysis_id),
        )
        STORE.update(analysis_id, status="complete", progress=100, message="Analysis complete", result=graph.to_dict())
    except AnalysisCancelled:
        STORE.update(analysis_id, status="cancelled", message="Analysis cancelled")
    except Exception as exc:  # worker boundary: expose structured failure, not a dead job
        STORE.update(analysis_id, status="failed", error=str(exc), message="Analysis failed")


def _analysis(analysis_id: str, result: bool = False) -> dict[str, Any]:
    item = STORE.get(analysis_id, include_result=result)
    if not item:
        raise HTTPException(status_code=404, detail="analysis not found")
    return item


@app.get("/api/health")
@app.get("/api/v1/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "root": str(ALLOWED_ROOT), "version": "1.0.0"}


@app.post("/api/v1/analyses", status_code=status.HTTP_202_ACCEPTED)
def create_analysis(request: CreateAnalysisRequest) -> dict[str, Any]:
    root = _safe_root(request.path)
    item = STORE.create(str(root))
    EXECUTOR.submit(_run_analysis, item["id"], root)
    return item


@app.get("/api/v1/analyses/{analysis_id}")
def get_analysis(analysis_id: str) -> dict[str, Any]:
    item = _analysis(analysis_id, result=True)
    result = item.pop("result", None)
    if result:
        item["summary"] = result["summary"]
    return item


@app.get("/api/v1/analyses/{analysis_id}/findings")
def get_findings(analysis_id: str) -> dict[str, Any]:
    item = _analysis(analysis_id, result=True)
    if item["status"] != "complete":
        raise HTTPException(status_code=409, detail="analysis is not complete")
    return {"analysis_id": analysis_id, "findings": item["result"]["findings"]}


@app.get("/api/v1/analyses/{analysis_id}/graph")
def get_graph(analysis_id: str) -> dict[str, Any]:
    item = _analysis(analysis_id, result=True)
    if item["status"] != "complete":
        raise HTTPException(status_code=409, detail="analysis is not complete")
    result = item["result"]
    return {key: result[key] for key in ("schema_version", "root", "files", "edges", "cycles", "summary")} | {"analysis_id": analysis_id}


@app.post("/api/v1/analyses/{analysis_id}/explanations")
def create_explanation(analysis_id: str, request: ExplanationRequest) -> dict[str, Any]:
    item = _analysis(analysis_id, result=True)
    if item["status"] != "complete":
        raise HTTPException(status_code=409, detail="analysis is not complete")
    finding = next(
        (value for value in item["result"]["findings"] if value["fingerprint"] == request.finding_fingerprint),
        None,
    )
    if not finding:
        raise HTTPException(status_code=404, detail="finding not found")
    explanation, generated = explain_finding(finding)
    return {"explanation": explanation, "ai_generated": generated, "facts_source": "deterministic-analysis"}


@app.delete("/api/v1/analyses/{analysis_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_analysis(analysis_id: str) -> Response:
    item = _analysis(analysis_id)
    if item["status"] in {"queued", "running"}:
        STORE.cancel(analysis_id)
    else:
        STORE.delete(analysis_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
