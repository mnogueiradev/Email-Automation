"""Contact and suppression endpoints for the local administrative API."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies import require_api_token
from app.api.schemas import (
    ContactCreate,
    ContactRead,
    ContactUpdate,
    SuppressionCreate,
    SuppressionRead,
)
from app.domain.email import normalize_email
from app.infrastructure.database.models import Contact, EmailSuppression
from app.infrastructure.database.session import get_database_session

router = APIRouter(
    prefix="/api/v1",
    tags=["contacts"],
    dependencies=[Depends(require_api_token)],
)
DatabaseSession = Annotated[Session, Depends(get_database_session)]


@router.post("/contacts", response_model=ContactRead, status_code=status.HTTP_201_CREATED)
def create_contact(payload: ContactCreate, session: DatabaseSession) -> Contact:
    """Create a contact; email addresses are unique after normalization."""

    contact = Contact(
        email=str(payload.email),
        email_normalized=normalize_email(str(payload.email)),
        display_name=payload.display_name,
        organization=payload.organization,
        role_title=payload.role_title,
    )
    session.add(contact)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Já existe um contato com esse endereço.",
        ) from exc
    session.refresh(contact)
    return contact


@router.get("/contacts", response_model=list[ContactRead])
def list_contacts(
    session: DatabaseSession,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[Contact]:
    """List contacts in stable ID order with bounded pagination."""

    statement = select(Contact).order_by(Contact.id).offset(offset).limit(limit)
    return list(session.scalars(statement).all())


@router.get("/contacts/{contact_id}", response_model=ContactRead)
def get_contact(contact_id: int, session: DatabaseSession) -> Contact:
    """Read one contact by its internal identifier."""

    contact = session.get(Contact, contact_id)
    if contact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contato não encontrado.")
    return contact


@router.patch("/contacts/{contact_id}", response_model=ContactRead)
def update_contact(
    contact_id: int,
    payload: ContactUpdate,
    session: DatabaseSession,
) -> Contact:
    """Update contact details or deactivate a contact without deleting history."""

    contact = session.get(Contact, contact_id)
    if contact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contato não encontrado.")

    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Nenhuma alteração informada.",
        )
    if "email" in updates:
        if updates["email"] is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="O e-mail não pode ser nulo.",
            )
        updates["email"] = str(updates["email"])
        updates["email_normalized"] = normalize_email(updates["email"])
    if "status" in updates and updates["status"] is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="O status não pode ser nulo.",
        )

    for field, value in updates.items():
        setattr(contact, field, value)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Já existe um contato com esse endereço.",
        ) from exc
    session.refresh(contact)
    return contact


@router.post("/suppressions", response_model=SuppressionRead, status_code=status.HTTP_201_CREATED)
def create_suppression(payload: SuppressionCreate, session: DatabaseSession) -> EmailSuppression:
    """Prevent future jobs from being enqueued to an address."""

    suppression = EmailSuppression(
        email_normalized=normalize_email(str(payload.email)),
        reason=payload.reason,
        source=payload.source,
    )
    session.add(suppression)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Esse endereço já está na lista de supressão.",
        ) from exc
    session.refresh(suppression)
    return suppression
