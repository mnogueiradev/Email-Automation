"""Initial relational model for contacts, campaigns, and the send queue."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base


class TimestampMixin:
    """UTC timestamps; the database connection is configured to use UTC."""

    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6), nullable=False, server_default=text("CURRENT_TIMESTAMP(6)")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6)"),
        onupdate=func.current_timestamp(6),
    )


class Contact(TimestampMixin, Base):
    """A recipient record. Keep the original address and a normalized key."""

    __tablename__ = "contacts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    email_normalized: Mapped[str] = mapped_column(
        String(320, collation="utf8mb4_bin"), nullable=False
    )
    display_name: Mapped[str | None] = mapped_column(String(200))
    organization: Mapped[str | None] = mapped_column(String(200))
    role_title: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, server_default=text("'active'")
    )

    __table_args__ = (
        UniqueConstraint("email_normalized", name="uq_contacts_email_normalized"),
        Index("ix_contacts_status", "status"),
    )


class EmailSuppression(TimestampMixin, Base):
    """An address that must not receive future campaign email."""

    __tablename__ = "email_suppressions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    email_normalized: Mapped[str] = mapped_column(
        String(320, collation="utf8mb4_bin"), nullable=False
    )
    reason: Mapped[str] = mapped_column(String(40), nullable=False)
    source: Mapped[str | None] = mapped_column(String(80))

    __table_args__ = (
        UniqueConstraint("email_normalized", name="uq_email_suppressions_email_normalized"),
    )


class EmailTemplate(TimestampMixin, Base):
    """Reusable subject and body content for outbound email."""

    __tablename__ = "email_templates"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    subject: Mapped[str] = mapped_column(String(998), nullable=False)
    body_text: Mapped[str] = mapped_column(Text, nullable=False)
    body_html: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (UniqueConstraint("name", name="uq_email_templates_name"),)


class Campaign(TimestampMixin, Base):
    """A named batch of messages with an explicit lifecycle state."""

    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    template_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("email_templates.id", name="fk_campaigns_template_id_email_templates"),
    )
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, server_default=text("'draft'")
    )
    scheduled_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))

    __table_args__ = (Index("ix_campaigns_status_scheduled_at", "status", "scheduled_at"),)


class EmailJob(TimestampMixin, Base):
    """One recipient delivery task; address is snapshotted at enqueue time."""

    __tablename__ = "email_jobs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    campaign_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("campaigns.id", name="fk_email_jobs_campaign_id_campaigns"),
        nullable=False,
    )
    contact_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("contacts.id", name="fk_email_jobs_contact_id_contacts"),
    )
    recipient_email: Mapped[str] = mapped_column(String(320), nullable=False)
    recipient_email_normalized: Mapped[str] = mapped_column(
        String(320, collation="utf8mb4_bin"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, server_default=text("'pending'")
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    available_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6), nullable=False, server_default=text("CURRENT_TIMESTAMP(6)")
    )
    locked_until: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    provider_message_id: Mapped[str | None] = mapped_column(String(255))
    last_error_code: Mapped[str | None] = mapped_column(String(120))
    sent_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))

    __table_args__ = (
        UniqueConstraint(
            "campaign_id", "recipient_email_normalized", name="uq_email_jobs_campaign_recipient"
        ),
        Index("ix_email_jobs_queue", "status", "available_at", "locked_until", "id"),
        Index("ix_email_jobs_contact_id", "contact_id"),
    )


class EmailAttempt(Base):
    """Transport attempt metadata without storing message bodies or raw errors."""

    __tablename__ = "email_attempts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("email_jobs.id", name="fk_email_attempts_job_id_email_jobs"),
        nullable=False,
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    smtp_response_code: Mapped[str | None] = mapped_column(String(16))
    error_code: Mapped[str | None] = mapped_column(String(120))
    started_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6), nullable=False, server_default=text("CURRENT_TIMESTAMP(6)")
    )
    finished_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))

    __table_args__ = (
        UniqueConstraint("job_id", "attempt_number", name="uq_email_attempts_job_number"),
        Index("ix_email_attempts_job_id", "job_id"),
    )
