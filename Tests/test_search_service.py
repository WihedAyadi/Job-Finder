from CV.models import CV, Experience
from Search.service import build_search_query


def test_search_query_uses_agent_cv_phrase() -> None:
    cv = CV(
        search_phrase="Senior data scientist Python machine learning",
        skills=["Python"],
    )

    assert build_search_query(cv) == "Senior data scientist Python machine learning"


def test_search_query_falls_back_to_cv_profile() -> None:
    cv = CV(
        experience=[Experience(company="Acme", title="Data Engineer")],
        skills=["Python", "SQL"],
    )

    assert build_search_query(cv) == "Data Engineer Python SQL"
