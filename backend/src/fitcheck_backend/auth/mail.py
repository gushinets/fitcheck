from typing import Protocol
from .types import MailMessage


class MailDeliveryError(Exception):
    def __init__(self):
        super().__init__('Email delivery failed')


class MailSender(Protocol):
    def available(self) -> bool: ...
    def send(self, message: MailMessage) -> None: ...
