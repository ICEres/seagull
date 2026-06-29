from __future__ import annotations

import sys
from dataclasses import dataclass as _dataclass


def dataclass(_cls=None, **kwargs):
    if sys.version_info < (3, 10):
        kwargs.pop("slots", None)
    if _cls is None:
        return _dataclass(**kwargs)
    return _dataclass(_cls, **kwargs)
