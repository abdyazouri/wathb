"""Development/test provider. Moves no money; must never run in production."""
import uuid

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from wages.payments.base import PaymentError, PaymentProvider, ProviderTimeout, TransferRequest, TransferStatus

VALID_CODE = "123456"


class FakeProvider(PaymentProvider):
    name = "fake"
    available = True

    # In-memory state shared across instances, reset by tests.
    transfers = {}          # idempotency_key -> dict(state, reference, request)
    by_reference = {}       # reference -> idempotency_key
    completed = []          # idempotency keys whose money "moved" (to prove no double payment)
    script = []             # next outcomes, consumed one per initiate/confirm call

    def __init__(self):
        if getattr(settings, "IS_PRODUCTION", False):
            raise ImproperlyConfigured("FakeProvider cannot be loaded under production settings.")

    @classmethod
    def reset(cls):
        cls.transfers, cls.by_reference, cls.completed, cls.script = {}, {}, [], []

    def _next(self):
        return type(self).script.pop(0) if type(self).script else None

    def initiate(self, request: TransferRequest) -> str:
        outcome = self._next()
        if outcome == "TIMEOUT":
            raise ProviderTimeout()
        if outcome == PaymentError.RECIPIENT_NO_WALLET:
            raise PaymentError(outcome)
        existing = self.transfers.get(request.idempotency_key)
        if existing:  # same key: re-send the code, never a second transfer
            return existing["reference"]
        reference = "FAKE-" + uuid.uuid4().hex[:12].upper()
        self.transfers[request.idempotency_key] = {"state": TransferStatus.PENDING_CODE, "reference": reference,
                                                   "request": request}
        self.by_reference[reference] = request.idempotency_key
        return reference

    def confirm(self, reference: str, code: str) -> str:
        key = self.by_reference[reference]
        transfer = self.transfers[key]
        outcome = self._next()
        if outcome == "CRASH":                  # an unexpected error inside the adapter
            raise RuntimeError("provider crashed")
        if outcome == "TIMEOUT":                # no answer, nothing moved
            raise ProviderTimeout()
        if outcome in (PaymentError.CODE_EXPIRED, PaymentError.INSUFFICIENT_BALANCE):
            if outcome == PaymentError.INSUFFICIENT_BALANCE:
                transfer["state"] = TransferStatus.FAILED
            raise PaymentError(outcome)
        if code != VALID_CODE:
            raise PaymentError(PaymentError.WRONG_CODE)
        if transfer["state"] != TransferStatus.SUCCEEDED:
            transfer["state"] = TransferStatus.SUCCEEDED
            self.completed.append(key)
        if outcome == "TIMEOUT_AFTER_SUCCESS":  # money moved, but the answer was lost
            raise ProviderTimeout()
        return reference

    def get_status(self, idempotency_key: str, reference: str | None) -> TransferStatus:
        transfer = self.transfers.get(idempotency_key)
        if transfer is None:
            return TransferStatus(TransferStatus.FAILED, failure="NOT_FOUND")
        return TransferStatus(transfer["state"], reference=transfer["reference"])
