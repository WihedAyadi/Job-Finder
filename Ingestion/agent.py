import json
import logging
import os
import re
from datetime import date
from pathlib import Path

import ollama
from pydantic import ValidationError
from langsmith import traceable

from CV.models import CV

DEFAULT_MODEL = "granite3.2:2b"
logger = logging.getLogger(__name__)


def load_project_environment() -> None:
    """Load local KEY=value settings without overwriting shell environment values."""
    project_root = Path(__file__).resolve().parent.parent
    for path in (project_root / ".env", project_root / ".gitignore" / "env"):
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            value = value.strip().strip("\"'")
            if key.strip() and value:
                os.environ.setdefault(key.strip(), value)


load_project_environment()


def _ollama_client() -> ollama.Client:
    return ollama.Client(host=os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434"))


@traceable(name="ollama-model-call", run_type="llm")
def _request_completion(messages: list[dict]) -> object:
    return _ollama_client().chat(
        model=os.getenv("OLLAMA_MODEL", DEFAULT_MODEL),
        messages=messages,
        format="json",
    )


@traceable(
    name="cv-enrichment",
    run_type="chain",
    process_inputs=lambda args: {
        "filename": args.get("filename", ""),
        "text_length": len(args.get("text", "")),
        "fallback_skill_count": len(args.get("fallback").skills)
        if args.get("fallback")
        else 0,
    },
    process_outputs=lambda result: {
        "skill_count": len(result.skills),
        "experience_count": len(result.experience),
        "project_count": len(result.projects),
        "profile_class_count": len(result.perceived_classes),
    },
)
def enrich_cv_with_ollama(text: str, filename: str, fallback: CV) -> CV:
    """Use the local Ollama model to recover structured CV data."""
    try:
        response = _request_completion([
                {
                    "role": "system",
                    "content": (
                        "You extract complete, factual data from CVs. The first non-empty line "
                        "is the candidate's name unless it is an email, phone number, or generic "
                        "document heading. Use that exact name; do not infer a different name. "
                        "Treat sections headed "
                        "Education, Studies, Academic Background, or Qualifications as education "
                        "only; never create work experience entries from those sections. Treat "
                        "Experience, Employment, or Work History as work experience only. Return "
                        "certifications and awards only in their dedicated fields. Keep "
                        "achievements separate from responsibilities. "
                        "only valid JSON "
                        "matching the supplied schema. Never invent missing values. Preserve "
                        "every distinct skill, project, role, date, technology, education item, "
                        "and contact detail found in the CV."
                    ),
                },
                {
                    "role": "user",
                    "content": f"{_schema_prompt()}\n\nCV TEXT:\n{text}",
                },
            ])
        content = _message_content(response)
        data = _normalise_agent_data(_parse_json_response(content))
        enriched = CV.model_validate({**data, "source_filename": filename, "summary": text})
    except (
        ollama.ResponseError,
        ConnectionError,
        json.JSONDecodeError,
        ValidationError,
        IndexError,
        TypeError,
    ):
        return fallback

    return _merge_fallback_values(enriched, fallback)


def parse_cv_with_agent(text: str, filename: str) -> CV:
    """Parse a resume exclusively through the configured local Ollama agent."""
    try:
        response = _request_completion([
                {
                    "role": "system",
                    "content": (
                        "You are the sole resume parser. Extract the complete resume into "
                        "the JSON schema below. Use the first non-empty line as the exact name "
                        "unless it is a document heading or contact value. Never infer or "
                        "rewrite the name. Keep education, certifications, projects, and "
                        "achievements separate from work experience. Preserve every skill."
                    ),
                },
                {"role": "user", "content": f"{_schema_prompt()}\n\nRESUME:\n{text}"                },
            ])
        content = _message_content(response)
        if not content:
            raise RuntimeError("The resume agent returned an empty response.")
        data = _normalise_agent_data(_parse_json_response(content))
        return CV.model_validate(
            {
                **data,
                "summary": text,
                "source_filename": filename,
                "parser": "ollama",
            }
        )
    except (
        ollama.ResponseError,
        ConnectionError,
        json.JSONDecodeError,
        ValidationError,
        IndexError,
        TypeError,
    ) as error:
        logger.exception("Resume agent request failed")
        raise RuntimeError(
            f"The Ollama resume agent could not produce valid structured data: {error}"
        ) from error


def _parse_json_response(content: str) -> dict:
    """Decode JSON returned by a model, including fenced JSON responses."""
    cleaned = content.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].strip().lower() in {"```json", "```"}:
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    value = json.loads(cleaned)
    if not isinstance(value, dict):
        raise TypeError("The resume agent returned a JSON value instead of an object.")
    return value


