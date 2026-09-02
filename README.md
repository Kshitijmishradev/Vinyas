# Architect Pro

Deterministic architecture analysis and baseline-aware CI governance for Python and JavaScript/TypeScript repositories.

Architect Pro builds an evidence-backed dependency graph, finds architecture violations, and helps teams prevent new structural debt without forcing them to fix every legacy issue first. Local AI is optional and can explain findings, but it never creates findings or changes CI outcomes.

## What it does

- Resolves Python packages, namespace-style packages, and relative imports.
- Resolves JS, JSX, TS, and TSX relative imports, index modules, and `tsconfig` path aliases.
- Keeps isolated files and reports ambiguous imports instead of guessing.
- Detects every dependency cycle and calculates explicit fan-in, fan-out, symbol count, dependency depth, and cycle-participation metrics.
- Enforces layer boundaries and configurable budgets through `architect.yaml`.
- Produces JSON, standalone HTML, and SARIF reports.
- Compares against a Git ref or saved report and fails only for newly introduced findings.
- Provides a repository-restricted local explorer with progress, cancellation, tables, graph navigation, evidence, and optional Ollama explanations.

## Five-minute start

Requires Python 3.10+ and, for the web explorer, Node 20+.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'

architect analyze . --output analysis.json
architect report . --format html --output architect-report.html
architect check . --baseline main --sarif architect.sarif
```

Start the local explorer:

```bash
architect serve .
cd frontend && npm ci && npm run dev
```

Open `http://127.0.0.1:5173`. The API accepts only the repository passed to `architect serve`; the browser cannot request arbitrary host paths.

Alternatively:

```bash
docker compose up --build
```

The Docker stack is available at `http://127.0.0.1:5173`. It mounts only the current repository as read-only and stores analysis metadata in a dedicated volume.

To analyze another repository without editing Compose, set `ARCHITECT_REPO` to its absolute path:

```bash
ARCHITECT_REPO=/absolute/path/to/another/repository docker compose up --build
```

For a persistent local setting, copy `.env.example` to `.env`, set `ARCHITECT_REPO`, and then use the normal `docker compose up --build` command. After changing repositories, restart the stack with `docker compose down` followed by `docker compose up --build`.

## CLI

```text
architect analyze PATH [--config FILE] [--output FILE]
architect report PATH --format html|json|sarif --output FILE
architect check PATH --baseline GIT_REF_OR_JSON [--sarif FILE] [--html FILE]
architect serve PATH [--host 127.0.0.1] [--port 8000]
```

`architect check` exits with status 1 only when the current repository contains active finding fingerprints absent from the baseline. The Git ref must be available locally; CI should use a full checkout or fetch the base ref.

## Governance configuration

Copy `architect.example.yaml` to `architect.yaml` and adapt it:

```yaml
include: ["src/**/*", "packages/**/*"]
exclude: ["**/*.generated.ts", "**/fixtures/**"]

layers:
  - name: presentation
    match: ["src/web/**"]
  - name: domain
    match: ["src/domain/**"]

forbidden_dependencies:
  - from: domain
    to: presentation

# Optional allow-list mode: when present, unlisted cross-layer edges are denied.
allowed_dependencies:
  - from: presentation
    to: domain

thresholds:
  cycles: 0
  fan_out: 20
  unresolved_imports: 0
  cross_boundary: 20

suppressions:
  - rule: forbidden-dependency
    path: "src/legacy/**"
    reason: "Migration tracked in issue #123"
    expires: 2026-12-31
```

Expired suppressions stop applying automatically. Every suppression requires a reason.

## API v1

- `POST /api/v1/analyses` — queue a scan within the configured repository root.
- `GET /api/v1/analyses/{id}` — read status, progress, and summary.
- `GET /api/v1/analyses/{id}/findings` — read deterministic findings and evidence.
- `GET /api/v1/analyses/{id}/graph` — read files, edges, metrics, and cycles.
- `POST /api/v1/analyses/{id}/explanations` — explain one verified finding.
- `DELETE /api/v1/analyses/{id}` — cancel a running scan or delete a completed result.

Analyses are stored in `.architect/analyses.sqlite3`. Full source files are not persisted; results contain paths, hashes, metrics, dependency evidence excerpts, and findings.

## Optional local AI

AI is disabled by default. Enable Ollama explanations only when desired:

```bash
export ARCHITECT_OLLAMA_ENABLED=true
export ARCHITECT_OLLAMA_MODEL=qwen2.5-coder:7b
architect serve .
```

Explanations receive only the selected deterministic finding and its evidence excerpt. If Ollama is unavailable, the API returns a deterministic explanation and marks it as non-AI.

## CI

The included `.github/workflows/architect.yml` runs backend checks, frontend checks, Docker builds, baseline-aware governance, SARIF upload, and an HTML report artifact. Ensure the workflow fetches the pull request base ref.

```bash
architect check . \
  --baseline "$BASE_SHA" \
  --sarif architect.sarif \
  --html architect-report.html
```

## Development and verification

```bash
pip install -e '.[dev]'
pytest
ruff check architect tests
mypy architect

cd frontend
npm ci
npm run lint
npm run build
```

The correctness suite covers relative Python imports, TSX and aliases, isolated files, ambiguous resolution, multiple cycles, governance suppressions, reports, baseline fingerprints, and SQLite lifecycle behavior.

## Security model and limitations

- Run the API on loopback unless you add authentication and a trusted reverse proxy.
- The server is restricted to `ARCHITECT_ROOT`; Docker mounts only that repository.
- Import analysis is static. Dynamic Python imports, runtime module loaders, framework-generated dependencies, and arbitrary bundler plugins may require future adapters.
- Java, Go, Rust, and C/C++ are not part of the reliable v1 analyzer. New languages should implement the analyzer/resolver boundary without weakening resolution confidence.
- AI output is advisory and never used for severity, rule evaluation, baselines, or exit codes.
