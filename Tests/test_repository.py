from CV.models import CV
from Database.repository import Repository


def test_repository_persists_cv_and_jobs(tmp_path) -> None:
    repository = Repository(tmp_path / "test.db")
    repository.save_cv(CV(name="Ada", skills=["Python"]))
    repository.save_jobs(
        [
            {
                "external_id": "1",
                "title": "Engineer",
                "company": "Acme",
                "location": "Remote",
                "url": "https://example.com/job",
                "description": "Python",
                "source": "test",
                "matched_terms": ["python"],
            }
        ]
    )

    assert repository.get_cv().name == "Ada"
    assert repository.list_jobs()[0]["matched_terms"] == ["python"]


def test_repository_replaces_old_search_results(tmp_path) -> None:
    repository = Repository(tmp_path / "replace.db")
    first = {
        "external_id": "old",
        "title": "Old role",
        "company": "Old Co",
        "location": "Remote",
        "url": "https://example.com/old",
        "description": "old",
        "source": "Remotive",
        "matched_terms": [],
        "details": {},
    }
    second = {**first, "external_id": "new", "title": "New role"}
    repository.save_jobs([first])
    repository.replace_jobs([second], ["Remotive"])

    assert [job["external_id"] for job in repository.list_jobs()] == ["new"]
