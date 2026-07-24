"""Request-body validation helpers shared across gull services.

Each service raises its own exception type (``ApiError``, ``BadRequest``,
plain ``ValueError``), so the shared parsing logic is packaged as a
``Validator`` constructed with an error factory. Message texts match the
historical per-service copies exactly.
"""

from __future__ import annotations

from typing import Any, Callable


class Validator:
    """Body-parsing helpers parameterized by an error factory.

    ``error`` is called with a message and must return the exception to raise.

    ``reject_bool_ints`` selects the integer-parsing dialect: message-hub
    rejects booleans where integers are expected, while the ai-provider
    copies accept them as ``int`` subclasses. ``strip_list_items`` selects the
    ``string_list`` dialect: ai-provider/safety-gateway strip items and drop
    empties, while message-hub preserves the list verbatim.
    """

    def __init__(
        self,
        error: Callable[[str], Exception],
        *,
        reject_bool_ints: bool = False,
        strip_list_items: bool = True,
    ) -> None:
        self._error = error
        self._reject_bool_ints = reject_bool_ints
        self._strip_list_items = strip_list_items

    def required_string(self, body: dict[str, Any], field_name: str) -> str:
        value = self.optional_string(body, field_name)
        if value is None:
            raise self._error(f"{field_name} is required")
        return value

    def optional_string(self, body: dict[str, Any], field_name: str) -> str | None:
        value = body.get(field_name)
        if value is None:
            return None
        if not isinstance(value, str):
            raise self._error(f"{field_name} must be a string")
        stripped = value.strip()
        return stripped or None

    def string_list(self, value: Any, field_name: str) -> tuple[str, ...]:
        if value is None:
            return ()
        if not isinstance(value, (list, tuple)):
            raise self._error(f"{field_name} must be a list")
        if not all(isinstance(item, str) for item in value):
            raise self._error(f"{field_name} must contain only strings")
        if not self._strip_list_items:
            return tuple(value)
        return tuple(item.strip() for item in value if item.strip())

    def optional_int(self, body: dict[str, Any], field_name: str) -> int | None:
        value = body.get(field_name)
        if value is None:
            return None
        if not isinstance(value, int) or (self._reject_bool_ints and isinstance(value, bool)):
            raise self._error(f"{field_name} must be an integer")
        return value

    def required_int(self, body: dict[str, Any], field_name: str) -> int:
        value = self.optional_int(body, field_name)
        if value is None:
            raise self._error(f"{field_name} is required")
        return value

    def optional_int_with_default(self, body: dict[str, Any], field_name: str, *, default: int) -> int:
        value = self.optional_int(body, field_name)
        return default if value is None else value

    def optional_float(self, body: dict[str, Any], field_name: str, *, default: float) -> float:
        value = body.get(field_name)
        if value is None:
            return default
        if not isinstance(value, (int, float)):
            raise self._error(f"{field_name} must be a number")
        return float(value)

    def optional_bool(self, body: dict[str, Any], field_name: str, *, default: bool) -> bool:
        value = body.get(field_name)
        if value is None:
            return default
        if not isinstance(value, bool):
            raise self._error(f"{field_name} must be a boolean")
        return value