def _message_content(response: object) -> str:
    """Read Ollama content and reject missing/non-text model output."""
    try:
        message = getattr(response, "message", None)
        content = getattr(message, "content", None)
        if content is None and isinstance(response, dict):
            content = response["message"]["content"]
    except (AttributeError, IndexError, KeyError, TypeError) as error:
        raise TypeError("The resume agent returned no assistant message.") from error
    if not isinstance(content, str) or not content.strip():
        raise TypeError("The resume agent returned empty or non-text content.")
    return content


def _normalise_agent_data(data: dict) -> dict:
    """Make common model shorthand values compatible with the CV schema."""
    normalised = dict(data)
    for key in ("name", "email", "phone", "location", "search_phrase"):
        if normalised.get(key) is None:
            normalised[key] = ""
    for item in normalised.get("experience", []) or []:
        if isinstance(item, dict):
            for key in ("company", "title", "description"):
                if item.get(key) is None:
                    item[key] = ""
            for key in ("start_date", "end_date"):
                item[key] = _normalise_date(item.get(key))
    for key in ("education", "certifications", "achievements"):
        values = normalised.get(key, []) or []
        normalised[key] = [
            _stringify_agent_value(value) for value in values
        ]
    for item in normalised.get("projects", []) or []:
        if isinstance(item, dict) and not item.get("url"):
            item["url"] = None
    return normalised


def _normalise_date(value: object) -> str | None:
    """Convert common CV month/year values to the model's ISO date format."""
    if value is None or isinstance(value, date):
        return value.isoformat() if isinstance(value, date) else None
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if cleaned.lower() in {"", "present", "current", "ongoing", "now"}:
        return None
    for pattern, replacement in (
        (r"^(\d{4})$", r"\1-01-01"),
        (r"^(\d{4})-(\d{2})$", r"\1-\2-01"),
    ):
        if re.fullmatch(pattern, cleaned):
            return re.sub(pattern, replacement, cleaned)
    month = (
        "jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
        "jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|"
        "dec(?:ember)?"
    )
    match = re.fullmatch(rf"({month})\.?\s+(\d{{4}})", cleaned, re.IGNORECASE)
    if match:
        month_number = {
            name: number
            for number, name in enumerate(
                (
                    "jan", "feb", "mar", "apr", "may", "jun",
                    "jul", "aug", "sep", "oct", "nov", "dec",
                ),
                start=1,
            )
        }
        normalized_month = match.group(1).casefold()[:3]
        return f"{match.group(2)}-{month_number[normalized_month]:02d}-01"
    return cleaned


