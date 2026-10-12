import smtplib
import ssl
import pytest
from fitcheck_backend.auth.mail import SMTPMailer, MailDeliveryError
from fitcheck_backend.auth.types import MailMessage
from fitcheck_backend.config import Settings


def settings(mode='starttls'):
    return Settings(auth_web_base_url='https://fitcheck.example', smtp_host='smtp.example', smtp_port=587,
        smtp_username='sender', smtp_password='mailsecret', smtp_from='sender@example.com', smtp_security=mode)


def test_smtp_requires_tls_and_rejects_header_injection(monkeypatch):
    messages = []
    events = []
    class Transport:
        def __init__(self, host, port, *, timeout):
            assert (host, port, timeout) == ('smtp.example', 587, 10)
            events.append('connect')
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def starttls(self, *, context):
            assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
            events.append('tls')
        def login(self, user, password):
            assert events == ['connect', 'tls']
            events.append('auth')
        def send_message(self, message):
            assert events[-1] == 'auth'
            messages.append(message)
    monkeypatch.setattr(smtplib, 'SMTP', Transport)
    SMTPMailer(settings()).send(MailMessage('a@example.com', 'verify_email', 'a'*43))
    assert messages[0]['To'] == 'a@example.com'
    assert messages[0]['From'] == 'sender@example.com'
    assert 'https://fitcheck.example/auth/verify-email#token='+'a'*43 in messages[0].get_content()
    with pytest.raises(MailDeliveryError):
        SMTPMailer(settings()).send(MailMessage('a@example.com\r\nBcc: evil@example.com', 'verify_email', 'a'*43))


def test_smtp_failure_does_not_expose_private_details(monkeypatch, caplog):
    class Transport:
        def __init__(self, *args, **kwargs):
            raise smtplib.SMTPDataError(550, b'private-recipient private-token mailsecret')
    monkeypatch.setattr(smtplib, 'SMTP_SSL', Transport)
    with pytest.raises(MailDeliveryError) as exc:
        SMTPMailer(settings('smtps')).send(MailMessage('a@example.com', 'reset_password', 'a'*43))
    assert str(exc.value) == 'Email delivery failed'
    assert not any(x in caplog.text for x in ['private-recipient', 'private-token', 'mailsecret', 'a@example.com'])
    assert not SMTPMailer(Settings()).available()
