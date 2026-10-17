"""Durable campaign queue worker with lease fencing and bounded retries."""

import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings, get_settings
from app.infrastructure.database.models import (
    Campaign,
    EmailAttempt,
    EmailJob,
    EmailSuppression,
    EmailTemplate,
)
from app.infrastructure.database.session import (
    dispose_database_engine,
    get_session_factory,
)
from app.infrastructure.email.smtp import OutboundMessage, SMTPTransport, TransportFailure
from app.logging_config import configure_logging

logger = logging.getLogger("app.worker")

JobOutcome = Literal["sent", "retry", "failed", "uncertain"]


@dataclass(frozen=True)
class ClaimedJob:
    """A queue row reserved until its lease deadline."""

    job_id: int
    lease_until: datetime


@dataclass(frozen=True)
class PreparedDelivery:
    """A started, persisted delivery attempt and its message content."""

    attempt_number: int
    message: OutboundMessage


def claim_ready_jobs(
    session: Session,
    *,
    now: datetime,
    batch_size: int,
    lease_seconds: int,
) -> list[ClaimedJob]:
    """Lock eligible rows and assign a lease in one short transaction.

    TiDB's pessimistic ``SELECT FOR UPDATE`` prevents two workers from claiming
    the same committed row. The lease timestamp also fences off stale workers.
    """

    now_utc = now.astimezone(UTC).replace(tzinfo=None)
    lease_until = now_utc + timedelta(seconds=lease_seconds)
    ready_campaign_ids = select(Campaign.id).where(
        Campaign.status.in_(("scheduled", "sending")),
        Campaign.scheduled_at.is_not(None),
        Campaign.scheduled_at <= now_utc,
    )
    eligible_job_state = or_(
        and_(EmailJob.status == "pending", EmailJob.available_at <= now_utc),
        and_(EmailJob.status == "processing", EmailJob.locked_until <= now_utc),
    )
    rows = session.execute(
        select(EmailJob.id, EmailJob.campaign_id, EmailJob.status)
        .where(
            EmailJob.campaign_id.in_(ready_campaign_ids),
            eligible_job_state,
        )
        .order_by(EmailJob.available_at, EmailJob.id)
        .limit(batch_size)
        .with_for_update()
    ).all()
    if not rows:
        session.rollback()
        return []

    expired_ids = [int(row.id) for row in rows if row.status == "processing"]
    uncertain_ids: set[int] = set()
    if expired_ids:
        uncertain_ids = set(
            session.scalars(
                select(EmailAttempt.job_id).where(
                    EmailAttempt.job_id.in_(expired_ids),
                    EmailAttempt.outcome == "started",
                    EmailAttempt.finished_at.is_(None),
                )
            ).all()
        )
    if uncertain_ids:
        session.execute(
            update(EmailAttempt)
            .where(
                EmailAttempt.job_id.in_(uncertain_ids),
                EmailAttempt.outcome == "started",
                EmailAttempt.finished_at.is_(None),
            )
            .values(
                outcome="uncertain",
                error_code="worker_lease_expired",
                finished_at=now_utc,
            )
        )
        session.execute(
            update(EmailJob)
            .where(EmailJob.id.in_(uncertain_ids))
            .values(
                status="uncertain",
                locked_until=None,
                last_error_code="worker_lease_expired_delivery_uncertain",
            )
        )

    job_ids = [int(row.id) for row in rows if int(row.id) not in uncertain_ids]
    campaign_ids = {int(row.campaign_id) for row in rows}
    if not job_ids:
        for campaign_id in campaign_ids:
            _refresh_campaign_status(session, campaign_id)
        session.commit()
        return []

    session.execute(
        update(EmailJob)
        .where(EmailJob.id.in_(job_ids))
        .values(status="processing", locked_until=lease_until)
    )
    session.execute(
        update(Campaign)
        .where(Campaign.id.in_(campaign_ids), Campaign.status == "scheduled")
        .values(status="sending")
    )
    for campaign_id in campaign_ids:
        _refresh_campaign_status(session, campaign_id)
    session.commit()
    return [ClaimedJob(job_id=job_id, lease_until=lease_until) for job_id in job_ids]


