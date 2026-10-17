"""Draft campaign creation and recipient enqueue operations."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies import require_api_token
from app.api.schemas import (
    CampaignCreate,
    CampaignJobRead,
    CampaignRead,
    CampaignRecipientsCreate,
    CampaignRecipientsResult,
    CampaignSchedule,
)
from app.domain.email import normalize_email
from app.infrastructure.database.models import (
    Campaign,
    Contact,
    EmailJob,
    EmailSuppression,
    EmailTemplate,
)
from app.infrastructure.database.session import get_database_session

router = APIRouter(
    prefix="/api/v1/campaigns",
    tags=["campaigns"],
    dependencies=[Depends(require_api_token)],
)
DatabaseSession = Annotated[Session, Depends(get_database_session)]


@router.post("", response_model=CampaignRead, status_code=status.HTTP_201_CREATED)
def create_campaign(payload: CampaignCreate, session: DatabaseSession) -> Campaign:
    """Create a draft campaign using an existing template."""

    if session.get(EmailTemplate, payload.template_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Template não encontrado.",
        )
    campaign = Campaign(name=payload.name, template_id=payload.template_id, status="draft")
    session.add(campaign)
    session.commit()
    session.refresh(campaign)
    return campaign


@router.get("", response_model=list[CampaignRead])
def list_campaigns(
    session: DatabaseSession,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[Campaign]:
    """List campaigns in stable ID order with bounded pagination."""

    statement = select(Campaign).order_by(Campaign.id).offset(offset).limit(limit)
    return list(session.scalars(statement).all())


@router.get("/{campaign_id}", response_model=CampaignRead)
def get_campaign(campaign_id: int, session: DatabaseSession) -> Campaign:
    """Read one campaign by its internal identifier."""

    campaign = session.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Campanha não encontrada.",
        )
    return campaign


@router.get("/{campaign_id}/jobs", response_model=list[CampaignJobRead])
def list_campaign_jobs(
    campaign_id: int,
    session: DatabaseSession,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[EmailJob]:
    """Inspect recipient delivery states and sanitized error codes for a campaign."""

    if session.get(Campaign, campaign_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Campanha não encontrada.",
        )
    statement = (
        select(EmailJob)
        .where(EmailJob.campaign_id == campaign_id)
        .order_by(EmailJob.id)
        .offset(offset)
        .limit(limit)
    )
    return list(session.scalars(statement).all())


@router.post("/{campaign_id}/recipients", response_model=CampaignRecipientsResult)
def enqueue_recipients(
    campaign_id: int,
    payload: CampaignRecipientsCreate,
    session: DatabaseSession,
) -> CampaignRecipientsResult:
    """Create pending jobs for active, non-suppressed contacts in a draft."""

    campaign = session.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Campanha não encontrada.",
        )
    if campaign.status != "draft":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Só é possível adicionar destinatários a uma campanha em rascunho.",
        )

    requested_ids = set(payload.contact_ids)
    contacts = list(
        session.scalars(select(Contact).where(Contact.id.in_(requested_ids))).all()
    )
    found_ids = {contact.id for contact in contacts}
    missing_ids = sorted(requested_ids - found_ids)
    if missing_ids:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "Há contatos que não existem.", "contact_ids": missing_ids},
        )

    normalized_addresses = {normalize_email(contact.email) for contact in contacts}
    suppressed = set(
        session.scalars(
            select(EmailSuppression.email_normalized).where(
                EmailSuppression.email_normalized.in_(normalized_addresses)
            )
        ).all()
    )
    already_queued = set(
        session.scalars(
            select(EmailJob.recipient_email_normalized).where(
                EmailJob.campaign_id == campaign_id,
                EmailJob.recipient_email_normalized.in_(normalized_addresses),
            )
        ).all()
    )
    already_queued_contact_ids = set(
        session.scalars(
            select(EmailJob.contact_id).where(
                EmailJob.campaign_id == campaign_id,
                EmailJob.contact_id.in_(requested_ids),
            )
        ).all()
    )

    jobs: list[EmailJob] = []
    skipped_inactive = 0
    skipped_suppressed = 0
    skipped_already_queued = 0
    for contact in contacts:
        email_key = normalize_email(contact.email)
        if contact.status != "active":
            skipped_inactive += 1
        elif email_key in suppressed:
            skipped_suppressed += 1
        elif email_key in already_queued or contact.id in already_queued_contact_ids:
            skipped_already_queued += 1
        else:
            jobs.append(
                EmailJob(
                    campaign_id=campaign_id,
                    contact_id=contact.id,
                    recipient_email=contact.email,
                    recipient_email_normalized=email_key,
                    status="pending",
                )
            )

    session.add_all(jobs)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A lista de destinatários mudou em paralelo; tente novamente.",
        ) from exc
    return CampaignRecipientsResult(
        campaign_id=campaign_id,
        created=len(jobs),
        skipped_inactive=skipped_inactive,
        skipped_suppressed=skipped_suppressed,
        skipped_already_queued=skipped_already_queued,
    )


@router.post("/{campaign_id}/schedule", response_model=CampaignRead)
def schedule_campaign(
    campaign_id: int,
    payload: CampaignSchedule,
    session: DatabaseSession,
) -> Campaign:
    """Mark a populated draft as scheduled; this does not send email by itself."""

    campaign = session.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Campanha não encontrada.",
        )
    if campaign.status != "draft":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Só é possível agendar uma campanha em rascunho.",
        )
    if campaign.template_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A campanha precisa de um template antes do agendamento.",
        )

    job_count = session.scalar(
        select(func.count()).select_from(EmailJob).where(EmailJob.campaign_id == campaign_id)
    )
    if not job_count:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Adicione pelo menos um destinatário antes do agendamento.",
        )

    scheduled_at = payload.scheduled_at or datetime.now(UTC)
    now = datetime.now(UTC)
    if scheduled_at < now:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A data de agendamento precisa ser atual ou futura.",
        )
    campaign.scheduled_at = scheduled_at.astimezone(UTC).replace(tzinfo=None)
    campaign.status = "scheduled"
    session.commit()
    session.refresh(campaign)
    return campaign
