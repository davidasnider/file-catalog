"""Tests for the formatting helpers used by src/scripts/inspect_file.py."""

import datetime

from src.scripts.inspect_file import (
    display_image_iterm2,
    format_mtime,
    format_pii_value,
    format_size,
)


def test_format_size_none_returns_unknown():
    assert format_size(None) == "Unknown"


def test_format_size_unit_boundaries():
    assert format_size(0) == "0.00 B"
    # Just under the 1 KB threshold stays in bytes.
    assert format_size(1023) == "1023.00 B"
    # Exactly 1 KB rolls over and keeps two decimals.
    assert format_size(1024) == "1.00 KB"
    assert format_size(1536) == "1.50 KB"


def test_format_size_large_units():
    assert format_size(1024**3) == "1.00 GB"
    # Values of several terabytes cap out at the TB unit label.
    assert format_size(5 * 1024**5) == "5.00 TB"


def test_format_mtime_none_returns_unknown():
    assert format_mtime(None) == "Unknown"


def test_format_mtime_renders_utc():
    # The epoch must be interpreted as UTC regardless of the local timezone.
    assert format_mtime(0) == "1970-01-01 00:00:00 UTC"
    expected = datetime.datetime.fromtimestamp(1700000000, tz=datetime.timezone.utc)
    assert format_mtime(1700000000) == expected.strftime("%Y-%m-%d %H:%M:%S UTC")


def test_format_mtime_out_of_range_returns_unknown():
    # A value far beyond any representable date must not raise.
    assert format_mtime(1e20) == "Unknown"


def test_format_pii_value_plain_values():
    assert format_pii_value("123-45-6789") == "123-45-6789"
    # Non-dict, non-string values fall back to str().
    assert format_pii_value(42) == "42"


def test_format_pii_value_address_dict():
    address = {
        "street_address": "123 Main St",
        "city": "Springfield",
        "state": "IL",
        "zip_code": "62701",
    }
    assert format_pii_value(address) == "123 Main St / Springfield, IL 62701"

    address_with_box = dict(address, mailing_address={"box_number": 456})
    assert (
        format_pii_value(address_with_box)
        == "123 Main St / PO Box 456 / Springfield, IL 62701"
    )


def test_format_pii_value_empty_address_falls_back_to_str():
    empty = {"city": "", "state": "", "zip_code": ""}
    assert format_pii_value(empty) == str(empty)


def test_format_pii_value_generic_dict_joins_pairs():
    assert format_pii_value({"alpha": 1, "beta": "x"}) == "alpha: 1, beta: x"


def test_display_image_iterm2_missing_file_writes_nothing(capsys):
    display_image_iterm2("/nonexistent/path/that/does-not-exist.png")
    assert capsys.readouterr().out == ""
