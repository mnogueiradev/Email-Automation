"""Immutable-at-the-API-level email template endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies import require_api_token
from app.api.schemas import EmailTemplateCreate, EmailTemplateRead
from app.infrastructure.database.models import EmailTemplate
from app.infrastructure.database.session import get_database_session

router = APIRouter(
    prefix="/api/v1/templates",
    tags=["templates"],
    dependencies=[Depends(require_api_token)],
)
DatabaseSession = Annotated[Session, Depends(get_database_session)]


@router.post("", response_model=EmailTemplateRead, status_code=status.HTTP_201_CREATED)
def create_template(payload: EmailTemplateCreate, session: DatabaseSession) -> EmailTemplate:
    """Create a reusable template. No endpoint edits it after creation."""

    template = EmailTemplate(
        name=payload.name,
        subject=payload.subject,
        body_text=payload.body_text,
        body_html=payload.body_html,
    )
    session.add(template)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Já existe um template com esse nome.",
        ) from exc
    session.refresh(template)
    return template


@router.get("", response_model=list[EmailTemplateRead])
def list_templates(
    session: DatabaseSession,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[EmailTemplate]:
    """List templates in stable ID order with bounded pagination."""

    statement = select(EmailTemplate).order_by(EmailTemplate.id).offset(offset).limit(limit)
    return list(session.scalars(statement).all())


@router.get("/{template_id}", response_model=EmailTemplateRead)
def get_template(template_id: int, session: DatabaseSession) -> EmailTemplate:
    """Read one template by its internal identifier."""

    template = session.get(EmailTemplate, template_id)
    if template is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Template não encontrado.",
        )
    return template
