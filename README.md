# OpsPilot

OpsPilot is an operations-resolution platform that will investigate support tickets, gather
evidence, recommend actions, require approval for sensitive changes, and retain an audit trail.

The current milestone includes a FastAPI and PostgreSQL API, a Next.js operations dashboard, an
evidence-based investigation workflow, and human-controlled action execution. Investigations
retrieve account, invoice, and knowledge records, produce a schema-validated recommendation, and
retain an audit timeline. Sensitive actions require an explicit approval before execution.

## Quick start without Docker

The API can use SQLite for local development, so Docker and PostgreSQL are not required. Start the
API in one terminal:

```bash
source .venv/bin/activate
export DATABASE_URL=sqlite:///./opspilot.db
python -m app.seed
uvicorn app.main:app --reload
```

Then open <http://localhost:8000/docs>. Stop the server with `Control-C`. The SQLite database is
stored in the ignored `opspilot.db` file. Use PostgreSQL through Docker before deployment and for
integration testing.

Start the dashboard in a second terminal:

```bash
cd frontend
cp .env.example .env.local
npm install
npm run dev
```

Open <http://localhost:3000>.

## Run with Docker

```bash
docker compose up --build
```

Then open the dashboard at <http://localhost:3000> or the interactive API docs at
<http://localhost:8000/docs>.

Seed sample data while the services are running:

```bash
docker compose exec api python -m app.seed
```

This also creates six tickets prefixed with `[Eval]` covering overbilling, a valid disputed
invoice, duplicate charges, missing evidence, prompt injection, and a Spanish-language request.

## Run locally

Start PostgreSQL (the database service can run by itself with
`docker compose up db`), then:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
uvicorn app.main:app --reload --env-file .env
```

## Verify

```bash
pytest
ruff check .
```

Tests use a temporary local SQLite database, so they do not require PostgreSQL.

## Product features

- Browse and filter the support ticket queue
- Review ticket and customer details
- Update ticket status and priority
- Create new tickets for existing customers
- Investigate tickets using retrieved operational evidence
- View structured diagnoses, confidence, cited evidence, and recommended actions
- Approve or reject sensitive recommendations with a reviewer and rationale
- Execute approved actions against a simulated external service
- Retry failed executions safely with idempotency keys
- Review an immutable activity timeline for each ticket
- Responsive layout for desktop and mobile

## API implemented

- `GET /health`
- `POST /customers`
- `GET /customers`
- `GET /customers/{id}`
- `GET /tickets` (optional `status` and `priority` filters)
- `GET /tickets/{id}`
- `POST /tickets`
- `PATCH /tickets/{id}`
- `POST /tickets/{id}/investigate`
- `GET /tickets/{id}/recommendations`
- `POST /tickets/{id}/recommendations/{recommendation_id}/approve`
- `POST /tickets/{id}/recommendations/{recommendation_id}/reject`
- `POST /tickets/{id}/recommendations/{recommendation_id}/execute`
- `GET /tickets/{id}/events`

The execute endpoint requires an `Idempotency-Key` header. Repeating a completed request with the
same key returns the original execution, while failed requests can be retried with that key. The
simulated adapter returns a stable external reference and never contacts a real billing system.

## Investigation modes

The default `demo` mode is deterministic and requires no API key. It is useful for local demos and
tests:

```bash
INVESTIGATION_MODE=demo docker compose up --build
```

To use OpenAI structured outputs, create a local `.env` file (never commit it):

```bash
INVESTIGATION_MODE=openai
OPENAI_API_KEY=your_api_key
OPENAI_MODEL=gpt-4o-mini
```

Then restart with `docker compose up --build`. Both modes return the same Pydantic-validated
recommendation schema, so the UI and persistence layer do not depend on the provider.

## Evaluate investigation quality

List the seeded evaluation cases without calling a model:

```bash
docker compose exec api python -m app.evaluate --list
```

Run the full suite against the currently configured provider:

```bash
docker compose exec api python -m app.evaluate
```

Or run one case:

```bash
docker compose exec api python -m app.evaluate --case prompt_injection
```

Each case receives one point for the expected category, action, approval decision, and required
evidence types. The runner also prints latency. In `openai` mode, every case makes an API request
and incurs usage; use `demo` mode for the free deterministic baseline.

## Next milestone

Add authentication and role-based access control, move investigations and action execution to a
background worker, and add production observability for model latency, token usage, cost, provider
errors, approval rates, and execution outcomes.
