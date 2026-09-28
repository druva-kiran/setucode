"""Permission decision enum."""
from __future__ import annotations

from enum import Enum


class PermissionDecision(Enum):
    AUTO_ALLOWED = "auto_allowed"   # readonly tool, no prompt needed
    ALLOW_ONCE = "allow_once"       # user approved this specific call
    ALLOW_ALWAYS = "allow_always"   # user approved and rule stored
    DENY = "deny"                   # user blocked the operation
