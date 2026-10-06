# Job Finder

Job Finder is a CV-aware job discovery web application built with FastAPI. It extracts a CV from PDF, sends the extracted text to a local Ollama agent running `granite3.2:2b`, stores the structured profile in SQLite, searches job sources, and ranks results against the candidate profile.

## Features

- PDF CV upload and structured extraction through Ollama.
- Pydantic validation for skills, experience, projects, education, certifications, and achievements.
- Agent-generated search phrases and job ranking.
- Experience-aware filtering.
- SQLite persistence for the CV and jobs.
- Automated sources: Arbeitnow, Remotive, and Jobicy.
- Search links for LinkedIn, Indeed, Glassdoor, and APEC.
- Optional LangSmith tracing for model calls.
- Browser dashboard with profile and job result views.

## Requirements

- Python 3.11 or newer
- Ollama
- The Granite model:

```powershell
ollama pull granite3.2:2b
```

## Local setup

Create and activate a virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Start Ollama in a separate terminal:

```powershell
ollama serve
```

Copy `.env.example` to `.env` and adjust the values if needed:

```env
OLLAMA_HOST=http://127.0.0.1:11434
OLLAMA_MODEL=granite3.2:2b
```

Start the application from the repository root:

```powershell
python run.py
```

Open <http://127.0.0.1:8000>.

The application also provides a settings form for entering an optional LangSmith key. LangSmith tracing must not be enabled with a placeholder or invalid key.

## Docker

The application container runs the web server and Ollama runs as a separate service because the Granite model is large.

### Docker Compose

The complete local stack can be started with:

```powershell
docker compose up --build
```

Compose starts:

- `job-finder` on <http://127.0.0.1:8000>
- `ollama` on <http://127.0.0.1:11434>

The Ollama service automatically pulls `${OLLAMA_MODEL}` on first startup and stores model data in the `ollama-data` volume. Application data is stored in `job-finder-data`.

Stop the stack with:

```powershell
docker compose down
```

To remove persisted models and application data too:

```powershell
docker compose down --volumes
```

### Standalone application container

The application container can also use an Ollama instance running on the host:

Build and run:

```powershell
docker build -t job-finder .
docker run --rm -p 8000:8000 `
  -e OLLAMA_HOST=http://host.docker.internal:11434 `
  -e OLLAMA_MODEL=granite3.2:2b `
  -v job-finder-data:/app/data `
  job-finder
```

On Linux, replace `host.docker.internal` with the reachable Ollama host address, or add:

```text
--add-host=host.docker.internal:host-gateway
```

The SQLite database is stored at `/app/data/job_finder.db` in the container. The volume keeps it across container recreation.

## Testing

Run the test suite:

```powershell
python -m pytest Tests --cov=CV --cov=Database --cov=Ingestion.pdf_parser --cov=Search.service --cov-report=term-missing --cov-fail-under=70
```

The coverage gate measures deterministic application logic. The Ollama transport is intentionally excluded from the threshold because it requires a live model service; it should be covered by a separate integration environment.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `OLLAMA_HOST` | `http://127.0.0.1:11434` | Ollama server URL |
| `OLLAMA_MODEL` | `granite3.2:2b` | Model used for CV parsing and ranking |
| `LANGSMITH_TRACING` | unset | Enables LangSmith tracing when set to `true` |
| `LANGSMITH_ENDPOINT` | `https://api.smith.langchain.com` | LangSmith endpoint |
| `LANGSMITH_API_KEY` | unset | Optional LangSmith API key |
| `LANGSMITH_PROJECT` | `Jobs` | LangSmith project name |

Do not commit `.env`, API keys, the SQLite database, virtual environments, or uploaded CVs.

## Application layout

```text
CV/                 Pydantic CV models
Database/           SQLite repository
Ingestion/          PDF extraction and Ollama agent
Search/             Job APIs, filtering, and ranking
Interface/          FastAPI routes and templates
Tests/              Automated tests
run.py              Local development entry point
Dockerfile          Container image definition
```

## CI/CD

The GitHub Actions workflow in `.github/workflows/ci.yml` implements:

```text
GitHub
   ↓
Tests + coverage (Python 3.12, minimum 70%)
   ↓
Docker build
   ↓
Push image to GHCR (pushes to main/master)
   ↓
Deploy to Render
```

The workflow:

1. Runs tests with a 70% coverage gate.
2. Builds the Docker image on pull requests and pushes.
3. Publishes `ghcr.io/<owner>/<repository>` on pushes to `main` or `master`.
4. Triggers Render after the image has been published.

Configure the repository secret `RENDER_DEPLOY_HOOK` with the deploy-hook URL from the Render service. If this secret is not configured, the deploy job is skipped. Configure Render to deploy the GHCR image:

```text
ghcr.io/<owner>/<repository>:latest
```

The GHCR package must be public, or the Render service must have credentials with permission to pull private packages. The workflow does not download Ollama models; the Compose deployment pulls the model automatically, while hosted deployments should provide a reachable Ollama service.
