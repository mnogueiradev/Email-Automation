"""Typed application configuration with safe defaults."""

from functools import lru_cache
from ipaddress import IPv4Address, IPv6Address, ip_address
from pathlib import Path
from typing import Literal

from pydantic import EmailStr, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings loaded from environment variables or a local .env file."""

    model_config = SettingsConfigDict(
        env_prefix="CV_AUTOMATION_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: Literal["development", "test", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    api_host: IPv4Address | IPv6Address = IPv4Address("127.0.0.1")
    api_port: int = 8000
    api_token: SecretStr | None = None

    db_host: str | None = None
    db_port: int = 4000
    db_user: str | None = None
    db_password: SecretStr | None = None
    db_name: str | None = None
    db_ca_file: Path | None = None

    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_from_address: EmailStr | None = None
    smtp_from_name: str | None = None
    smtp_security: Literal["starttls", "ssl"] = "starttls"
    smtp_timeout_seconds: int = 20

    worker_batch_size: int = 10
    worker_poll_interval_seconds: float = 2.0
    worker_lease_seconds: int = 180
    worker_max_attempts: int = 5
    worker_retry_base_seconds: int = 30
    worker_retry_max_seconds: int = 3600

    @field_validator("api_host", mode="before")
    @classmethod
    def validate_api_host(cls, value: object) -> object:
        address = ip_address(value) if isinstance(value, str) else value
        if not isinstance(address, (IPv4Address, IPv6Address)) or not address.is_loopback:
            raise ValueError("A API permanece restrita a um endereço loopback nesta etapa.")
        return address

    @field_validator("api_token")
    @classmethod
    def validate_api_token(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and len(value.get_secret_value()) < 32:
            raise ValueError("O token da API deve ter pelo menos 32 caracteres.")
        return value

    @field_validator("api_port", "db_port")
    @classmethod
    def validate_port(cls, value: int) -> int:
        if not 1 <= value <= 65535:
            raise ValueError("A porta deve estar entre 1 e 65535.")
        return value

    @field_validator("smtp_port")
    @classmethod
    def validate_smtp_port(cls, value: int) -> int:
        if not 1 <= value <= 65535:
            raise ValueError("A porta SMTP deve estar entre 1 e 65535.")
        return value

    @field_validator("smtp_timeout_seconds", "worker_lease_seconds")
    @classmethod
    def validate_positive_seconds(cls, value: int) -> int:
        if value < 1:
            raise ValueError("Os tempos limite e de lease devem ser positivos.")
        return value

    @field_validator("worker_batch_size", "worker_max_attempts", "worker_retry_base_seconds")
    @classmethod
    def validate_positive_worker_values(cls, value: int) -> int:
        if value < 1:
            raise ValueError("As configurações do worker devem ser positivas.")
        return value

    @field_validator("worker_retry_max_seconds")
    @classmethod
    def validate_retry_limit(cls, value: int) -> int:
        if value < 1:
            raise ValueError("O limite de retentativa deve ser positivo.")
        return value

    @field_validator("worker_poll_interval_seconds")
    @classmethod
    def validate_poll_interval(cls, value: float) -> float:
        if not 0.1 <= value <= 60:
            raise ValueError("O intervalo do worker deve ficar entre 0.1 e 60 segundos.")
        return value

    @field_validator("db_host", "db_user", "db_name")
    @classmethod
    def normalize_database_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("Os campos de conexão do banco não podem ser vazios.")
        return normalized

    @field_validator("smtp_host", "smtp_username", "smtp_from_name", mode="before")
    @classmethod
    def normalize_optional_smtp_text(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None
        return value

    @field_validator("smtp_from_address", mode="before")
    @classmethod
    def normalize_smtp_from_address(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None
        return value

    @field_validator("smtp_password", mode="before")
    @classmethod
    def normalize_smtp_password(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def validate_database_configuration(self) -> "Settings":
        database_fields = (
            self.db_host,
            self.db_user,
            self.db_password,
            self.db_name,
            self.db_ca_file,
        )
        if any(value is not None for value in database_fields) and not all(
            value is not None for value in database_fields
        ):
            raise ValueError(
                "Configure host, usuário, senha, nome do banco e CA do TiDB em conjunto."
            )

        if self.db_password is not None and not self.db_password.get_secret_value().strip():
            raise ValueError("A senha do TiDB não pode ser vazia.")

        if self.db_ca_file is not None and not self.db_ca_file.is_file():
            raise ValueError("O arquivo CA configurado para o TiDB não existe ou não é um arquivo.")

        if (self.smtp_host is None) != (self.smtp_from_address is None):
            raise ValueError("Configure host e endereço remetente SMTP em conjunto.")

        if (self.smtp_username is None) != (self.smtp_password is None):
            raise ValueError("Configure usuário e senha SMTP em conjunto.")

        if any(
            value is not None
            for value in (self.smtp_username, self.smtp_password, self.smtp_from_name)
        ) and not self.smtp_configured:
            raise ValueError("As opções SMTP exigem host e endereço remetente.")

        if self.smtp_password is not None and not self.smtp_password.get_secret_value().strip():
            raise ValueError("A senha SMTP não pode ser vazia.")

        if self.smtp_from_name is not None and (
            len(self.smtp_from_name) > 200
            or "\r" in self.smtp_from_name
            or "\n" in self.smtp_from_name
        ):
            raise ValueError("O nome remetente SMTP é inválido ou excede 200 caracteres.")

        if self.worker_lease_seconds <= self.smtp_timeout_seconds * 2:
            raise ValueError("O lease do worker deve exceder duas vezes o timeout SMTP.")

        return self

    @property
    def database_configured(self) -> bool:
        """Return whether the full, TLS-capable database configuration is present."""

        return all(
            value is not None
            for value in (
                self.db_host,
                self.db_user,
                self.db_password,
                self.db_name,
                self.db_ca_file,
            )
        )

    @property
    def smtp_configured(self) -> bool:
        """Return whether the minimum SMTP transport configuration is present."""

        return self.smtp_host is not None and self.smtp_from_address is not None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings instance."""

    return Settings()
