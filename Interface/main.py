from pathlib import Path

import httpx
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from CV.models import CV
from Database.repository import Repository
from Ingestion.agent import enrich_cv_with_openrouter
from Ingestion.pdf_parser import extract_text, parse_cv
from Search.service import API_SOURCES, PUBLIC_SOURCES, search_jobs, source_links

BASE_DIR = Path(__file__).resolve().parent.parent
repository = Repository(BASE_DIR / "job_finder.db")
templates = Jinja2Templates(directory=str(BASE_DIR / "Interface" / "templates"))
app = FastAPI(title="Job Finder")


@app.get("/", response_class=HTMLResponse)
async def home(request: Request) -> HTMLResponse:
    selected_source = request.query_params.get("source", "all")
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
        },
    )


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
    heuristic_cv = parse_cv(text, filename)
    cv = enrich_cv_with_openrouter(text, filename, heuristic_cv)
    repository.save_cv(cv)
    return RedirectResponse("/profile", status_code=303)


@app.post("/jobs/search")
async def search_and_save_jobs(source: list[str] | None = None) -> RedirectResponse:
    cv = repository.get_cv()
    if cv is None:
        raise HTTPException(status_code=400, detail="Upload a CV before searching.")
    selected_sources = [item for item in (source or []) if item != "all"]
    try:
        jobs = await search_jobs(cv, sources=selected_sources or None)
    except (httpx.HTTPError, ValueError) as error:
        raise HTTPException(status_code=502, detail="The job source is unavailable.") from error
    repository.save_jobs(jobs)
    selected = selected_sources[0] if len(selected_sources) == 1 else "all"
    return RedirectResponse(f"/?source={selected}", status_code=303)
