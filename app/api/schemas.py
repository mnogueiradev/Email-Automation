"""Validated request and response schemas for local campaign management."""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class ContactCreate(BaseModel):
    email: EmailStr
    display_name: str | None = Field(default=None, max_length=200)
    organization: str | None = Field(default=None, max_length=200)
    role_title: str | None = Field(default=None, max_length=200)


class ContactUpdate(BaseModel):
    email: EmailStr | None = None
    display_name: str | None = Field(default=None, max_length=200)
    organization: str | None = Field(default=None, max_length=200)
    role_title: str | None = Field(default=None, max_length=200)
    status: Literal["active", "inactive"] | None = None


class ContactRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    display_name: str | None
    organization: str | None
    role_title: str | None
    status: str
    created_at: datetime
    updated_at: datetime


class SuppressionCreate(BaseModel):
    email: EmailStr
    reason: Literal["unsubscribe", "bounce", "complaint", "manual"]
    source: str | None = Field(default=None, max_length=80)


class SuppressionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email_normalized: EmailStr
    reason: str
    source: str | None
    created_at: datetime


class EmailTemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    subject: str = Field(min_length=1, max_length=998)
    body_text: str = Field(min_length=1)
    body_html: str | None = None

    @field_validator("name", "subject")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("O campo não pode ficar vazio.")
        if "\r" in normalized or "\n" in normalized:
            raise ValueError("O campo não pode conter quebras de linha.")
        return normalized

    @field_validator("body_text")
    @classmethod
    def require_nonempty_text_body(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("O corpo em texto não pode ficar vazio.")
        return normalized


class EmailTemplateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    subject: str
    body_text: str
    body_html: str | None
    created_at: datetime
    updated_at: datetime


class CampaignCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    template_id: int

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("O nome não pode ficar vazio.")
        return normalized


class CampaignRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    template_id: int | None
    status: str
    scheduled_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CampaignJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    campaign_id: int
    recipient_email: EmailStr
    status: str
    attempt_count: int
    available_at: datetime
    locked_until: datetime | None
    sent_at: datetime | None
    last_error_code: str | None
    created_at: datetime
    updated_at: datetime


class CampaignRecipientsCreate(BaseModel):
    contact_ids: list[int] = Field(min_length=1, max_length=500)


class CampaignRecipientsResult(BaseModel):
    campaign_id: int
    created: int
    skipped_inactive: int
    skipped_suppressed: int
    skipped_already_queued: int


class CampaignSchedule(BaseModel):
    scheduled_at: datetime | None = None

    @field_validator("scheduled_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("Use uma data com fuso horário, por exemplo UTC.")
        if value is not None:
            return value.astimezone(UTC)
        return value
