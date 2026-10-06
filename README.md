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

The application container runs the web server. Ollama remains a separate service because the model is large and is normally managed by the host or a dedicated Ollama service.

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
python -m pytest Tests -q
```

Tests do not require a live Ollama server. A running Ollama instance and `granite3.2:2b` are required for actual CV uploads and AI job ranking.

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

GitHub Actions runs on pushes and pull requests:

1. Installs the supported Python version.
2. Installs dependencies.
3. Runs the test suite.
4. Builds the Docker image.

The pipeline intentionally does not download the Ollama model. Model inference is an external runtime dependency and should be validated in deployment or a separate integration environment.
