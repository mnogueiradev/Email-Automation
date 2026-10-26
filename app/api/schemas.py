"""Validated request and response schemas for local campaign management."""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator


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
    subject: str = Field(min_length=1, max_length=998)
    template_id: int | None = None

    @field_validator("name", "subject")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("O campo não pode ficar vazio.")
        if "\r" in normalized or "\n" in normalized:
            raise ValueError("O campo não pode conter quebras de linha.")
        return normalized


class CampaignUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    subject: str | None = Field(default=None, min_length=1, max_length=998)
    template_id: int | None = None

    @field_validator("name", "subject")
    @classmethod
    def strip_name(cls, value: str | None) -> str | None:
        if value is None:
            return value
        normalized = value.strip()
        if not normalized:
            raise ValueError("O nome não pode ficar vazio.")
        return normalized


class CampaignRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    subject: str | None
    template_id: int | None
    status: str
    scheduled_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CampaignAttachmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    campaign_id: int
    filename: str
    content_type: str
    size_bytes: int
    created_at: datetime


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


class CampaignJobAttemptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_id: int
    attempt_number: int
    outcome: str
    smtp_response_code: str | None
    error_code: str | None
    started_at: datetime
    finished_at: datetime | None


class CampaignJobEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_id: int
    event_type: str
    previous_status: str
    new_status: str
    actor: str
    duplicate_risk_acknowledged: bool
    note: str
    created_at: datetime


class CampaignJobResolution(BaseModel):
    action: Literal["mark_sent", "mark_failed", "retry"]
    note: str = Field(min_length=1, max_length=500)
    acknowledge_duplicate_risk: bool = False

    @field_validator("note")
    @classmethod
    def strip_resolution_note(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Informe uma justificativa para a resolução manual.")
        return normalized

    @model_validator(mode="after")
    def acknowledge_retry_risk(self) -> "CampaignJobResolution":
        if self.action == "retry" and not self.acknowledge_duplicate_risk:
            raise ValueError(
                "Uma retentativa manual pode duplicar um e-mail; confirme acknowledge_duplicate_risk."
            )
        if self.action != "retry" and self.acknowledge_duplicate_risk:
            raise ValueError("A confirmação de risco só se aplica a uma retentativa.")
        return self


class CampaignRecipientsCreate(BaseModel):
    contact_ids: list[int] = Field(min_length=1, max_length=500)


class CampaignRecipientsResult(BaseModel):
    campaign_id: int
    created: int
    removed: int = 0
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
