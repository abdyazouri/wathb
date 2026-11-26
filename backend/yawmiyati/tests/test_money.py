from django.test import SimpleTestCase

from yawmiyati.money import format_money, to_arabic_indic


class FormatMoneyTests(SimpleTestCase):

    def test_whole_shekels_have_no_decimals(self):
        self.assertEqual(format_money(25000), "٢٥٠ ₪")

    def test_fractional_shekels_keep_both_agorot_digits(self):
        self.assertEqual(format_money(2550), "٢٥٫٥٠ ₪")
        self.assertEqual(format_money(2505), "٢٥٫٠٥ ₪")

    def test_never_rounds(self):
        # 99.99 must not become 100; 0.01 must not become 0.
        self.assertEqual(format_money(9999), "٩٩٫٩٩ ₪")
        self.assertEqual(format_money(1), "٠٫٠١ ₪")
        self.assertEqual(format_money(12345678), "١٢٣٤٥٦٫٧٨ ₪")

    def test_zero(self):
        self.assertEqual(format_money(0), "٠ ₪")

    def test_negative(self):
        self.assertEqual(format_money(-2550), "-٢٥٫٥٠ ₪")

    def test_output_has_no_latin_digits_or_currency_code(self):
        for value in (0, 1, 99, 100, 2550, 25000, 987654321):
            out = format_money(value)
            self.assertFalse(any(c in "0123456789" for c in out), out)
            self.assertNotIn("ILS", out)
            self.assertTrue(out.endswith(" ₪"), out)

    def test_client_to_arabic_numerals_is_harmless(self):
        # Mirrors the Android String.toArabicNumerals(): maps 0-9 only, leaves the
        # rest untouched. Applying it on top of the server output changes nothing.
        for value in (25000, 2550, 1):
            out = format_money(value)
            self.assertEqual(to_arabic_indic(out), out)
