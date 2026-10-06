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
