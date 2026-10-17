"""Create the initial email automation schema.

Revision ID: 20261013_0001
Revises:
Create Date: 2026-10-13
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision: str = "20261013_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "contacts",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column(
            "email_normalized",
            sa.String(length=320, collation="utf8mb4_bin"),
            nullable=False,
        ),
        sa.Column("display_name", sa.String(length=200), nullable=True),
        sa.Column("organization", sa.String(length=200), nullable=True),
        sa.Column("role_title", sa.String(length=200), nullable=True),
        sa.Column(
            "status", sa.String(length=24), server_default=sa.text("'active'"), nullable=False
        ),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_contacts"),
        sa.UniqueConstraint("email_normalized", name="uq_contacts_email_normalized"),
    )
    op.create_index("ix_contacts_status", "contacts", ["status"])

    op.create_table(
        "email_suppressions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "email_normalized",
            sa.String(length=320, collation="utf8mb4_bin"),
            nullable=False,
        ),
        sa.Column("reason", sa.String(length=40), nullable=False),
        sa.Column("source", sa.String(length=80), nullable=True),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_email_suppressions"),
        sa.UniqueConstraint(
            "email_normalized", name="uq_email_suppressions_email_normalized"
        ),
    )

    op.create_table(
        "email_templates",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("subject", sa.String(length=998), nullable=False),
        sa.Column("body_text", sa.Text(), nullable=False),
        sa.Column("body_html", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_email_templates"),
        sa.UniqueConstraint("name", name="uq_email_templates_name"),
    )

    op.create_table(
        "campaigns",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("template_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "status", sa.String(length=24), server_default=sa.text("'draft'"), nullable=False
        ),
        sa.Column("scheduled_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["template_id"],
            ["email_templates.id"],
            name="fk_campaigns_template_id_email_templates",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_campaigns"),
    )
    op.create_index(
        "ix_campaigns_status_scheduled_at", "campaigns", ["status", "scheduled_at"]
    )

    op.create_table(
        "email_jobs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("campaign_id", sa.BigInteger(), nullable=False),
        sa.Column("contact_id", sa.BigInteger(), nullable=True),
        sa.Column("recipient_email", sa.String(length=320), nullable=False),
        sa.Column(
            "recipient_email_normalized",
            sa.String(length=320, collation="utf8mb4_bin"),
            nullable=False,
        ),
        sa.Column(
            "status", sa.String(length=24), server_default=sa.text("'pending'"), nullable=False
        ),
        sa.Column("attempt_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "available_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.Column("locked_until", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("provider_message_id", sa.String(length=255), nullable=True),
        sa.Column("last_error_code", sa.String(length=120), nullable=True),
        sa.Column("sent_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id"], ["campaigns.id"], name="fk_email_jobs_campaign_id_campaigns"
        ),
        sa.ForeignKeyConstraint(
            ["contact_id"], ["contacts.id"], name="fk_email_jobs_contact_id_contacts"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_email_jobs"),
        sa.UniqueConstraint(
            "campaign_id", "recipient_email_normalized", name="uq_email_jobs_campaign_recipient"
        ),
    )
    op.create_index(
        "ix_email_jobs_queue",
        "email_jobs",
        ["status", "available_at", "locked_until", "id"],
    )
    op.create_index("ix_email_jobs_contact_id", "email_jobs", ["contact_id"])

    op.create_table(
        "email_attempts",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.BigInteger(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("smtp_response_code", sa.String(length=16), nullable=True),
        sa.Column("error_code", sa.String(length=120), nullable=True),
        sa.Column(
            "started_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.Column("finished_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.ForeignKeyConstraint(
            ["job_id"], ["email_jobs.id"], name="fk_email_attempts_job_id_email_jobs"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_email_attempts"),
        sa.UniqueConstraint("job_id", "attempt_number", name="uq_email_attempts_job_number"),
    )
    op.create_index("ix_email_attempts_job_id", "email_attempts", ["job_id"])


def downgrade() -> None:
    raise RuntimeError(
        "A migração inicial não tem downgrade automático para impedir exclusão acidental de dados."
    )