def prepare_delivery(
    factory: sessionmaker[Session], claimed: ClaimedJob
) -> PreparedDelivery | None:
    """Recheck suppression, load the template, and persist the attempt before SMTP."""

    with factory() as session:
        job = session.scalar(
            select(EmailJob)
            .where(
                EmailJob.id == claimed.job_id,
                EmailJob.status == "processing",
                EmailJob.locked_until == claimed.lease_until,
            )
            .with_for_update()
        )
        if job is None:
            session.rollback()
            return None

        suppressed = session.scalar(
            select(EmailSuppression.id).where(
                EmailSuppression.email_normalized == job.recipient_email_normalized
            )
        )
        if suppressed is not None:
            job.status = "suppressed"
            job.locked_until = None
            job.last_error_code = "suppressed_before_delivery"
            _refresh_campaign_status(session, job.campaign_id)
            session.commit()
            logger.info("job_suppressed_before_delivery id=%s", job.id)
            return None

        campaign = session.get(Campaign, job.campaign_id)
        template = (
            session.get(EmailTemplate, campaign.template_id)
            if campaign is not None and campaign.template_id is not None
            else None
        )
        if template is None:
            job.status = "failed"
            job.locked_until = None
            job.last_error_code = "campaign_template_unavailable"
            _refresh_campaign_status(session, job.campaign_id)
            session.commit()
            logger.error("job_failed_missing_template id=%s", job.id)
            return None

        attempt_number = job.attempt_count + 1
        job.attempt_count = attempt_number
        session.add(
            EmailAttempt(
                job_id=job.id,
                attempt_number=attempt_number,
                outcome="started",
            )
        )
        delivery = PreparedDelivery(
            attempt_number=attempt_number,
            message=OutboundMessage(
                recipient=job.recipient_email,
                subject=template.subject,
                body_text=template.body_text,
                body_html=template.body_html,
            ),
        )
        session.commit()
        return delivery


def finish_delivery(
    factory: sessionmaker[Session],
    claimed: ClaimedJob,
    delivery: PreparedDelivery,
    *,
    outcome: JobOutcome,
    settings: Settings,
    error_code: str | None = None,
    response_code: str | None = None,
) -> bool:
    """Persist a delivery result only while this worker still owns the lease."""

    now = datetime.now(UTC).replace(tzinfo=None)
    with factory() as session:
        job = session.scalar(
            select(EmailJob)
            .where(
                EmailJob.id == claimed.job_id,
                EmailJob.status == "processing",
                EmailJob.locked_until == claimed.lease_until,
            )
            .with_for_update()
        )
        if job is None:
            session.rollback()
            return False

        attempt = session.scalar(
            select(EmailAttempt).where(
                EmailAttempt.job_id == job.id,
                EmailAttempt.attempt_number == delivery.attempt_number,
                EmailAttempt.outcome == "started",
                EmailAttempt.finished_at.is_(None),
            )
        )
        if attempt is None:
            session.rollback()
            return False

        if outcome == "retry" and delivery.attempt_number >= settings.worker_max_attempts:
            outcome = "failed"
            error_code = "smtp_retry_limit_reached"

        if outcome == "sent":
            job.status = "sent"
            job.sent_at = now
            job.provider_message_id = None
            job.last_error_code = None
            attempt.outcome = "sent"
        elif outcome == "retry":
            job.status = "pending"
            job.available_at = now + timedelta(
                seconds=_retry_delay(delivery.attempt_number, settings)
            )
            job.last_error_code = error_code
            attempt.outcome = "retryable_failure"
        elif outcome == "failed":
            job.status = "failed"
            job.last_error_code = error_code or "delivery_failed"
            attempt.outcome = "permanent_failure"
        else:
            job.status = "uncertain"
            job.last_error_code = error_code or "delivery_outcome_uncertain"
            attempt.outcome = "uncertain"

        job.locked_until = None
        attempt.error_code = error_code
        attempt.smtp_response_code = response_code
        attempt.finished_at = now
        _refresh_campaign_status(session, job.campaign_id)
        session.commit()
        return True


def _retry_delay(attempt_number: int, settings: Settings) -> int:
    exponent = min(max(attempt_number - 1, 0), 30)
    return min(
        settings.worker_retry_base_seconds * (2**exponent),
        settings.worker_retry_max_seconds,
    )


