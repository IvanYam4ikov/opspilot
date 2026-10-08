import logging
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import actions
from app.database import SessionLocal
from app.investigation import generate_recommendation, retrieve_context
from app.models import ActionExecution, AuditEvent, Job, Recommendation, Ticket

logger = logging.getLogger("opspilot.jobs")


def process_next_job() -> bool:
    with SessionLocal() as db:
        statement = (
            select(Job)
            .where(Job.status == "queued", Job.available_at <= datetime.now(UTC))
            .order_by(Job.created_at, Job.id)
            .limit(1)
        )
        if db.bind is not None and db.bind.dialect.name != "sqlite":
            statement = statement.with_for_update(skip_locked=True)
        job = db.scalar(statement)
        if job is None:
            return False
        job.status = "running"
        job.attempts += 1
        job.started_at = datetime.now(UTC)
        job.error = None
        db.commit()
        job_id = job.id
    _run_job(job_id)
    return True


def _run_job(job_id: int) -> None:
    started = time.perf_counter()
    try:
        with SessionLocal() as db:
            job = db.get(Job, job_id)
            if job is None:
                return
            if job.job_type == "investigation":
                result = _process_investigation(db, job)
            elif job.job_type == "action_execution":
                result = _process_action_execution(db, job)
            else:
                raise RuntimeError(f"Unsupported job type: {job.job_type}")

            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            job.status = "completed"
            job.result = {**result, "duration_ms": duration_ms}
            job.completed_at = datetime.now(UTC)
            db.commit()
            logger.info(
                "job_completed job_id=%s type=%s duration_ms=%s attempts=%s",
                job.id,
                job.job_type,
                duration_ms,
                job.attempts,
            )
    except Exception as exc:  # noqa: BLE001 - persist and retry provider failures
        with SessionLocal() as db:
            job = db.get(Job, job_id)
            if job is None:
                return
            job.error = str(exc)
            if job.attempts < job.max_attempts:
                job.status = "queued"
                job.available_at = datetime.now(UTC) + timedelta(seconds=2**job.attempts)
            else:
                job.status = "failed"
                job.completed_at = datetime.now(UTC)
            db.commit()
            logger.warning(
                "job_failed job_id=%s type=%s attempts=%s terminal=%s error=%s",
                job.id,
                job.job_type,
                job.attempts,
                job.status == "failed",
                exc,
            )


def process_job(job_id: int) -> Job:
    """Process a specific queued job. Used by tests and local tooling."""
    with SessionLocal() as db:
        target = db.get(Job, job_id)
        if target is None:
            raise ValueError("Job not found")
        if target.status != "queued":
            db.expunge(target)
            return target
        target.status = "running"
        target.attempts += 1
        target.started_at = datetime.now(UTC)
        target.error = None
        db.commit()
    _run_job(job_id)
    with SessionLocal() as db:
        completed = db.get(Job, job_id)
        if completed is None:
            raise ValueError("Job not found")
        db.expunge(completed)
        return completed


def _process_investigation(db: Session, job: Job) -> dict:
    if job.ticket_id is None:
        raise RuntimeError("Investigation job is missing a ticket")
    ticket = db.get(Ticket, job.ticket_id)
    if ticket is None:
        raise RuntimeError("Ticket not found")
    db.add(
        AuditEvent(
            ticket_id=ticket.id,
            event_type="investigation_started",
            message="Investigation started",
            event_metadata={"job_id": job.id, "attempt": job.attempts},
        )
    )
    context = retrieve_context(db, ticket)
    result, provider = generate_recommendation(context)
    recommendation = Recommendation(
        ticket_id=ticket.id,
        provider=provider,
        **result.model_dump(mode="json"),
    )
    db.add(recommendation)
    db.flush()
    job.recommendation_id = recommendation.id
    db.add_all(
        [
            AuditEvent(
                ticket_id=ticket.id,
                event_type="evidence_retrieved",
                message=f"Retrieved {len(result.evidence)} evidence sources",
                event_metadata={
                    "job_id": job.id,
                    "sources": [item.source_id for item in result.evidence],
                },
            ),
            AuditEvent(
                ticket_id=ticket.id,
                event_type="recommendation_generated",
                message=f"Recommended action: {result.recommended_action}",
                event_metadata={
                    "job_id": job.id,
                    "recommendation_id": recommendation.id,
                    "confidence": result.confidence,
                    "provider": provider,
                },
            ),
        ]
    )
    db.flush()
    return {
        "recommendation_id": recommendation.id,
        "provider": provider,
        "confidence": result.confidence,
        "evidence_count": len(result.evidence),
    }


