# OpsPilot

OpsPilot is an operations-resolution platform that will investigate support tickets, gather
evidence, recommend actions, require approval for sensitive changes, and retain an audit trail.

This first milestone intentionally contains no AI: it establishes the customer and ticket API
that later workflows will build on.

## Quick start without Docker

The project can use SQLite for local development, so Docker and PostgreSQL are not required to
start the API:

```bash
source .venv/bin/activate
export DATABASE_URL=sqlite:///./opspilot.db
python -m app.seed
uvicorn app.main:app --reload
```

Then open <http://localhost:8000/docs>. Stop the server with `Control-C`. The SQLite database is
stored in the ignored `opspilot.db` file. Use PostgreSQL through Docker before deployment and for
integration testing.

## Run with Docker

```bash
docker compose up --build
```

Then open the interactive API docs at <http://localhost:8000/docs>.

Seed sample data while the services are running:

```bash
docker compose exec api python -m app.seed
```

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

## API implemented

- `GET /health`
- `POST /customers`
- `GET /customers/{id}`
- `GET /tickets` (optional `status` and `priority` filters)
- `GET /tickets/{id}`
- `POST /tickets`
- `PATCH /tickets/{id}`

## Next milestone

Build a small Next.js page that lists tickets, opens a ticket detail view, and updates status.
