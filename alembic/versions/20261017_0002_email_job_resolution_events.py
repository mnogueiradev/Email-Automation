"""Add an append-only audit table for manual queue resolutions.

Revision ID: 20261017_0002
Revises: 20261013_0001
Create Date: 2026-10-17
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision: str = "20261017_0002"
down_revision: str | None = "20261013_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "email_job_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("previous_status", sa.String(length=24), nullable=False),
        sa.Column("new_status", sa.String(length=24), nullable=False),
        sa.Column(
            "actor",
            sa.String(length=80),
            server_default=sa.text("'local_api'"),
            nullable=False,
        ),
        sa.Column(
            "duplicate_risk_acknowledged",
            sa.Boolean(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("note", sa.String(length=500), nullable=False),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["email_jobs.id"],
            name="fk_email_job_events_job_id_email_jobs",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_email_job_events"),
    )
    op.create_index(
        "ix_email_job_events_job_created",
        "email_job_events",
        ["job_id", "created_at"],
    )


def downgrade() -> None:
    raise RuntimeError(
        "Esta migração não tem downgrade automático para preservar o histórico de resoluções."
    )
