from io import BytesIO
import re
from CV.models import CV, Experience, Project

from pypdf import PdfReader


def extract_text(pdf_bytes: bytes) -> str:
    """Extract text from a text-based PDF and fail clearly for empty documents."""
    reader = PdfReader(BytesIO(pdf_bytes))
    text = "\n".join(page.extract_text() or "" for page in reader.pages).strip()
    if not text:
        raise ValueError("The PDF contains no extractable text.")
    return text


_SKILLS = (
    "python", "fastapi", "django", "javascript", "typescript", "react", "sql",
    "postgresql", "aws", "docker", "kubernetes", "machine learning", "java",
    "c++", "excel", "figma", "product management",
)
_CLASS_RULES = {
    "Software Engineering": ("python", "fastapi", "django", "javascript", "typescript", "react", "java", "c++"),
    "Data & AI": ("machine learning", "sql", "python"),
    "Cloud & DevOps": ("aws", "docker", "kubernetes"),
    "Product & Design": ("figma", "product management"),
}
_SECTION_ALIASES = {
    "experience": ("experience", "professional experience", "work experience", "employment", "work history"),
    "projects": ("projects", "selected projects", "personal projects", "portfolio"),
    "education": ("education", "academic background", "academic qualifications"),
    "skills": ("skills", "technical skills", "core skills", "competencies", "technologies"),
}


def parse_cv(text: str, filename: str) -> CV:
    lowered = text.lower()
    skills = _unique_skills(
        set(_parse_skill_section(text)) | {
            skill for skill in _SKILLS
            if re.search(rf"(?<!\w){re.escape(skill)}(?!\w)", lowered)
        }
    )
    classes = [
        name for name, keywords in _CLASS_RULES.items()
        if any(keyword in lowered for keyword in keywords)
    ]
    years = [
        float(match)
        for match in re.findall(r"(\d+(?:\.\d+)?)\+?\s+years?", lowered)
    ]
    experience_years = max(years, default=0)
    section = _section(text, _SECTION_ALIASES["experience"])
    experience = _parse_experience(section, skills)
    projects = _parse_projects(
        _section(text, _SECTION_ALIASES["projects"])
    )
    education = [
        line.strip("•- \t")
        for line in _section(text, _SECTION_ALIASES["education"]).splitlines()
        if line.strip()
    ]
    return CV(
        name=_cv_name(text),
        email=_first_match(text, r"[\w.+-]+@[\w-]+\.[\w.-]+"),
        phone=_first_match(text, r"(?:(?:\+\d{1,3}[\s.-]?)?(?:\(?\d{2,4}\)?[\s.-]?)?\d{3}[\s.-]?\d{3,4})"),
        summary=text,
        skills=skills,
        experience=experience,
        projects=projects,
        education=education,
        perceived_classes=classes,
        total_experience_years=experience_years,
        search_phrase=_fallback_search_phrase(experience, classes, skills),
        source_filename=filename,
    )


def _section(text: str, headings: tuple[str, ...]) -> str:
    lines = text.splitlines()
    start = next(
        (index for index, line in enumerate(lines) if _is_heading(line, headings)),
        None,
    )
    if start is None:
        return ""
    other_headings = tuple(
        heading for aliases in _SECTION_ALIASES.values() for heading in aliases
    ) + ("certifications", "summary", "profile")
    end = next(
        (
            index for index in range(start + 1, len(lines))
            if _is_heading(lines[index], other_headings)
        ),
        len(lines),
    )
    return "\n".join(lines[start + 1:end])


def _parse_skill_section(text: str) -> set[str]:
    section = _section(text, _SECTION_ALIASES["skills"])
    candidates = re.split(r"[,;|•\n]", section)
    return {
        candidate.strip()
        for candidate in candidates
        if 1 < len(candidate.strip()) < 80
        and not _is_heading(candidate, _SECTION_ALIASES["skills"])
    }


def _unique_skills(skills: set[str]) -> list[str]:
    unique: dict[str, str] = {}
    for skill in skills:
        clean = re.sub(r"\s+", " ", skill.strip())
        if clean:
            unique.setdefault(clean.casefold(), clean)
    return sorted(unique.values(), key=str.casefold)


def _is_heading(line: str, headings: tuple[str, ...]) -> bool:
    normalized = re.sub(r"[^a-z ]", " ", line.casefold())
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized in {
        re.sub(r"[^a-z ]", " ", heading.casefold()).strip()
        for heading in headings
    }


def _cv_name(text: str) -> str:
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    if first_line and not _looks_like_contact_or_heading(first_line):
        return first_line
    return _first_match(
        text,
        r"(?im)^\s*(?:name\s*:\s*)?([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z.'-]+){1,3})\s*$",
    )


def _looks_like_contact_or_heading(value: str) -> bool:
    lowered = value.casefold()
    return (
        "@" in value
        or bool(re.fullmatch(r"[\d\s+().-]+", value))
        or lowered in {"cv", "resume", "curriculum vitae"}
        or _is_heading(value, tuple(heading for aliases in _SECTION_ALIASES.values() for heading in aliases))
    )


def _parse_projects(text: str) -> list[Project]:
    projects: list[Project] = []
    for line in text.splitlines():
        clean = line.strip("•- \t")
        if not clean:
            continue
        name, separator, description = clean.partition(":")
        projects.append(
            Project(
                name=name.strip()[:100],
                description=(description.strip() if separator else clean)[:1000],
                technologies=sorted(
                    skill for skill in _SKILLS
                    if re.search(rf"(?<!\w){re.escape(skill)}(?!\w)", clean.casefold())
                ),
            )
        )
    return projects


def _first_match(text: str, pattern: str) -> str:
    match = re.search(pattern, text)
    return match.group(1 if match.lastindex else 0).strip() if match else ""


def _parse_experience(text: str, skills: list[str]) -> list[Experience]:
    entries: list[Experience] = []
    for line in text.splitlines():
        clean = line.strip()
        if not clean or len(clean) > 120:
            continue
        if re.search(r"\b(19|20)\d{2}\b", clean) and (" - " in clean or " to " in clean.lower()):
            title, _, company = clean.partition(" at ")
            entries.append(Experience(
                company=company.strip() or "Unspecified company",
                title=title.split("|")[0].strip(),
                description=clean,
                skills=skills,
            ))
    return entries


def _fallback_search_phrase(
    experience: list[Experience], classes: list[str], skills: list[str]
) -> str:
    focus = [role.title for role in experience[:2]] or classes[:2]
    return " ".join([*focus, *skills[:6]]).strip()
