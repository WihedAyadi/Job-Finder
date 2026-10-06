from pathlib import Path
import os
import hashlib
from datetime import datetime

import httpx
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from CV.models import CV
from Database.repository import Repository
from Ingestion.agent import parse_cv_with_agent
from Ingestion.pdf_parser import extract_text
from Search.service import API_SOURCES, PUBLIC_SOURCES, search_jobs, source_links

BASE_DIR = Path(__file__).resolve().parent.parent
repository = Repository(os.getenv("JOB_FINDER_DB", str(BASE_DIR / "job_finder.db")))
templates = Jinja2Templates(directory=str(BASE_DIR / "Interface" / "templates"))
app = FastAPI(title="Job Finder")


@app.get("/", response_class=HTMLResponse)
async def home(request: Request) -> HTMLResponse:
    selected_source = request.query_params.get("source", "all")
    settings_saved = request.query_params.get("settings_saved") == "1"
    search_error = request.query_params.get("search_error") == "1"
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "cv": repository.get_cv(),
            "jobs": [
                job for job in repository.list_jobs()
                if selected_source == "all" or job["source"] == selected_source
            ],
            "source_links": source_links(repository.get_cv()) if repository.get_cv() else {},
            "api_sources": list(API_SOURCES),
            "web_sources": list(PUBLIC_SOURCES),
            "selected_source": selected_source,
            "ollama_configured": True,
            "langsmith_configured": bool(os.getenv("LANGSMITH_API_KEY")),
            "settings_saved": settings_saved,
            "search_error": search_error,
            "greeting": _greeting(),
        },
    )


def _greeting() -> str:
    hour = datetime.now().hour
    if hour < 12:
        return "Good morning"
    if hour < 18:
        return "Good afternoon"
    return "Good evening"


@app.post("/settings")
async def save_settings(
    langsmith_api_key: str = Form(""),
) -> RedirectResponse:
    if langsmith_api_key.strip():
        os.environ["LANGSMITH_API_KEY"] = langsmith_api_key.strip()
        os.environ["LANGSMITH_TRACING"] = "true"
    return RedirectResponse("/?settings_saved=1", status_code=303)


@app.get("/profile", response_class=HTMLResponse)
async def profile(request: Request) -> HTMLResponse:
    cv = repository.get_cv()
    if cv is None:
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(
        request=request, name="profile.html", context={"cv": cv}
    )


@app.post("/cv")
async def upload_cv(file: UploadFile = File(...)) -> RedirectResponse:
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=415, detail="Upload a PDF CV.")
    contents = await file.read()
    try:
        text = extract_text(contents)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    filename = file.filename or "cv.pdf"
    document_hash = hashlib.sha256(text.strip().encode("utf-8")).hexdigest()
    existing_cv = repository.get_cv()
    previous_hash = existing_cv.document_hash if existing_cv else ""
    if existing_cv and not previous_hash and existing_cv.summary:
        previous_hash = hashlib.sha256(existing_cv.summary.strip().encode("utf-8")).hexdigest()
    if (
        existing_cv
        and previous_hash == document_hash
        and existing_cv.parser == "ollama"
    ):
        return RedirectResponse("/profile", status_code=303)
    try:
        cv = parse_cv_with_agent(text, filename)
    except RuntimeError as error:
        raise HTTPException(
            status_code=502,
            detail=(
                "The CV agent could not parse this document. "
                "Check that Ollama is running and that the granite3.2:2b model is installed. "
                f"Reason: {error}"
            ),
        ) from error
    repository.save_cv(cv.model_copy(update={"document_hash": document_hash}))
    return RedirectResponse("/profile", status_code=303)


@app.post("/jobs/search")
async def search_and_save_jobs(source: list[str] | None = None) -> RedirectResponse:
    cv = repository.get_cv()
    if cv is None:
        raise HTTPException(status_code=400, detail="Upload a CV before searching.")
    selected_sources = [item for item in (source or []) if item != "all"]
    try:
        jobs = await search_jobs(cv, sources=selected_sources or None)
    except (httpx.HTTPError, ValueError):
        # Keep the last successful results visible when a provider is temporarily down.
        return RedirectResponse("/?search_error=1", status_code=303)
    repository.replace_jobs(jobs, selected_sources or list(API_SOURCES))
    selected = selected_sources[0] if len(selected_sources) == 1 else "all"
    return RedirectResponse(f"/?source={selected}", status_code=303)
