"""Which payment provider and which mode the «تحويل الأجر» screen uses."""
from django.conf import settings

AUTOMATIC = "automatic"
MANUAL = "manual"


def get_provider():
    name = settings.PAYMENT_PROVIDER
    if name == "fake":
        from wages.payments.fake import FakeProvider
        return FakeProvider()  # raises under production settings
    if name == "jawwal":
        from wages.payments.jawwal import JawwalPayProvider
        return JawwalPayProvider()
    raise ValueError(f"Unknown PAYMENT_PROVIDER: {name}")


def payment_mode():
    """Automatic only when switched on (JAWWAL_PAY_AUTOMATIC) and the provider exists."""
    if settings.JAWWAL_PAY_AUTOMATIC and get_provider().available:
        return AUTOMATIC
    return MANUAL
