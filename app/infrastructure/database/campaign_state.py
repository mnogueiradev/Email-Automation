"""Transactional campaign lifecycle updates shared by API and worker."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.infrastructure.database.models import Campaign, EmailJob


def refresh_campaign_status(session: Session, campaign_id: int) -> None:
    """Recalculate terminal campaign state after a job transition."""

    campaign = session.scalar(
        select(Campaign).where(Campaign.id == campaign_id).with_for_update()
    )
    if campaign is None or campaign.status not in (
        "scheduled",
        "sending",
        "completed",
        "completed_with_issues",
    ):
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
