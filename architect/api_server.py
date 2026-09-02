from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import tempfile
import time
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from architect import __version__
from architect.engine import AnalysisCancelled, analyze_repository
from architect.explanations import explain_finding
from architect.remote_sources import (
    InvalidRepositoryURL,
    RemoteCancelled,
    RemoteLimits,
    RemoteSourceError,
    ScanTimeout,
    download_github_snapshot,
    parse_github_url,
)
from architect.storage import AnalysisStore, expiry_after, is_expired

LOGGER = logging.getLogger(__name__)
ALLOWED_ROOT = Path(
    os.environ.get("VINYAS_ROOT", os.environ.get("ARCHITECT_ROOT", os.getcwd()))
).expanduser().resolve()
DATA_DIR = Path(
    os.environ.get(
        "VINYAS_DATA_DIR",
        os.environ.get("ARCHITECT_DATA_DIR", ALLOWED_ROOT / ".vinyas"),
    )
).expanduser().resolve()
STORE = AnalysisStore(DATA_DIR / "analyses.sqlite3")
MAX_WORKERS = max(
    1,
    int(os.environ.get("VINYAS_MAX_JOBS", os.environ.get("ARCHITECT_MAX_JOBS", "2"))),
)
MAX_ACTIVE = max(1, int(os.environ.get("VINYAS_MAX_ACTIVE", "2")))
RATE_LIMIT = max(1, int(os.environ.get("VINYAS_RATE_LIMIT_PER_HOUR", "3")))
REMOTE_ENABLED = os.environ.get("VINYAS_REMOTE_ENABLED", "false").lower() in {
    "1",
    "true",
    "yes",
}
TRUST_PROXY = os.environ.get("VINYAS_TRUST_PROXY", "false").lower() in {"1", "true", "yes"}
CLIENT_SALT = os.urandom(32)
REMOTE_LIMITS = RemoteLimits(
    max_download_bytes=int(os.environ.get("VINYAS_MAX_DOWNLOAD_BYTES", 50 * 1024 * 1024)),
    max_archive_entries=int(os.environ.get("VINYAS_MAX_ARCHIVE_ENTRIES", "10000")),
    max_source_files=int(os.environ.get("VINYAS_MAX_SOURCE_FILES", "750")),
    max_source_bytes=int(os.environ.get("VINYAS_MAX_SOURCE_BYTES", 25 * 1024 * 1024)),
    max_file_bytes=int(os.environ.get("VINYAS_MAX_FILE_BYTES", 1024 * 1024)),
    timeout_seconds=int(os.environ.get("VINYAS_SCAN_TIMEOUT_SECONDS", "90")),
)
EXECUTOR = ThreadPoolExecutor(max_workers=MAX_WORKERS)


class CreateAnalysisRequest(BaseModel):
    path: str | None = None
    repository_url: str | None = None


class ExplanationRequest(BaseModel):
    finding_fingerprint: str


async def _janitor() -> None:
    while True:
        await asyncio.sleep(300)
        STORE.delete_expired()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    STORE.mark_interrupted(expiry_after(15))
    STORE.delete_expired()
    cleanup = asyncio.create_task(_janitor())
    try:
        yield
    finally:
        cleanup.cancel()
        try:
            await cleanup
        except asyncio.CancelledError:
            pass


app = FastAPI(title="Vinyas API", version=__version__, lifespan=lifespan)
CORS_ORIGINS = [
    origin.strip()
    for origin in os.environ.get(
        "VINYAS_CORS_ORIGINS",
        "http://127.0.0.1:5173,http://localhost:5173",
    ).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type"],
)


def _safe_root(requested: str | None) -> Path:
    candidate = Path(requested).expanduser().resolve() if requested else ALLOWED_ROOT
    try:
        candidate.relative_to(ALLOWED_ROOT)
    except ValueError as exc:
        raise HTTPException(
            status_code=403, detail="path is outside the server repository root"
        ) from exc
    if not candidate.is_dir():
        raise HTTPException(status_code=400, detail="repository path does not exist")
    return candidate


def _run_local_analysis(analysis_id: str, root: Path) -> None:
    try:
        STORE.update(analysis_id, status="running", progress=1, message="Starting analysis")
        graph = analyze_repository(
            root,
            progress=lambda value, message: STORE.update(
                analysis_id, progress=value, message=message
            ),
            cancelled=lambda: STORE.cancelled(analysis_id),
        )
        STORE.update(
            analysis_id,
            status="complete",
            progress=100,
            message="Analysis complete",
            result=graph.to_dict(),
        )
    except AnalysisCancelled:
        STORE.update(
            analysis_id,
            status="cancelled",
            message="Analysis cancelled",
            error_code="cancelled",
            expires_at=expiry_after(15),
        )
    except Exception as exc:  # worker boundary
        LOGGER.exception("Local analysis failed")
        STORE.update(
            analysis_id,
            status="failed",
            error=str(exc),
            error_code="analysis_failed",
            message="Analysis failed",
            expires_at=expiry_after(15),
        )


