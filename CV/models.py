from datetime import date

from pydantic import BaseModel, Field, HttpUrl


class Experience(BaseModel):
    company: str
    title: str
    start_date: date | None = None
    end_date: date | None = None
    description: str = ""
    skills: list[str] = Field(default_factory=list)


class Project(BaseModel):
    name: str
    description: str = ""
    url: HttpUrl | None = None
    technologies: list[str] = Field(default_factory=list)


class CV(BaseModel):
    name: str = ""
    email: str = ""
    phone: str = ""
    summary: str = ""
    location: str = ""
    skills: list[str] = Field(default_factory=list)
    experience: list[Experience] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)
    education: list[str] = Field(default_factory=list)
    perceived_classes: list[str] = Field(default_factory=list)
    total_experience_years: float = 0
    search_phrase: str = ""
    source_filename: str | None = None

    def searchable_terms(self) -> set[str]:
        terms = set(self.skills)
        for project in self.projects:
            terms.update(project.technologies)
        for project in self.projects:
            terms.add(project.name)
        for role in self.experience:
            terms.add(role.title)
            terms.update(role.skills)
        return {term.strip().lower() for term in terms if term.strip()}

    def experience_limit_years(self) -> float:
        return self.total_experience_years + 3

    def generated_search_phrase(self) -> str:
        if self.search_phrase.strip():
            return self.search_phrase.strip()
        roles = [role.title for role in self.experience[:2]]
        focus = roles or self.perceived_classes[:2]
        skills = self.skills[:6]
        return " ".join([*focus, *skills]).strip()
