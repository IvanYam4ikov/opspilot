import hashlib
from dataclasses import dataclass

from app.models import Recommendation, Ticket


@dataclass(frozen=True)
class SimulatedActionResult:
    external_reference: str
    details: dict


def execute_simulated_action(
    ticket: Ticket, recommendation: Recommendation, idempotency_key: str
) -> SimulatedActionResult:
    """Simulate a retry-safe call to an external billing or support system."""
    digest = hashlib.sha256(idempotency_key.encode()).hexdigest()[:12].upper()
    external_reference = f"SIM-{digest}"
    action = recommendation.recommended_action

    messages = {
        "issue_partial_credit": "A partial billing credit was recorded.",
        "refund_duplicate_charge": "The duplicate charge was refunded.",
        "review_invoice": "The invoice was queued for manual billing review.",
        "request_more_information": "A request for additional information was sent.",
        "no_action": "The case was verified and no external change was made.",
        "reset_credentials": "A credential-reset workflow was started.",
        "approve_cancellation": "The cancellation was recorded.",
        "escalate": "The case was escalated to a specialist queue.",
    }
    if action not in messages:
        raise RuntimeError(f"Unsupported action: {action}")

    return SimulatedActionResult(
        external_reference=external_reference,
        details={
            "action": action,
            "message": messages[action],
            "ticket_id": ticket.id,
            "recommendation_id": recommendation.id,
            "simulated": True,
        },
    )