def _process_action_execution(db: Session, job: Job) -> dict:
    if job.ticket_id is None or job.recommendation_id is None or job.idempotency_key is None:
        raise RuntimeError("Action job is missing required identifiers")
    ticket = db.get(Ticket, job.ticket_id)
    recommendation = db.get(Recommendation, job.recommendation_id)
    if ticket is None or recommendation is None:
        raise RuntimeError("Ticket or recommendation not found")
    if recommendation.approval is not None and recommendation.approval.decision == "rejected":
        raise RuntimeError("Rejected recommendations cannot be executed")
    if recommendation.requires_approval and (
        recommendation.approval is None or recommendation.approval.decision != "approved"
    ):
        raise RuntimeError("Approval is required before execution")

    execution = db.scalar(
        select(ActionExecution).where(ActionExecution.idempotency_key == job.idempotency_key)
    )
    if execution is not None and execution.status == "completed":
        return {
            "execution_id": execution.id,
            "external_reference": execution.external_reference,
            "action": execution.action,
        }
    if execution is None:
        execution = ActionExecution(
            recommendation_id=recommendation.id,
            ticket_id=ticket.id,
            action=recommendation.recommended_action,
            idempotency_key=job.idempotency_key,
            status="executing",
            attempts=job.attempts,
            result={},
        )
        db.add(execution)
        db.flush()
    else:
        execution.status = "executing"
        execution.error = None
        execution.attempts = job.attempts

    db.add(
        AuditEvent(
            ticket_id=ticket.id,
            event_type="action_execution_started",
            message=f"Executing action: {recommendation.recommended_action}",
            event_metadata={
                "job_id": job.id,
                "recommendation_id": recommendation.id,
                "idempotency_key": job.idempotency_key,
                "attempt": job.attempts,
            },
        )
    )
    db.commit()

    try:
        result = actions.execute_simulated_action(ticket, recommendation, job.idempotency_key)
    except RuntimeError as exc:
        execution.status = "failed"
        execution.error = str(exc)
        db.add(
            AuditEvent(
                ticket_id=ticket.id,
                event_type="action_execution_failed",
                message=f"Action execution failed: {exc}",
                event_metadata={
                    "job_id": job.id,
                    "recommendation_id": recommendation.id,
                    "attempt": job.attempts,
                },
            )
        )
        db.commit()
        raise

    execution.status = "completed"
    execution.external_reference = result.external_reference
    execution.result = result.details
    execution.error = None
    execution.completed_at = datetime.now(UTC)
    ticket.status = (
        "in_progress"
        if recommendation.recommended_action
        in {"request_more_information", "escalate", "review_invoice"}
        else "resolved"
    )
    db.add(
        AuditEvent(
            ticket_id=ticket.id,
            event_type="action_execution_completed",
            message=f"Completed action: {recommendation.recommended_action}",
            event_metadata={
                "job_id": job.id,
                "recommendation_id": recommendation.id,
                "external_reference": result.external_reference,
                "idempotency_key": job.idempotency_key,
            },
        )
    )
    db.flush()
    return {
        "execution_id": execution.id,
        "external_reference": result.external_reference,
        "action": recommendation.recommended_action,
    }
