"""Draft campaign creation and recipient enqueue operations."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated
from urllib.parse import unquote

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies import require_api_token
from app.api.schemas import (
    CampaignAttachmentRead,
    CampaignCreate,
    CampaignUpdate,
    CampaignJobAttemptRead,
    CampaignJobEventRead,
    CampaignJobRead,
    CampaignJobResolution,
    CampaignRead,
    CampaignRecipientsCreate,
    CampaignRecipientsResult,
    CampaignSchedule,
)
from app.domain.email import normalize_email
from app.infrastructure.database.campaign_state import refresh_campaign_status
from app.infrastructure.database.models import (
    Campaign,
    CampaignAttachment,
    Contact,
    EmailAttempt,
    EmailJob,
    EmailJobEvent,
    EmailSuppression,
    EmailTemplate,
)
from app.infrastructure.database.session import get_database_session

MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024

router = APIRouter(
    prefix="/api/v1/campaigns",
    tags=["campaigns"],
    dependencies=[Depends(require_api_token)],
)
DatabaseSession = Annotated[Session, Depends(get_database_session)]


@router.post("", response_model=CampaignRead, status_code=status.HTTP_201_CREATED)
def create_campaign(payload: CampaignCreate, session: DatabaseSession) -> Campaign:
    """Create a draft campaign using only its title and subject."""

    campaign = Campaign(
        name=payload.name,
        subject=payload.subject,
        template_id=payload.template_id,
        status="draft",
    )
    session.add(campaign)
    session.commit()
    session.refresh(campaign)
    return campaign


@router.patch("/{campaign_id}", response_model=CampaignRead)
def update_campaign(
    campaign_id: int,
    payload: CampaignUpdate,
    session: DatabaseSession,
) -> Campaign:
    """Update draft campaign metadata before it is scheduled."""

    campaign = session.scalar(
        select(Campaign).where(Campaign.id == campaign_id).with_for_update()
    )
    if campaign is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campanha não encontrada.")
    if campaign.status != "draft":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Só é possível editar uma campanha em rascunho.",
        )

    updates = payload.model_dump(exclude_unset=True)
    if "template_id" in updates and updates["template_id"] is not None:
        if session.get(EmailTemplate, updates["template_id"]) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template não encontrado.")
    for field, value in updates.items():
        setattr(campaign, field, value)
    session.commit()
    session.refresh(campaign)
    return campaign


@router.post("/{campaign_id}/attachment", response_model=CampaignAttachmentRead)
async def upload_attachment(
    campaign_id: int,
    request: Request,
    session: DatabaseSession,
) -> CampaignAttachment:
    """Replace the optional draft attachment with one arbitrary file type."""

    campaign = session.scalar(
        select(Campaign).where(Campaign.id == campaign_id).with_for_update()
    )
    if campaign is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campanha não encontrada.")
    if campaign.status != "draft":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Só é possível anexar arquivos a uma campanha em rascunho.",
        )

    filename_header = unquote(request.headers.get("x-file-name", "anexo"))
    filename = Path(filename_header.replace("\r", "").replace("\n", "")).name[:255] or "anexo"
    content = await request.body()
    if len(content) > MAX_ATTACHMENT_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="O anexo deve ter no máximo 25 MB.",
        )

    session.execute(delete(CampaignAttachment).where(CampaignAttachment.campaign_id == campaign_id))
    attachment = CampaignAttachment(
        campaign_id=campaign_id,
        filename=filename,
        content_type=(request.headers.get("content-type") or "application/octet-stream")[:255],
        size_bytes=len(content),
        content=content,
    )
    session.add(attachment)
    session.commit()
    session.refresh(attachment)
    return attachment


@router.delete("/{campaign_id}/attachment", status_code=status.HTTP_204_NO_CONTENT)
def delete_attachment(campaign_id: int, session: DatabaseSession) -> None:
    """Remove the optional attachment from a draft campaign."""

    campaign = session.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campanha não encontrada.")
    if campaign.status != "draft":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A campanha já foi enviada.")
    session.execute(delete(CampaignAttachment).where(CampaignAttachment.campaign_id == campaign_id))
    session.commit()


@router.get("/{campaign_id}/attachment", response_model=CampaignAttachmentRead)
def get_attachment(campaign_id: int, session: DatabaseSession) -> CampaignAttachment:
    """Return metadata for the optional campaign attachment."""

    attachment = session.scalar(
        select(CampaignAttachment).where(CampaignAttachment.campaign_id == campaign_id)
    )
    if attachment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Anexo não encontrado.")
    return attachment


@router.delete("/{campaign_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_campaign(campaign_id: int, session: DatabaseSession) -> None:
    """Delete a draft campaign and its not-yet-sent recipient jobs."""

    campaign = session.scalar(
        select(Campaign).where(Campaign.id == campaign_id).with_for_update()
    )
    if campaign is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campanha não encontrada.")
    if campaign.status != "draft":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Só é possível excluir uma campanha em rascunho.",
        )

    session.execute(delete(EmailJob).where(EmailJob.campaign_id == campaign_id))
    session.execute(delete(CampaignAttachment).where(CampaignAttachment.campaign_id == campaign_id))
    session.delete(campaign)
    session.commit()


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


@router.get(
    "/{campaign_id}/jobs/{job_id}/attempts",
    response_model=list[CampaignJobAttemptRead],
)
def list_job_attempts(
    campaign_id: int,
    job_id: int,
    session: DatabaseSession,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[EmailAttempt]:
    """Inspect structured attempt history without exposing raw SMTP messages."""

    job_exists = session.scalar(
        select(EmailJob.id).where(
            EmailJob.id == job_id,
            EmailJob.campaign_id == campaign_id,
        )
    )
    if job_exists is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job não encontrado.")
    statement = (
        select(EmailAttempt)
        .where(EmailAttempt.job_id == job_id)
        .order_by(EmailAttempt.attempt_number)
        .offset(offset)
        .limit(limit)
    )
    return list(session.scalars(statement).all())


@router.get(
    "/{campaign_id}/jobs/{job_id}/events",
    response_model=list[CampaignJobEventRead],
)
def list_job_events(
    campaign_id: int,
    job_id: int,
    session: DatabaseSession,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[EmailJobEvent]:
    """List immutable operator decisions for a delivery job."""

    job_exists = session.scalar(
        select(EmailJob.id).where(
            EmailJob.id == job_id,
            EmailJob.campaign_id == campaign_id,
        )
    )
    if job_exists is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job não encontrado.")
    statement = (
        select(EmailJobEvent)
        .where(EmailJobEvent.job_id == job_id)
        .order_by(EmailJobEvent.created_at, EmailJobEvent.id)
        .offset(offset)
        .limit(limit)
    )
    return list(session.scalars(statement).all())


@router.post(
    "/{campaign_id}/jobs/{job_id}/resolve",
    response_model=CampaignJobEventRead,
)
def resolve_job(
    campaign_id: int,
    job_id: int,
    payload: CampaignJobResolution,
    session: DatabaseSession,
) -> EmailJobEvent:
    """Resolve a terminal delivery state and write an audit event atomically."""

    job = session.scalar(
        select(EmailJob)
        .where(
            EmailJob.id == job_id,
            EmailJob.campaign_id == campaign_id,
        )
        .with_for_update()
    )
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job não encontrado.")
    if job.status not in ("uncertain", "failed"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Só é possível resolver jobs uncertain ou failed.",
        )

    campaign = session.scalar(
        select(Campaign).where(Campaign.id == campaign_id).with_for_update()
    )
    if campaign is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Campanha não encontrada.",
        )

    previous_status = job.status
    now = datetime.now(UTC).replace(tzinfo=None)
    if payload.action == "mark_sent":
        job.status = "sent"
        job.sent_at = now
        job.last_error_code = None
    elif payload.action == "mark_failed":
        job.status = "failed"
        job.sent_at = None
        job.last_error_code = "manual_marked_failed"
    else:
        job.status = "pending"
        job.available_at = now
        job.locked_until = None
        job.sent_at = None
        job.last_error_code = None
        campaign.status = "sending"
        campaign.scheduled_at = now

    event = EmailJobEvent(
        job_id=job.id,
        event_type=payload.action,
        previous_status=previous_status,
        new_status=job.status,
        actor="local_api",
        duplicate_risk_acknowledged=payload.acknowledge_duplicate_risk,
        note=payload.note,
    )
    session.add(event)
    refresh_campaign_status(session, campaign_id)
    session.commit()
    session.refresh(event)
    return event


@router.put("/{campaign_id}/recipients", response_model=CampaignRecipientsResult)
def replace_recipients(
    campaign_id: int,
    payload: CampaignRecipientsCreate,
    session: DatabaseSession,
) -> CampaignRecipientsResult:
    """Replace the complete recipient selection of a draft campaign."""

    campaign = session.scalar(
        select(Campaign).where(Campaign.id == campaign_id).with_for_update()
    )
    if campaign is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campanha não encontrada.")
    if campaign.status != "draft":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Só é possível editar destinatários de uma campanha em rascunho.",
        )

    requested_ids = set(payload.contact_ids)
    contacts = list(session.scalars(select(Contact).where(Contact.id.in_(requested_ids))).all())
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
    previous_count = session.scalar(
        select(func.count()).select_from(EmailJob).where(EmailJob.campaign_id == campaign_id)
    ) or 0
    session.execute(delete(EmailJob).where(EmailJob.campaign_id == campaign_id))

    jobs: list[EmailJob] = []
    skipped_inactive = 0
    skipped_suppressed = 0
    for contact in contacts:
        email_key = normalize_email(contact.email)
        if contact.status != "active":
            skipped_inactive += 1
        elif email_key in suppressed:
            skipped_suppressed += 1
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
    session.commit()
    return CampaignRecipientsResult(
        campaign_id=campaign_id,
        created=len(jobs),
        removed=int(previous_count),
        skipped_inactive=skipped_inactive,
        skipped_suppressed=skipped_suppressed,
        skipped_already_queued=0,
    )


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
    """Place a populated draft in the immediate delivery queue."""

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
