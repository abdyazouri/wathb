"""Jawwal Pay adapter — NOT BUILT.

No endpoint, field or format here may be guessed. It will be written only from Jawwal
Pay's own documentation, and only if that documentation supports transfers initiated by
a third party from the business's wallet straight to the worker's wallet (not merely
payments into a Wathb merchant account). See docs/JAWWAL_PAY_REQUIREMENTS.md.
"""
from wages.payments.base import PaymentProvider

_NOT_BUILT = "Jawwal Pay adapter is not built yet; see docs/JAWWAL_PAY_REQUIREMENTS.md."


class JawwalPayProvider(PaymentProvider):
    name = "jawwal"
    available = False  # keeps the payment screen in manual mode

    def initiate(self, request):
        raise NotImplementedError(_NOT_BUILT)

    def confirm(self, reference, code):
        raise NotImplementedError(_NOT_BUILT)

    def get_status(self, idempotency_key, reference):
        raise NotImplementedError(_NOT_BUILT)
