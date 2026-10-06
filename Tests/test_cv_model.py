from CV.models import CV, Experience, Project


def test_cv_collects_searchable_terms() -> None:
    cv = CV(
        skills=["Python"],
        experience=[Experience(company="Acme", title="Backend Engineer", skills=["SQL"])],
        projects=[Project(name="Job Finder", technologies=["FastAPI"])],
    )

    assert cv.searchable_terms() == {
        "python",
        "backend engineer",
        "sql",
        "job finder",
        "fastapi",
    }
