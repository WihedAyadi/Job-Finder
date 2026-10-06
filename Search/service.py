import asyncio
import re
from typing import Any
from urllib.parse import quote_plus

import httpx

from CV.models import CV
from Ingestion.agent import rank_jobs_with_openrouter

ARBEITNOW_API = "https://www.arbeitnow.com/api/job-board-api"
REMOTIVE_API = "https://remotive.com/api/remote-jobs"
JOBICY_API = "https://jobicy.com/api/v2/remote-jobs?count=50"
PUBLIC_SOURCES = {
    "LinkedIn": "https://www.linkedin.com/jobs/search/?keywords={query}",
    "Indeed": "https://www.indeed.com/jobs?q={query}",
    "Glassdoor": "https://www.glassdoor.com/Job/jobs.htm?sc.keyword={query}",
    "APEC": "https://www.apec.fr/candidat/recherche-emploi.html/emploi?motsCles={query}",
}
API_SOURCES = {
    "Arbeitnow": ARBEITNOW_API,
    "Remotive": REMOTIVE_API,
    "Jobicy": JOBICY_API,
}


def _job_from_api(item: dict[str, Any], cv: CV, source: str) -> dict[str, Any]:
    description = item.get("description", "")
    searchable = " ".join(
        [item.get("title", ""), item.get("company_name", item.get("companyName", "")), description]
    ).lower()
    matched_terms = sorted(term for term in cv.searchable_terms() if term in searchable)
    required = _required_years(searchable)
    if required is not None and required > cv.experience_limit_years():
        return {}
    return {
        "external_id": f"{source}:{item.get('slug') or item.get('id') or item.get('url')}",
        "title": item.get("title", "Untitled role"),
        "company": item.get("company_name", item.get("companyName", "Unknown company")),
        "location": ", ".join(item.get("tags", [])) or item.get("jobGeo", item.get("location", "Remote")),
        "url": item.get("url", item.get("jobUrl", "")),
        "description": description,
        "source": source,
        "matched_terms": matched_terms,
        "details": {
            "employment_type": (
                item.get("job_types", ["Not specified"])[0]
                if isinstance(item.get("job_types"), list)
                else item.get("job_types", "Not specified")
            ),
            "remote": bool(item.get("remote", False)),
            "posted_at": item.get("created_at", "Not specified"),
            "experience_required_years": required,
            "source_url": item.get("url", ""),
        },
    }


async def search_jobs(
    cv: CV, sources: list[str] | None = None, limit: int = 25
) -> list[dict[str, Any]]:
    selected_sources = sources or list(API_SOURCES)
    selected_sources = [source for source in selected_sources if source in API_SOURCES]
    if not selected_sources:
        raise ValueError("Select at least one supported job source.")
    async with httpx.AsyncClient(timeout=15) as client:
        responses = await asyncio.gather(
            *(client.get(API_SOURCES[source]) for source in selected_sources),
            return_exceptions=True,
        )
    jobs: list[dict[str, Any]] = []
    for response, source in zip(responses, selected_sources):
        if isinstance(response, Exception) or response.status_code >= 400:
            continue
        payload = response.json()
        items = payload.get("data", payload.get("jobs", []))
        jobs.extend(
            job for item in items if (job := _job_from_api(item, cv, source))
        )
    if not jobs and all(isinstance(response, Exception) for response in responses):
        raise httpx.HTTPError("All job sources are unavailable.")
    jobs = list({job["external_id"]: job for job in jobs}.values())
    return rank_jobs_with_openrouter(cv, jobs)[:limit]


def source_links(cv: CV) -> dict[str, str]:
    query = quote_plus(cv.generated_search_phrase())
    return {name: url.format(query=query) for name, url in PUBLIC_SOURCES.items()}


def _required_years(text: str) -> float | None:
    matches = re.findall(r"(\d+(?:\.\d+)?)\+?\s*(?:years?|yrs?)\s+(?:of\s+)?experience", text)
    return max((float(value) for value in matches), default=None)