def _stringify_agent_value(value: object) -> str:
    """Preserve structured model fields while matching the CV string schema."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return "; ".join(
            f"{key}: {item}" for key, item in value.items() if item not in (None, "")
        )
    return str(value)


def _schema_prompt() -> str:
    return """Return an object with exactly these fields:
{
  "name": "string",
  "email": "string",
  "phone": "string",
  "location": "string",
  "skills": ["all skills as short strings"],
  "experience": [{
    "company": "string",
    "title": "string",
    "start_date": "YYYY-MM-DD or null",
    "end_date": "YYYY-MM-DD or null",
    "description": "full responsibility and achievement text",
    "skills": ["skills used in this role"]
  }],
  "projects": [{
    "name": "string",
    "description": "full project details",
    "url": "URL or null",
    "technologies": ["technologies used"]
  }],
  "education": ["degree, institution, and date details"],
  "certifications": ["certification, issuer, and date details"],
  "achievements": ["measurable accomplishments or awards"],
  "perceived_classes": ["professional categories"],
  "total_experience_years": 0,
  "search_phrase": "one natural-language job search phrase, 8 to 18 words"
}
The search_phrase must describe the candidate's target roles, seniority, strongest skills,
and relevant domain. Write it as a natural search query, not a comma-separated dump of fields.
Use an empty string, empty list, null, or 0 only when the CV does not provide the value."""


def _merge_fallback_values(enriched: CV, fallback: CV) -> CV:
    """Retain heuristic evidence when a model omits a value it did not understand."""
    return enriched.model_copy(
        update={
            "skills": _merge_skills(enriched.skills, fallback.skills),
            "experience": enriched.experience or fallback.experience,
            "projects": enriched.projects or fallback.projects,
            "education": enriched.education or fallback.education,
            "certifications": enriched.certifications or fallback.certifications,
            "achievements": enriched.achievements or fallback.achievements,
            "name": fallback.name or enriched.name,
            "email": enriched.email or fallback.email,
            "phone": enriched.phone or fallback.phone,
            "location": enriched.location or fallback.location,
            "search_phrase": enriched.search_phrase or fallback.search_phrase,
            "perceived_classes": sorted(
                set(enriched.perceived_classes) | set(fallback.perceived_classes)
            ),
            "total_experience_years": max(
                enriched.total_experience_years, fallback.total_experience_years
            ),
            "source_filename": fallback.source_filename,
            "summary": fallback.summary,
        }
    )


def _merge_skills(*skill_lists: list[str]) -> list[str]:
    unique: dict[str, str] = {}
    for skills in skill_lists:
        for skill in skills:
            clean = " ".join(skill.split())
            if clean:
                unique.setdefault(clean.casefold(), clean)
    return sorted(unique.values(), key=str.casefold)


@traceable(
    name="job-ranking",
    run_type="chain",
    process_inputs=lambda args: {
        "job_count": len(args.get("jobs", [])),
        "skill_count": len(args.get("cv").skills) if args.get("cv") else 0,
        "experience_years": args.get("cv").total_experience_years
        if args.get("cv")
        else 0,
    },
    process_outputs=lambda result: {
        "ranked_job_count": len(result),
        "top_job_id": result[0].get("external_id") if result else None,
    },
)
def rank_jobs_with_ollama(cv: CV, jobs: list[dict]) -> list[dict]:
    """Rank jobs as a batch using the complete CV, with a deterministic fallback."""
    if not jobs:
        return sorted(jobs, key=lambda job: len(job.get("matched_terms", [])), reverse=True)

    compact_jobs = [
        {
            "external_id": job["external_id"],
            "title": job["title"],
            "company": job["company"],
            "description": job["description"][:3000],
        }
        for job in jobs
    ]
    prompt = (
        "Rank these jobs for the candidate. Exclude jobs that are clearly unrelated "
        "to their skills or experience. Return only JSON in this format: "
        '{"external_ids":["id in best-first order"]}. Do not invent IDs.\\n'
        f"CANDIDATE SEARCH PHRASE:\\n{cv.generated_search_phrase()}\\n"
        f"CANDIDATE CV:\\n{cv.model_dump_json()}\\nJOBS:\\n{json.dumps(compact_jobs)}"
    )
    try:
        response = _request_completion([{"role": "user", "content": prompt}])
        ranked_ids = _parse_json_response(_message_content(response)).get(
            "external_ids", []
        )
        by_id = {job["external_id"]: job for job in jobs}
        ranked = [by_id[job_id] for job_id in ranked_ids if job_id in by_id]
        ranked.extend(job for job in jobs if job["external_id"] not in ranked_ids)
        return ranked
    except (ollama.ResponseError, ConnectionError, json.JSONDecodeError, TypeError, AttributeError):
        return sorted(jobs, key=lambda job: len(job.get("matched_terms", [])), reverse=True)
