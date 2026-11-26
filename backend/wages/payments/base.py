"""Payment provider interface.

Hard rule: money moves directly from the business's wallet to the worker's wallet.
Wathb never receives, holds or forwards funds; a provider only *initiates* a transfer
that the payer authorises with a one-time code the provider sends to the payer.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass


class PaymentError(Exception):
    """A definite answer from the provider: the transfer did not (or cannot) happen."""
    WRONG_CODE = "WRONG_CODE"
    CODE_EXPIRED = "CODE_EXPIRED"
    INSUFFICIENT_BALANCE = "INSUFFICIENT_BALANCE"
    RECIPIENT_NO_WALLET = "RECIPIENT_NO_WALLET"

    def __init__(self, code):
        super().__init__(code)
        self.code = code


class ProviderTimeout(Exception):
    """No answer: the transfer may or may not have happened. Ask get_status before retrying."""


@dataclass(frozen=True)
class TransferRequest:
    idempotency_key: str   # tied to the wage obligation; the same key never moves money twice
    amount: int            # integer agorot, from the wage's agreed terms only
    currency: str
    payer_wallet: str      # the business's linked wallet (E.164)
    payee_wallet: str      # the worker's registered phone (E.164)


@dataclass(frozen=True)
class TransferStatus:
    PENDING_CODE = "PENDING_CODE"   # waiting for the payer's code
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"

    state: str
    reference: str | None = None
    failure: str | None = None


class PaymentProvider(ABC):
    name = ""
    # False until a real integration exists; then the screen falls back to manual mode.
    available = True

    @abstractmethod
    def initiate(self, request: TransferRequest) -> str:
        """Start (or, with the same key, re-send the code for) a transfer.
        The provider sends the one-time code to the payer. Returns the provider reference."""

    @abstractmethod
    def confirm(self, reference: str, code: str) -> str:
        """Relay the payer's code. Returns the final reference on success.
        The code must never be stored or logged by the caller or the provider adapter."""

    @abstractmethod
    def get_status(self, idempotency_key: str, reference: str | None) -> TransferStatus:
        """Ask what happened to a transfer, e.g. after a timeout."""

    def handle_callback(self, body: bytes, headers) -> TransferStatus | None:
        """Optional: verify and parse a provider callback."""
        raise NotImplementedError
