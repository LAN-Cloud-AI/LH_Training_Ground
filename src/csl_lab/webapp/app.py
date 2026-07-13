from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from csl_lab.paths import (
    ensure_product,
    ensure_scenario,
    list_products,
    list_scenario_metas,
    normalize_product_id,
    normalize_scenario_id,
)
from csl_lab.webapp.access_users import (
    AccessUsersError,
    add_access_email,
    list_access_emails,
    remove_access_email,
)
from csl_lab.webapp.config_store import load_config, public_config, save_config
from csl_lab.webapp.db import apply_human_correction, init_db, list_comments
from csl_lab.webapp.jobs import jobs
from csl_lab.webapp.services import (
    list_post_files,
    preview_posts_file,
    run_crawl_job,
    run_judge_and_ingest,
)

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="LeadsHunter Model Training Ground", version="0.1.0")


@app.on_event("startup")
def _startup() -> None:
    init_db()
    # hydrate env from saved config
    load_config()


class ConfigUpdate(BaseModel):
    tikhub_api_token: str | None = None
    tikhub_base_url: str | None = None
    tikhub_rpm: int | None = None
    deepseek_api_key: str | None = None
    deepseek_model: str | None = None
    deepseek_base_url: str | None = None
    cloudflare_api_token: str | None = None
    cf_access_team_domain: str | None = None


class AccessEmailRequest(BaseModel):
    email: str


class CrawlRequest(BaseModel):
    keyword: str
    max_pages: int = Field(default=10, ge=1, le=50)
    scenario_id: str = "new_car"
    product_id: str = "mona_l03"
    fetch_detail: bool = True


class JudgeRequest(BaseModel):
    posts_path: str
    scenario_id: str = "new_car"
    product_id: str = "mona_l03"
    crawl_run_id: str | None = None


class CorrectionRequest(BaseModel):
    human_correction: str
    correction_reason: str = ""


class ScenarioEnsureRequest(BaseModel):
    scenario_id: str
    display_name: str | None = None


class ProductEnsureRequest(BaseModel):
    product_id: str
    keyword: str | None = None
    brand: str | None = None
    series: str | None = None
    scenario_id: str = "new_car"


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "leadshunter-training-ground"}


@app.get("/api/config")
def get_config() -> dict[str, Any]:
    return public_config()


@app.put("/api/config")
def put_config(body: ConfigUpdate) -> dict[str, Any]:
    save_config(body.model_dump(exclude_unset=True))
    return public_config()


@app.get("/api/posts/files")
def posts_files() -> dict[str, Any]:
    return {"files": list_post_files()}


@app.get("/api/posts/preview")
def posts_preview(path: str, limit: int = 500) -> dict[str, Any]:
    try:
        return preview_posts_file(path, limit=limit)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/scenarios")
def scenarios() -> dict[str, Any]:
    return {"scenarios": list_scenario_metas()}


@app.post("/api/scenarios/ensure")
def scenarios_ensure(body: ScenarioEnsureRequest) -> dict[str, Any]:
    try:
        sid = ensure_scenario(
            body.scenario_id,
            display_name=body.display_name,
            create_if_missing=True,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {
        "scenario_id": sid,
        "normalized_from": normalize_scenario_id(body.scenario_id),
        "scenarios": list_scenario_metas(),
        "created_or_existing": sid,
    }


@app.get("/api/products")
def products(scenario_id: str = "new_car") -> dict[str, Any]:
    return {"scenario_id": scenario_id, "products": list_products(scenario_id)}


@app.post("/api/products/ensure")
def products_ensure(body: ProductEnsureRequest) -> dict[str, Any]:
    try:
        pid = ensure_product(
            body.scenario_id,
            body.product_id,
            keyword=body.keyword,
            brand=body.brand,
            series=body.series,
            create_if_missing=True,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {
        "scenario_id": body.scenario_id,
        "product_id": pid,
        "normalized_from": normalize_product_id(body.product_id),
        "products": list_products(body.scenario_id),
        "created_or_existing": pid,
    }


@app.post("/api/crawl")
def start_crawl(body: CrawlRequest) -> dict[str, Any]:
    job = jobs.create("crawl")

    def _run() -> dict[str, Any]:
        return run_crawl_job(
            keyword=body.keyword,
            max_pages=body.max_pages,
            scenario_id=body.scenario_id,
            product_id=body.product_id,
            fetch_detail=body.fetch_detail,
        )

    jobs.run_in_thread(job, _run)
    return {"job_id": job.job_id, "status": job.status}


@app.post("/api/judge")
def start_judge(body: JudgeRequest) -> dict[str, Any]:
    if not Path(body.posts_path).exists():
        raise HTTPException(400, f"posts file not found: {body.posts_path}")
    job = jobs.create("judge")

    def _run() -> dict[str, Any]:
        return run_judge_and_ingest(
            posts_path=body.posts_path,
            scenario_id=body.scenario_id,
            product_id=body.product_id,
            crawl_run_id=body.crawl_run_id,
        )

    jobs.run_in_thread(job, _run)
    return {"job_id": job.job_id, "status": job.status}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    return {
        "job_id": job.job_id,
        "kind": job.kind,
        "status": job.status,
        "message": job.message,
        "result": job.result,
        "error": job.error,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    }


@app.get("/api/comments")
def get_comments(
    limit: int = 200, offset: int = 0, scenario_id: str | None = None
) -> dict[str, Any]:
    rows = list_comments(limit=limit, offset=offset, scenario_id=scenario_id)
    return {"count": len(rows), "items": rows}


@app.post("/api/comments/{note_id}/correction")
def post_correction(note_id: str, body: CorrectionRequest) -> dict[str, Any]:
    try:
        row = apply_human_correction(
            note_id=note_id,
            human_correction=body.human_correction,
            correction_reason=body.correction_reason,
        )
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return row


@app.get("/api/access/users")
def get_access_users() -> dict[str, Any]:
    try:
        return list_access_emails()
    except AccessUsersError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/access/users")
def post_access_user(body: AccessEmailRequest) -> dict[str, Any]:
    try:
        return add_access_email(body.email)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except AccessUsersError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.delete("/api/access/users")
def delete_access_user(body: AccessEmailRequest) -> dict[str, Any]:
    try:
        return remove_access_email(body.email)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except AccessUsersError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
