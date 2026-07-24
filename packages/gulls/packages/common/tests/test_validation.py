from __future__ import annotations

from unittest import TestCase

from seagull_common.validation import Validator


class ApiError(Exception):
    def __init__(self, status_code: int, error: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error = error
        self.message = message


class StringValidationTest(TestCase):
    def setUp(self) -> None:
        self.validator = Validator(ValueError)

    def test_required_string_returns_stripped_value(self) -> None:
        self.assertEqual("hello", self.validator.required_string({"name": "  hello  "}, "name"))

    def test_required_string_rejects_missing_field(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            self.validator.required_string({}, "name")
        self.assertEqual("name is required", str(ctx.exception))

    def test_required_string_rejects_blank_value(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            self.validator.required_string({"name": "   "}, "name")
        self.assertEqual("name is required", str(ctx.exception))

    def test_required_string_rejects_non_string(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            self.validator.required_string({"name": 42}, "name")
        self.assertEqual("name must be a string", str(ctx.exception))

    def test_optional_string_returns_none_for_missing_or_blank(self) -> None:
        self.assertIsNone(self.validator.optional_string({}, "name"))
        self.assertIsNone(self.validator.optional_string({"name": "  "}, "name"))

    def test_optional_string_rejects_non_string(self) -> None:
        with self.assertRaises(ValueError):
            self.validator.optional_string({"name": ["x"]}, "name")

    def test_error_factory_controls_exception_type(self) -> None:
        validator = Validator(lambda message: ApiError(400, "bad_request", message))
        with self.assertRaises(ApiError) as ctx:
            validator.required_string({}, "name")
        self.assertEqual(400, ctx.exception.status_code)
        self.assertEqual("bad_request", ctx.exception.error)
        self.assertEqual("name is required", ctx.exception.message)


class StringListTest(TestCase):
    def test_default_dialect_strips_items_and_drops_empties(self) -> None:
        validator = Validator(ValueError)
        self.assertEqual(("a", "b"), validator.string_list([" a ", "b", "  "], "refs"))

    def test_verbatim_dialect_preserves_items(self) -> None:
        validator = Validator(ValueError, strip_list_items=False)
        self.assertEqual((" a ", "b", "  "), validator.string_list([" a ", "b", "  "], "refs"))

    def test_none_is_empty_tuple(self) -> None:
        self.assertEqual((), Validator(ValueError).string_list(None, "refs"))

    def test_rejects_non_list(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            Validator(ValueError).string_list("a,b", "refs")
        self.assertEqual("refs must be a list", str(ctx.exception))

    def test_rejects_non_string_items(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            Validator(ValueError).string_list(["a", 2], "refs")
        self.assertEqual("refs must contain only strings", str(ctx.exception))


class IntValidationTest(TestCase):
    def test_optional_int_returns_value_or_none(self) -> None:
        validator = Validator(ValueError)
        self.assertEqual(7, validator.optional_int({"count": 7}, "count"))
        self.assertIsNone(validator.optional_int({}, "count"))

    def test_optional_int_rejects_non_int(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            Validator(ValueError).optional_int({"count": "7"}, "count")
        self.assertEqual("count must be an integer", str(ctx.exception))

    def test_bool_dialects(self) -> None:
        # ai-provider dialect: bool is an int subclass and passes through.
        self.assertEqual(True, Validator(ValueError).optional_int({"count": True}, "count"))
        # message-hub dialect: bools are rejected where ints are expected.
        with self.assertRaises(ValueError):
            Validator(ValueError, reject_bool_ints=True).optional_int({"count": True}, "count")

    def test_required_int(self) -> None:
        validator = Validator(ValueError)
        self.assertEqual(3, validator.required_int({"count": 3}, "count"))
        with self.assertRaises(ValueError) as ctx:
            validator.required_int({}, "count")
        self.assertEqual("count is required", str(ctx.exception))

    def test_optional_int_with_default(self) -> None:
        validator = Validator(ValueError)
        self.assertEqual(512, validator.optional_int_with_default({}, "max", default=512))
        self.assertEqual(9, validator.optional_int_with_default({"max": 9}, "max", default=512))


class FloatAndBoolValidationTest(TestCase):
    def setUp(self) -> None:
        self.validator = Validator(ValueError)

    def test_optional_float_accepts_int_and_float(self) -> None:
        self.assertEqual(0.2, self.validator.optional_float({}, "temperature", default=0.2))
        self.assertEqual(1.0, self.validator.optional_float({"temperature": 1}, "temperature", default=0.2))
        self.assertEqual(0.7, self.validator.optional_float({"temperature": 0.7}, "temperature", default=0.2))

    def test_optional_float_rejects_non_number(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            self.validator.optional_float({"temperature": "hot"}, "temperature", default=0.2)
        self.assertEqual("temperature must be a number", str(ctx.exception))

    def test_optional_bool(self) -> None:
        self.assertTrue(self.validator.optional_bool({}, "async", default=True))
        self.assertFalse(self.validator.optional_bool({"async": False}, "async", default=True))
        with self.assertRaises(ValueError) as ctx:
            self.validator.optional_bool({"async": "yes"}, "async", default=False)
        self.assertEqual("async must be a boolean", str(ctx.exception))
