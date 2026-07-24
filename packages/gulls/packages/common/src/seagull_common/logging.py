"""Single-line JSON logging to stdout, the shape CloudWatch ingests."""

from __future__ import annotations

import json
from typing import Any


def log(level: str, message: str, **fields: Any) -> None:
    print(json.dumps({"level": level, "message": message, **fields}, default=str))
