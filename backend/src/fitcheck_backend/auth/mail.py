from typing import Protocol
import logging
import smtplib
import ssl
from email.message import EmailMessage
from .types import MailMessage
from .crypto import TOKEN_PATTERN
from ..contracts.resources import normalize_email

logger = logging.getLogger('fitcheck.auth.mail')


class MailDeliveryError(Exception):
    def __init__(self):
        super().__init__('Email delivery failed')


class MailSender(Protocol):
    def available(self) -> bool: ...
    def send(self, message: MailMessage) -> None: ...


class SMTPMailer:
    def __init__(self, settings):
        self._settings = settings

    def available(self) -> bool:
        return self._settings.smtp_host is not None and self._settings.auth_web_base_url is not None

    def send(self, message: MailMessage) -> None:
        if not self.available() or any(c in message.recipient for c in '\r\n') or not TOKEN_PATTERN.fullmatch(message.token):
            raise MailDeliveryError()
        try:
            recipient = normalize_email(message.recipient)
        except ValueError:
            raise MailDeliveryError() from None
        settings = self._settings
        titles = {'verify_email': ('Confirm your FitCheck email', 'verify-email'),
                  'reset_password': ('Reset your FitCheck password', 'password-reset')}
        if message.purpose not in titles:
            raise MailDeliveryError()
        subject, path = titles[message.purpose]
        email = EmailMessage()
        email['From'], email['To'], email['Subject'] = settings.smtp_from, recipient, subject
        email.set_content(f'{subject}\n\n{settings.auth_web_base_url}/auth/{path}#token={message.token}\n\nIf you did not request this, ignore this message.\n')
        context = ssl.create_default_context()
        try:
            if settings.smtp_security == 'smtps':
                connection = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=10, context=context)
            else:
                connection = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10)
            with connection as smtp:
                if settings.smtp_security == 'starttls':
                    smtp.starttls(context=context)
                smtp.login(settings.smtp_username, settings.smtp_password.get_secret_value())
                refused = smtp.send_message(email)
                if refused:
                    raise MailDeliveryError()
        except (smtplib.SMTPException, OSError):
            logger.warning('email_delivery_failed purpose=%s', message.purpose)
            raise MailDeliveryError() from None
