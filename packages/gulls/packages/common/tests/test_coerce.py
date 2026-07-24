from __future__ import annotations

from datetime import datetime, timezone
from unittest import TestCase

from seagull_common.coerce import datetime_to_string, dict_value, int_value, string_value, without_none


class IntValueTest(TestCase):
    def test_int_passes_through(self) -> None:
        self.assertEqual(5, int_value(5))

    def test_digit_string_is_parsed(self) -> None:
        self.assertEqual(42, int_value("42"))

    def test_everything_else_is_zero(self) -> None:
        self.assertEqual(0, int_value("4.2"))
        self.assertEqual(0, int_value("-1"))
        self.assertEqual(0, int_value(None))
        self.assertEqual(0, int_value({}))


class StringValueTest(TestCase):
    def test_non_blank_string_passes_through_unstripped(self) -> None:
        self.assertEqual(" a ", string_value(" a "))

    def test_blank_and_non_string_are_none(self) -> None:
        self.assertIsNone(string_value("   "))
        self.assertIsNone(string_value(7))
        self.assertIsNone(string_value(None))


class DictValueTest(TestCase):
    def test_dict_passes_through(self) -> None:
        self.assertEqual({"a": 1}, dict_value({"a": 1}))

    def test_non_dict_is_empty_dict(self) -> None:
        self.assertEqual({}, dict_value(None))
        self.assertEqual({}, dict_value([("a", 1)]))


class WithoutNoneTest(TestCase):
    def test_drops_only_none_values(self) -> None:
        self.assertEqual(
            {"a": 1, "c": "", "d": 0, "e": False},
            without_none({"a": 1, "b": None, "c": "", "d": 0, "e": False}),
        )


class DatetimeToStringTest(TestCase):
    def test_none_is_none(self) -> None:
        self.assertIsNone(datetime_to_string(None))

    def test_datetime_is_isoformat(self) -> None:
        value = datetime(2026, 7, 24, 12, 30, 45, tzinfo=timezone.utc)
        self.assertEqual("2026-07-24T12:30:45+00:00", datetime_to_string(value))
