"""Verified TLS SMTP transport for outbound campaign messages."""

import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr
from typing import Literal

from app.config import Settings


@dataclass(frozen=True)
class OutboundAttachment:
    """Binary attachment to include without interpreting its file type."""

    filename: str
    content_type: str
    content: bytes


@dataclass(frozen=True)
class OutboundMessage:
    """Rendered email data needed by a transport."""

    recipient: str
    subject: str
    body_text: str
    body_html: str | None
    attachments: tuple[OutboundAttachment, ...] = ()


class TransportFailure(Exception):
    """A sanitized SMTP outcome suitable for queue policy decisions."""

    def __init__(
        self,
        outcome: Literal["retry", "failed", "uncertain"],
        error_code: str,
        response_code: str | None = None,
    ) -> None:
        super().__init__(error_code)
        self.outcome = outcome
        self.error_code = error_code
        self.response_code = response_code


class SMTPTransport:
    """Send one message using STARTTLS or implicit TLS with certificate checks."""

    def __init__(self, settings: Settings) -> None:
        if not settings.smtp_configured:
            raise ValueError("A configuração SMTP está incompleta.")
        assert settings.smtp_host is not None
        assert settings.smtp_from_address is not None

        self.host = settings.smtp_host
        self.port = settings.smtp_port
        self.username = settings.smtp_username
        self.password = settings.smtp_password
        self.from_address = str(settings.smtp_from_address)
        self.from_name = settings.smtp_from_name
        self.security = settings.smtp_security
        self.timeout_seconds = settings.smtp_timeout_seconds

    def verify_connection(self) -> None:
        """Verify DNS, TLS, and optional authentication without sending a message."""

        context = ssl.create_default_context()
        try:
            if self.security == "ssl":
                with smtplib.SMTP_SSL(
                    self.host,
                    self.port,
                    timeout=self.timeout_seconds,
                    context=context,
                ) as server:
                    self._authenticate(server)
            else:
                with smtplib.SMTP(self.host, self.port, timeout=self.timeout_seconds) as server:
                    server.ehlo()
                    server.starttls(context=context)
                    server.ehlo()
                    self._authenticate(server)
        except smtplib.SMTPResponseException as exc:
            outcome: Literal["retry", "failed"] = (
                "retry" if 400 <= exc.smtp_code < 500 else "failed"
            )
            raise TransportFailure(outcome, "smtp_preflight_response", str(exc.smtp_code)) from None
        except (OSError, smtplib.SMTPException):
            raise TransportFailure("retry", "smtp_preflight_connection_failed") from None

    def send(self, outbound: OutboundMessage) -> None:
        """Submit one recipient and classify protocol replies without retaining raw text."""

        try:
            message = self._build_message(outbound)
        except (TypeError, ValueError):
            raise TransportFailure("failed", "message_content_invalid") from None
        context = ssl.create_default_context()
        try:
            if self.security == "ssl":
                with smtplib.SMTP_SSL(
                    self.host,
                    self.port,
                    timeout=self.timeout_seconds,
                    context=context,
                ) as server:
                    self._authenticate(server)
                    self._submit(server, message, outbound.recipient)
            else:
                with smtplib.SMTP(self.host, self.port, timeout=self.timeout_seconds) as server:
                    server.ehlo()
                    server.starttls(context=context)
                    server.ehlo()
                    self._authenticate(server)
                    self._submit(server, message, outbound.recipient)
        except TransportFailure:
            raise
        except smtplib.SMTPResponseException as exc:
            code = str(exc.smtp_code)
            outcome: Literal["retry", "failed", "uncertain"]
            if 400 <= exc.smtp_code < 500:
                outcome = "retry"
            elif 500 <= exc.smtp_code < 600:
                outcome = "failed"
            else:
                outcome = "uncertain"
            if outcome == "uncertain":
                error_code = "smtp_unrecognized_response"
            else:
                error_code = (
                    "smtp_transient_response"
                    if outcome == "retry"
                    else "smtp_permanent_response"
                )
            raise TransportFailure(outcome, error_code, code) from None
        except smtplib.SMTPServerDisconnected:
            raise TransportFailure("uncertain", "smtp_connection_lost") from None
        except OSError:
            # A socket failure can happen after the server accepted DATA but before the
            # client received the final reply. Do not retry automatically in that case.
            raise TransportFailure("uncertain", "smtp_delivery_uncertain") from None
        except smtplib.SMTPException:
            raise TransportFailure("uncertain", "smtp_protocol_error") from None

    def _build_message(self, outbound: OutboundMessage) -> EmailMessage:
        message = EmailMessage()
        message["From"] = formataddr((self.from_name or "", self.from_address))
        message["To"] = outbound.recipient
        message["Subject"] = outbound.subject
        message.set_content(outbound.body_text)
        if outbound.body_html is not None:
            message.add_alternative(outbound.body_html, subtype="html")
        for attachment in outbound.attachments:
            maintype, separator, subtype = attachment.content_type.partition("/")
            if not separator or not maintype or not subtype:
                maintype, subtype = "application", "octet-stream"
            subtype = subtype.split(";", 1)[0].strip() or "octet-stream"
            message.add_attachment(
                attachment.content,
                maintype=maintype,
                subtype=subtype,
                filename=attachment.filename,
            )
        return message

    def _authenticate(self, server: smtplib.SMTP) -> None:
        if self.username is not None and self.password is not None:
            server.login(self.username, self.password.get_secret_value())

    @staticmethod
    def _submit(server: smtplib.SMTP, message: EmailMessage, recipient: str) -> None:
        refused = server.send_message(message, to_addrs=[recipient])
        if not refused:
            return

        response = refused.get(recipient)
        if response is None:
            raise TransportFailure("uncertain", "smtp_recipient_rejected")
        code, _ = response
        outcome: Literal["retry", "failed"] = "retry" if 400 <= code < 500 else "failed"
        if code < 400 or code >= 600:
            raise TransportFailure("uncertain", "smtp_unrecognized_recipient_response", str(code))
        error_code = (
            "smtp_transient_recipient_response"
            if outcome == "retry"
            else "smtp_permanent_recipient_response"
        )
        raise TransportFailure(outcome, error_code, str(code))
