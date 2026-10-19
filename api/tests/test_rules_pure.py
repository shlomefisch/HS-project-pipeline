"""Rules that need no database."""

from app.rules.normalize import norm_email, norm_name, norm_phone
from app.rules.qr import parse_item_code


def test_names_compare_without_spacing_case_or_punctuation():
    assert norm_name("  Pinches  Kisch ") == "pinches kisch"
    assert norm_name("PINCHES KISCH") == "pinches kisch"
    assert norm_name("A-to-Z Construction, Inc.") == "a to z construction inc"
    assert norm_name("") == ""
    assert norm_name(None) == ""


def test_phones_compare_as_digits():
    assert norm_phone("(845) 555-1234") == "8455551234"
    assert norm_phone("845.555.1234") == "8455551234"
    assert norm_phone("+1 845 555 1234") == "8455551234"
    assert norm_phone("ext 12") is None
    assert norm_phone(None) is None


def test_emails_lowercase_and_trim():
    assert norm_email("  Rifky@Example.COM ") == "rifky@example.com"
    assert norm_email("not-an-email") is None
    assert norm_email("@x.com") is None


def test_qr_takes_the_number_after_the_last_slash():
    assert parse_item_code("https://5032967.app.netsuite.com/app/common/item/item.nl/100101") == 100101
    assert parse_item_code("https://hstile.com/i/100203/") == 100203
    assert parse_item_code("100422") == 100422
    assert parse_item_code(" 100422 ") == 100422


def test_qr_falls_back_to_an_id_parameter():
    assert parse_item_code("https://5032967.app.netsuite.com/app/common/item/item.nl?id=100530") == 100530


def test_qr_rejects_codes_without_an_item_number():
    assert parse_item_code("https://hstile.com/about") is None
    assert parse_item_code("") is None
    assert parse_item_code(None) is None
