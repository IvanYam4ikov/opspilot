# OpsPilot

OpsPilot is an AI-assisted operations platform that turns customer support requests into evidence-backed recommendations and controlled actions. It demonstrates how an enterprise AI workflow can move beyond a chat interface: retrieve business context, produce a structured decision, require human approval for risky changes, execute through an idempotent adapter, and preserve an audit trail.

## The business problem

Operations teams often resolve billing, access, and cancellation requests by manually checking tickets, account records, invoices, and policy documents. That process is slow, inconsistent, and difficult to audit. OpsPilot provides a single queue where an operator can investigate a request, inspect the evidence used by the model, route sensitive decisions to an authorized approver, and execute the approved action.

The application is designed around the controls that matter in production AI:

- Grounded outputs: every recommendation cites the ticket and retrieved account, invoice, or policy evidence.
- Structured decisions: model output is validated against a typed schema rather than displayed as unconstrained prose.
- Human-in-the-loop safety: credit and refund actions cannot run until an approver or administrator authorizes them.
- Durable execution: investigations and external actions run as database-backed jobs with retry state and failure visibility.
- Idempotency and auditability: duplicate action requests cannot create duplicate side effects, and every workflow transition is recorded.
- Role-based access: operators, approvers, and administrators receive distinct permissions through signed bearer tokens.

## Architecture

```text
Next.js operations console
        │ authenticated REST calls + job polling
        ▼
FastAPI control plane ───────────────► PostgreSQL
        │                              tickets, evidence,
        │ enqueue durable job           jobs, approvals,
        │                              executions, audit events
        ▼
Background worker
        │ retrieve business context
        │ run deterministic demo engine or OpenAI model
        │ validate structured result
        ▼
Human approval gate ──► idempotent action adapter
```

The API remains responsive while model calls and simulated external actions execute in a separate worker. PostgreSQL is the source of truth for job status, retry attempts, approvals, and workflow history. Alembic owns schema initialization, and GitHub Actions validates both application layers on every push and pull request.

## Technology

- Backend: Python 3.13, FastAPI, SQLAlchemy, Pydantic, PyJWT
- AI: OpenAI Responses API with structured outputs; deterministic offline provider for repeatable demos and evaluation
- Data: PostgreSQL 17 and Alembic migrations
- Frontend: Next.js, React, TypeScript
- Delivery: Docker Compose and GitHub Actions
- Quality: Pytest, Ruff, TypeScript type checking, production frontend build

## Run locally

Prerequisites: Docker Desktop with Docker Compose.

```bash
cp .env.example .env
docker compose up --build
```

Open the operations console at [http://localhost:3000](http://localhost:3000) or the interactive API documentation at [http://localhost:8000/docs](http://localhost:8000/docs).

The API container applies the database migration and loads idempotent demo data before it starts. The worker container then processes queued investigations and executions.

### Demo accounts

| Role | Email | Password | Capabilities |
| --- | --- | --- | --- |
| Operator | `operator@opspilot.example` | `demo-operator` | Create/update tickets, investigate, execute approved actions |
| Approver | `approver@opspilot.example` | `demo-approver` | Review recommendations and execute actions |
| Administrator | `admin@opspilot.example` | `demo-admin` | Full demo access and operational metrics |

These credentials are for local demonstration only. Set a long random `AUTH_SECRET` and connect the application to an enterprise identity provider before any real deployment.

## Try the end-to-end workflow

1. Sign in as the administrator.
2. Select **Invoice amount appears incorrect** or another evaluation ticket.
3. Choose **Investigate**. The API returns a queued job and the UI polls until the worker completes it.
4. Review the category, confidence score, cited evidence, and recommended action.
5. Approve or reject the recommendation. The reviewer is derived from the authenticated user.
6. Execute an approved action. A second durable job calls the idempotent simulated adapter and updates the ticket.
7. Inspect the activity timeline or `GET /ops/metrics` for workflow and job telemetry.

Stop the stack with:

```bash
docker compose down
```

Add `-v` only when you intentionally want to delete the local PostgreSQL data volume.

## Use a real model

The default `demo` mode is deterministic, requires no API key, and is suitable for local development and repeatable evaluation. To use OpenAI, edit `.env`:

```dotenv
INVESTIGATION_MODE=openai
OPENAI_API_KEY=your-key
OPENAI_MODEL=gpt-4o-mini
```

Then rebuild the services:

```bash
docker compose up --build
```

The recommendation footer identifies the provider that generated the result. The model receives retrieved application records and must return the same validated investigation schema used by the demo provider. No action bypasses the approval and idempotency controls based on model confidence.

## API workflow

Authentication starts with `POST /auth/login`; subsequent requests use `Authorization: Bearer <token>`.

| Endpoint | Purpose |
| --- | --- |
| `POST /tickets/{id}/investigate` | Queue an evidence-backed investigation |
| `GET /jobs/{id}` | Read queued, running, completed, or failed job state |
| `GET /tickets/{id}/recommendations` | Inspect the latest recommendation and evidence |
| `POST /tickets/{id}/recommendations/{id}/approve` | Record an authorized approval |
| `POST /tickets/{id}/recommendations/{id}/reject` | Record an authorized rejection |
| `POST /tickets/{id}/recommendations/{id}/execute` | Queue an action with an `Idempotency-Key` header |
| `GET /tickets/{id}/events` | Read the append-only workflow timeline |
| `GET /ops/metrics` | Read job throughput and workflow counts (approver/admin) |

## Tests and evaluation

Run the backend suite:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
ruff check .
pytest -q
```

Run the frontend checks:

```bash
cd frontend
npm ci
npm run typecheck
npm run build
```

The seeded evaluation set includes billing mismatches, verified invoices, duplicate charges, insufficient evidence, multilingual input, and untrusted instructions embedded in tickets. Tests assert expected classification, action, evidence coverage, authentication, authorization, job retry behavior, approval gating, and idempotent execution.

## Engineering tradeoffs and next steps

This portfolio implementation deliberately keeps infrastructure runnable on one laptop. Its durable queue uses PostgreSQL rather than a managed queue, authentication uses locally seeded users rather than OIDC, retrieval is based on typed business records rather than vector search, and external actions are simulated.

The next production-oriented milestone would add semantic retrieval with source versioning, an enterprise identity provider, OpenTelemetry traces and exported metrics, a managed queue with dead-letter handling, and deployment to a cloud environment with secrets management and infrastructure as code.
