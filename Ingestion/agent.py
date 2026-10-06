import json
import os

from openai import OpenAI
from openai import OpenAIError
from pydantic import ValidationError
from langsmith import traceable

from CV.models import CV

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "google/gemma-4-31b-it:free"


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
def enrich_cv_with_openrouter(text: str, filename: str, fallback: CV) -> CV:
    """Use an OpenRouter model to recover structured CV data missed by heuristics."""
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        return fallback

    client = OpenAI(base_url=OPENROUTER_BASE_URL, api_key=api_key)
    try:
        response = client.chat.completions.create(
            model=os.getenv("OPENROUTER_MODEL", DEFAULT_MODEL),
            messages=[
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
            ],
            response_format={"type": "json_object"},
            extra_body={"reasoning": {"enabled": True}},
        )
        content = response.choices[0].message.content
        if not content:
            return fallback
        data = json.loads(content)
        enriched = CV.model_validate({**data, "source_filename": filename, "summary": text})
    except (OpenAIError, json.JSONDecodeError, ValidationError, IndexError, TypeError):
        return fallback

    return _merge_fallback_values(enriched, fallback)


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
            "name": enriched.name or fallback.name,
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
def rank_jobs_with_openrouter(cv: CV, jobs: list[dict]) -> list[dict]:
    """Rank jobs as a batch using the complete CV, with a deterministic fallback."""
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key or not jobs:
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
    client = OpenAI(base_url=OPENROUTER_BASE_URL, api_key=api_key)
    try:
        response = client.chat.completions.create(
            model=os.getenv("OPENROUTER_MODEL", DEFAULT_MODEL),
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            extra_body={"reasoning": {"enabled": True}},
        )
        content = response.choices[0].message.content
        ranked_ids = json.loads(content or "{}").get("external_ids", [])
        by_id = {job["external_id"]: job for job in jobs}
        ranked = [by_id[job_id] for job_id in ranked_ids if job_id in by_id]
        ranked.extend(job for job in jobs if job["external_id"] not in ranked_ids)
        return ranked
    except (OpenAIError, json.JSONDecodeError, TypeError, AttributeError):
        return sorted(jobs, key=lambda job: len(job.get("matched_terms", [])), reverse=True)
