from Ingestion.pdf_parser import parse_cv


def test_fallback_parser_extracts_cv_sections() -> None:
    cv = parse_cv(
        """
        Ada Lovelace
        ada@example.com
        SKILLS
        Python; Airflow; Data Modeling
        EXPERIENCE
        Data Engineer at Acme | 2021 - 2024
        PROJECTS
        Revenue Pipeline: Built an Airflow and Python pipeline.
        EDUCATION
        BSc Computer Science, Example University
        """,
        "ada.pdf",
    )

    assert cv.name == "Ada Lovelace"
    assert cv.email == "ada@example.com"
    assert {"python", "airflow", "data modeling"} <= {skill.casefold() for skill in cv.skills}
    assert cv.projects[0].name == "Revenue Pipeline"
    assert cv.education == ["BSc Computer Science, Example University"]
    assert cv.generated_search_phrase()


def test_first_line_is_name_and_studies_are_not_experience() -> None:
    cv = parse_cv(
        """
        Jordan Smith
        jordan@example.com
        Technical Skills
        Python, FastAPI, PostgreSQL, Redis, Terraform, GitHub Actions
        Professional Experience
        Backend Engineer at Acme | 2021 - 2024
        Education
        MSc Computer Science | 2020 - 2021
        BSc Mathematics | 2017 - 2020
        """,
        "jordan.pdf",
    )

    assert cv.name == "Jordan Smith"
    assert {
        "python", "fastapi", "postgresql", "redis", "terraform", "github actions"
    } <= {skill.casefold() for skill in cv.skills}
    assert len(cv.experience) == 1
    assert cv.experience[0].title == "Backend Engineer"
    assert cv.education == ["MSc Computer Science | 2020 - 2021", "BSc Mathematics | 2017 - 2020"]
