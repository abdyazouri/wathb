"""Shared money formatting for user-facing *_display fields.

Display only: raw agorot fields, money calculations and CSV/report exports
must keep using the integer minor-unit values.
"""

_ARABIC_INDIC_DIGITS = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")
_ARABIC_DECIMAL_SEPARATOR = "٫"
SHEKEL_SIGN = "₪"


def to_arabic_indic(text):
    return str(text).translate(_ARABIC_INDIC_DIGITS)


def format_money(minor_units):
    """Agorot → "٢٥٠ ₪" or "٢٥٫٥٠ ₪". Exact integer math, never rounds."""
    minor_units = int(minor_units)
    sign = "-" if minor_units < 0 else ""
    major, agorot = divmod(abs(minor_units), 100)
    number = str(major) if agorot == 0 else f"{major}{_ARABIC_DECIMAL_SEPARATOR}{agorot:02d}"
    return f"{sign}{to_arabic_indic(number)} {SHEKEL_SIGN}"
