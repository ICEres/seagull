"""Backward-compatible protocol model exports.

New code should import base social/control primitives from
`seagull_protocol.base`, work/task primitives from `seagull_protocol.work`, and
generic event primitives from `seagull_protocol.events`.
"""

from seagull_protocol.base import *  # noqa: F403
from seagull_protocol.base import __all__ as _base_all
from seagull_protocol.events import *  # noqa: F403
from seagull_protocol.events import __all__ as _event_all
from seagull_protocol.work import *  # noqa: F403
from seagull_protocol.work import __all__ as _work_all


__all__ = [*_base_all, *_work_all, *_event_all]
