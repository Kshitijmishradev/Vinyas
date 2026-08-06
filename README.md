# Architect CLI v4

<p align="center">
  <strong>Interactive architecture mapping for real codebases.</strong><br/>
  Scan repositories, infer dependency relationships, and explore the graph in a modern React UI.
</p>

🔗 [Project page](https://kshitijmishradev.github.io/Architech_CLI/)

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white" />
  <img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-API-009688?logo=fastapi&logoColor=white" />
  <img alt="React" src="https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=111" />
  <img alt="Vite" src="https://img.shields.io/badge/Vite-Frontend-646CFF?logo=vite&logoColor=white" />
</p>

## Why Architect CLI

- Understand large codebases quickly with dependency-focused architecture views.
- Analyze with or without LLM labels (`hints` mode is very fast and deterministic).
- Navigate results in an interactive frontend (search, filtering, focused exploration).
- Keep results reusable with persisted analysis and label cache files.

## Architecture

- Backend: FastAPI (`architect/api_server.py`)
- Analyzer core: scanner + dependency resolution + optional LLM labeling (`architect/analysis_core.py`)
- Frontend: React + Vite + Sigma.js graph rendering (`frontend/`)

## Quick Start

### 1. Install dependencies

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cd frontend && npm install && cd ..
```

### 2. Start full local stack

```bash
make dev
```

Services:

- Backend: `http://127.0.0.1:8000`
- Frontend: `http://127.0.0.1:5173`

## API Usage

### Health check

```bash
curl -s http://127.0.0.1:8000/api/health
```

### Analyze any repository

```bash
curl -s -X POST http://127.0.0.1:8000/api/analyze \
  -H 'Content-Type: application/json' \
  -d '{
    "path": "/absolute/path/to/repo",
    "no_llm": true,
    "label_mode": "hints",
    "max_edges": 200
  }'
```

Useful endpoints:

- `GET /api/health`
- `POST /api/analyze`
- `POST /api/path-explanation`
- `POST /api/risk-analysis`
- `POST /api/search`

## Tinygrad Example

This project has already been exercised against the `tinygrad` codebase and works well on large dependency graphs.

Suggested request for Tinygrad:

```bash
curl -s -X POST http://127.0.0.1:8000/api/analyze \
  -H 'Content-Type: application/json' \
  -d '{
    "path": "/Users/kshitijmishra/tinygrad",
    "no_llm": false,
    "label_mode": "hybrid",
    "max_edges": 0
  }'
```

### Tinygrad UI snapshots

<p>
  <img src="img/Screenshot 2026-03-07 at 11.20.14 PM.png" alt="Tinygrad architecture view 1" width="49%" />
  <img src="img/Screenshot 2026-03-07 at 11.21.11 PM.png" alt="Tinygrad architecture view 2" width="49%" />
</p>
<p>
  <img src="img/Screenshot 2026-03-07 at 11.21.56 PM.png" alt="Tinygrad architecture view 3" width="49%" />
  <img src="img/Screenshot 2026-03-07 at 11.22.01 PM.png" alt="Tinygrad architecture view 4" width="49%" />
</p>

## LLM Labels (Optional)

To enable semantic relationship labels, run Ollama locally:

```bash
ollama serve
ollama pull qwen2.5-coder:7b
```

Then send analyze requests with `"no_llm": false` and optionally set `"model"`.

## Persistence

- Analysis store: `.architect_analysis_store.json`
- LLM label cache: `.architect_cache.json`

## Dev Commands

### Backend only

```bash
venv/bin/python -m uvicorn architect.api_server:app --host 127.0.0.1 --port 8000
```

### Frontend only

```bash
cd frontend
npm run dev -- --host 127.0.0.1 --port 5173
```

### Tests

```bash
venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
```

### Docker

```bash
docker compose up --build
```