def _run_remote_analysis(analysis_id: str, repository_url: str) -> None:
    repository = parse_github_url(repository_url)
    deadline = time.monotonic() + REMOTE_LIMITS.timeout_seconds

    def stopped() -> bool:
        if time.monotonic() >= deadline:
            raise ScanTimeout("Repository analysis exceeded the 90-second limit.")
        return STORE.cancelled(analysis_id)

    try:
        STORE.update(
            analysis_id,
            status="running",
            progress=2,
            message="Validating GitHub repository",
        )
        jobs_dir = DATA_DIR / "jobs"
        jobs_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=f"{analysis_id}-", dir=jobs_dir) as directory:
            snapshot = download_github_snapshot(
                repository,
                Path(directory),
                REMOTE_LIMITS,
                progress=lambda value, message: STORE.update(
                    analysis_id, progress=value, message=message
                ),
                cancelled=stopped,
                deadline=deadline,
            )
            source = repository.source(snapshot.commit_sha)
            STORE.update(analysis_id, source=source)

            def analysis_progress(value: int, message: str) -> None:
                STORE.update(
                    analysis_id,
                    progress=40 + int(value * 0.58),
                    message=message,
                )

            graph = analyze_repository(
                snapshot.root,
                progress=analysis_progress,
                cancelled=stopped,
            )
            payload = graph.to_dict()
            payload["root"] = repository.url
            payload["source"] = source
        STORE.update(
            analysis_id,
            status="complete",
            progress=100,
            message="Analysis complete",
            result=payload,
            expires_at=expiry_after(60),
        )
    except (RemoteCancelled, AnalysisCancelled):
        STORE.update(
            analysis_id,
            status="cancelled",
            message="Analysis cancelled",
            error_code="cancelled",
            expires_at=expiry_after(15),
        )
    except RemoteSourceError as exc:
        STORE.update(
            analysis_id,
            status="failed",
            message="Analysis failed",
            error=str(exc),
            error_code=exc.code,
            expires_at=expiry_after(15),
        )
    except Exception:
        LOGGER.exception("Remote analysis failed")
        STORE.update(
            analysis_id,
            status="failed",
            message="Analysis failed",
            error="The repository could not be analyzed.",
            error_code="analysis_failed",
            expires_at=expiry_after(15),
        )


def _analysis(analysis_id: str, result: bool = False) -> dict[str, Any]:
    item = STORE.get(analysis_id, include_result=result)
    if not item:
        raise HTTPException(status_code=404, detail="analysis not found")
    if is_expired(item):
        STORE.delete(analysis_id)
        raise HTTPException(status_code=410, detail="analysis has expired")
    return item


def _client_hash(request: Request) -> str:
    address = request.client.host if request.client else "unknown"
    if TRUST_PROXY:
        forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
        if forwarded:
            address = forwarded
    return hashlib.sha256(CLIENT_SALT + address.encode("utf-8")).hexdigest()


@app.get("/api/health")
@app.get("/api/v1/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "root": str(ALLOWED_ROOT),
        "version": __version__,
        "capabilities": {"local": True, "github_public": REMOTE_ENABLED},
    }


@app.post("/api/v1/analyses", status_code=status.HTTP_202_ACCEPTED)
def create_analysis(payload: CreateAnalysisRequest, request: Request) -> dict[str, Any]:
    if payload.path is not None and payload.repository_url is not None:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_source", "message": "Choose a path or repository URL."},
        )
    if payload.repository_url is not None:
        if not REMOTE_ENABLED:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "remote_analysis_disabled",
                    "message": "Public repository analysis is not enabled on this server.",
                },
            )
        try:
            repository = parse_github_url(payload.repository_url)
        except InvalidRepositoryURL as exc:
            raise HTTPException(
                status_code=400,
                detail={"code": exc.code, "message": str(exc)},
            ) from exc
        item, rejection = STORE.reserve_remote(
            repository.url,
            repository.source(),
            _client_hash(request),
            max_per_hour=RATE_LIMIT,
            max_active=MAX_ACTIVE,
        )
        if rejection:
            messages = {
                "rate_limit_exceeded": "Three scans per hour are allowed. Try again later.",
                "client_job_active": "You already have an analysis in progress.",
                "service_capacity_reached": "The analyzer is currently at capacity. Try again shortly.",
            }
            retry = "3600" if rejection == "rate_limit_exceeded" else "15"
            raise HTTPException(
                status_code=429,
                detail={"code": rejection, "message": messages[rejection]},
                headers={"Retry-After": retry},
            )
        assert item is not None
        EXECUTOR.submit(_run_remote_analysis, item["id"], repository.url)
        return item

    root = _safe_root(payload.path)
    source = {"kind": "local", "path": str(root)}
    item = STORE.create(str(root), source=source)
    EXECUTOR.submit(_run_local_analysis, item["id"], root)
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
    keys = ("schema_version", "root", "files", "edges", "cycles", "summary")
    response = {key: result[key] for key in keys} | {"analysis_id": analysis_id}
    if "source" in result:
        response["source"] = result["source"]
    return response


@app.post("/api/v1/analyses/{analysis_id}/explanations")
def create_explanation(analysis_id: str, request: ExplanationRequest) -> dict[str, Any]:
    item = _analysis(analysis_id, result=True)
    if item["status"] != "complete":
        raise HTTPException(status_code=409, detail="analysis is not complete")
    finding = next(
        (
            value
            for value in item["result"]["findings"]
            if value["fingerprint"] == request.finding_fingerprint
        ),
        None,
    )
    if not finding:
        raise HTTPException(status_code=404, detail="finding not found")
    explanation, generated = explain_finding(finding)
    return {
        "explanation": explanation,
        "ai_generated": generated,
        "facts_source": "deterministic-analysis",
    }


@app.delete("/api/v1/analyses/{analysis_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_analysis(analysis_id: str) -> Response:
    item = _analysis(analysis_id)
    if item["status"] in {"queued", "running"}:
        STORE.cancel(analysis_id)
    else:
        STORE.delete(analysis_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
