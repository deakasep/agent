"""Pengiriman email transaksional (verifikasi email, reset password). Tanpa dependency baru: smtplib stdlib.

CLAU_MAIL_BACKEND:
- `smtp`     : kirim lewat server SMTP (CLAU_SMTP_*). Wajib di produksi bila pendaftaran mandiri dibuka.
- `file`     : tulis email ke folder CLAU_MAIL_DIR (development saja; ditolak di CLAU_ENV=production).
- `memory`   : simpan di `outbox` (test).
- `disabled` : tidak mengirim apa pun (default). Pendaftaran mandiri menolak berjalan tanpa backend kirim.

Isi email (termasuk tautan bertoken) tidak pernah ditulis ke log; log hanya mencatat tujuan yang disamarkan.
"""

from __future__ import annotations

import logging
import os
import smtplib
import ssl
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from pathlib import Path

log = logging.getLogger("clau.mail")
BACKENDS = ("smtp", "file", "memory", "disabled")


@dataclass(frozen=True)
class Mail:
    to: str
    subject: str
    body: str


outbox: list[Mail] = []


class MailError(RuntimeError):
    pass


@dataclass(frozen=True)
class MailSettings:
    backend: str
    sender: str
    sender_name: str
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    smtp_tls: str  # starttls | ssl
    directory: str
    environment: str

    @property
    def can_send(self) -> bool:
        if self.backend == "smtp":
            return bool(self.smtp_host and self.sender)
        if self.backend == "file":
            return self.environment != "production" and bool(self.directory)
        return self.backend == "memory"


def mail_settings() -> MailSettings:
    backend = (os.environ.get("CLAU_MAIL_BACKEND") or "disabled").strip().lower()
    if backend not in BACKENDS:
        backend = "disabled"
    return MailSettings(
        backend=backend,
        sender=(os.environ.get("CLAU_MAIL_FROM") or "").strip(),
        sender_name=(os.environ.get("CLAU_MAIL_FROM_NAME") or "CLAU AI").strip(),
        smtp_host=(os.environ.get("CLAU_SMTP_HOST") or "").strip(),
        smtp_port=int(os.environ.get("CLAU_SMTP_PORT") or "587"),
        smtp_user=(os.environ.get("CLAU_SMTP_USER") or "").strip(),
        smtp_password=os.environ.get("CLAU_SMTP_PASSWORD") or "",
        smtp_tls=(os.environ.get("CLAU_SMTP_TLS") or "starttls").strip().lower(),
        directory=(os.environ.get("CLAU_MAIL_DIR") or "").strip(),
        environment=os.environ.get("CLAU_ENV") or "production",
    )


def mask(email: str) -> str:
    name, _, domain = email.partition("@")
    return f"{name[:1]}***@{domain}"


def send(to: str, subject: str, body: str, settings: MailSettings | None = None) -> None:
    """Kirim satu email teks. MailError bila backend tidak siap atau server menolak."""
    s = settings or mail_settings()
    if not s.can_send:
        raise MailError("mail_backend_unavailable")
    if s.backend == "memory":
        outbox.append(Mail(to, subject, body))
        return
    msg = EmailMessage()
    msg["From"] = formataddr((s.sender_name, s.sender or "noreply@localhost"))
    msg["To"] = to
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid(domain=(s.sender.partition("@")[2] or "localhost"))
    msg.set_content(body)
    if s.backend == "file":
        folder = Path(s.directory)
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        (folder / f"{stamp}.eml").write_bytes(bytes(msg))
        log.info("mail written to file for %s", mask(to))
        return
    try:
        context = ssl.create_default_context()
        if s.smtp_tls == "ssl":
            server: smtplib.SMTP = smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, timeout=15, context=context)
        else:
            server = smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=15)
            server.starttls(context=context)
        with server:
            if s.smtp_user:
                server.login(s.smtp_user, s.smtp_password)
            server.send_message(msg)
    except (OSError, smtplib.SMTPException) as exc:
        log.warning("mail to %s failed: %s", mask(to), type(exc).__name__)
        raise MailError("mail_failed") from exc
    log.info("mail sent to %s", mask(to))
