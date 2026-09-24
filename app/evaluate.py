import argparse
import time

from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal
from app.evaluation_cases import EVALUATION_CASES
from app.investigation import generate_recommendation, retrieve_context
from app.models import Ticket


def main() -> None:
    parser = argparse.ArgumentParser(description="Run OpsPilot's local investigation eval suite.")
    parser.add_argument("--case", help="Run one case by key instead of the full suite.")
    parser.add_argument("--list", action="store_true", help="List cases without calling a model.")
    args = parser.parse_args()

    cases = [case for case in EVALUATION_CASES if args.case in (None, case.key)]
    if args.case and not cases:
        raise SystemExit(f"Unknown case: {args.case}")
    if args.list:
        for case in cases:
            print(f"{case.key:24} {case.title}")
        return

    print(f"Provider mode: {settings.investigation_mode}")
    print(f"Model: {settings.openai_model if settings.investigation_mode == 'openai' else 'demo'}")
    print("Scoring: category, action, approval gate, required evidence\n")

    earned = 0
    possible = len(cases) * 4
    with SessionLocal() as db:
        for case in cases:
            ticket = db.scalar(select(Ticket).where(Ticket.title == case.title))
            if ticket is None:
                print(f"FAIL {case.key}: ticket not seeded")
                continue
            started = time.perf_counter()
            try:
                result, provider = generate_recommendation(retrieve_context(db, ticket))
            except Exception as exc:  # noqa: BLE001 - report provider failures per case
                print(f"ERROR {case.key}: {type(exc).__name__}: {exc}")
                continue
            elapsed = time.perf_counter() - started
            evidence_types = {item.source_type for item in result.evidence}
            checks = {
                "category": result.category == case.expected_category,
                "action": result.recommended_action == case.expected_action,
                "approval": result.requires_approval == case.expected_approval,
                "evidence": case.required_evidence_types.issubset(evidence_types),
            }
            score = sum(checks.values())
            earned += score
            status = "PASS" if score == 4 else "FAIL"
            failed = ", ".join(name for name, passed in checks.items() if not passed)
            suffix = "" if not failed else f" | missed: {failed}"
            print(
                f"{status} {case.key:24} {score}/4  {elapsed:5.2f}s  "
                f"{result.category} → {result.recommended_action} ({provider}){suffix}"
            )

    percentage = earned / possible * 100 if possible else 0
    print(f"\nTotal: {earned}/{possible} ({percentage:.1f}%)")
    if earned != possible:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
