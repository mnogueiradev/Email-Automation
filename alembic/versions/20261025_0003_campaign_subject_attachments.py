"""Add campaign subjects and binary attachments.

Revision ID: 20261025_0003
Revises: 20261017_0002
Create Date: 2026-10-25
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision: str = "20261025_0003"
down_revision: str | None = "20261017_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("campaigns", sa.Column("subject", sa.String(length=998), nullable=True))
    op.create_table(
        "campaign_attachments",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("campaign_id", sa.BigInteger(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=255), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("content", mysql.LONGBLOB(), nullable=False),
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
            ["campaign_id"],
            ["campaigns.id"],
            name="fk_campaign_attachments_campaign_id_campaigns",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_campaign_attachments"),
    )
    op.create_index(
        "ix_campaign_attachments_campaign_id",
        "campaign_attachments",
        ["campaign_id"],
    )


def downgrade() -> None:
    raise RuntimeError("Esta migração não tem downgrade automático para preservar os anexos.")