def _refresh_campaign_status(session: Session, campaign_id: int) -> None:
    campaign = session.scalar(
        select(Campaign).where(Campaign.id == campaign_id).with_for_update()
    )
    if campaign is None or campaign.status not in ("scheduled", "sending"):
        return

    active_count = session.scalar(
        select(func.count())
        .select_from(EmailJob)
        .where(
            EmailJob.campaign_id == campaign_id,
            EmailJob.status.in_(("pending", "processing")),
        )
    )
    if active_count:
        return

    issue_count = session.scalar(
        select(func.count())
        .select_from(EmailJob)
        .where(
            EmailJob.campaign_id == campaign_id,
            EmailJob.status.in_(("failed", "uncertain")),
        )
    )
    campaign.status = "completed_with_issues" if issue_count else "completed"


def process_claimed_job(
    factory: sessionmaker[Session],
    transport: SMTPTransport,
    claimed: ClaimedJob,
    settings: Settings,
) -> None:
    delivery = prepare_delivery(factory, claimed)
    if delivery is None:
        return

    try:
        transport.send(delivery.message)
    except TransportFailure as exc:
        outcome = exc.outcome
        stored_error_code = exc.error_code
        response_code = exc.response_code
    except Exception as exc:
        # Unknown failures after the transport call starts may follow server acceptance.
        outcome = "uncertain"
        stored_error_code = "worker_unexpected_transport_error"
        response_code = None
        logger.error(
            "job_transport_error id=%s exception_type=%s",
            claimed.job_id,
            type(exc).__name__,
        )
    else:
        outcome = "sent"
        stored_error_code = None
        response_code = None

    if outcome == "retry" and delivery.attempt_number >= settings.worker_max_attempts:
        outcome = "failed"
        stored_error_code = "smtp_retry_limit_reached"

    completed = finish_delivery(
        factory,
        claimed,
        delivery,
        outcome=outcome,
        settings=settings,
        error_code=stored_error_code,
        response_code=response_code,
    )
    if completed:
        logger.info("job_finished id=%s outcome=%s", claimed.job_id, outcome)
    else:
        logger.warning("job_result_ignored_stale_lease id=%s", claimed.job_id)


def run_worker(*, once: bool = False) -> None:
    """Run one batch or continuously poll the durable queue."""

    settings = get_settings()
    configure_logging(settings.log_level)
    if not settings.database_configured:
        raise RuntimeError("Configure o TiDB antes de iniciar o worker.")
    if not settings.smtp_configured:
        raise RuntimeError("Configure o SMTP e o endereço remetente antes de iniciar o worker.")

    transport = SMTPTransport(settings)
    try:
        transport.verify_connection()
    except TransportFailure as exc:
        logger.error("worker_smtp_preflight_failed code=%s", exc.error_code)
        raise RuntimeError(
            "A verificação de conexão SMTP falhou; nenhum job foi reservado."
        ) from None

    factory = get_session_factory()
    logger.info(
        "worker_started mode=%s batch_size=%s",
        "once" if once else "continuous",
        settings.worker_batch_size,
    )
    try:
        while True:
            now = datetime.now(UTC)
            try:
                with factory() as session:
                    claimed_jobs = claim_ready_jobs(
                        session,
                        now=now,
                        batch_size=settings.worker_batch_size,
                        lease_seconds=settings.worker_lease_seconds,
                    )
            except SQLAlchemyError as exc:
                logger.error("worker_queue_error exception_type=%s", type(exc).__name__)
                if once:
                    raise RuntimeError("Não foi possível acessar a fila no TiDB.") from None
                time.sleep(settings.worker_poll_interval_seconds)
                continue

            for claimed in claimed_jobs:
                try:
                    process_claimed_job(factory, transport, claimed, settings)
                except SQLAlchemyError as exc:
                    logger.error(
                        "worker_job_persistence_error id=%s exception_type=%s",
                        claimed.job_id,
                        type(exc).__name__,
                    )

            if once:
                logger.info("worker_batch_finished claimed=%s", len(claimed_jobs))
                break
            if not claimed_jobs:
                time.sleep(settings.worker_poll_interval_seconds)
    finally:
        dispose_database_engine()
