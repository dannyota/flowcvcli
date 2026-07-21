"""Exception hierarchy for the library layer.

The client and mixins used to raise `SystemExit` on every failure — fine for the
CLI, hostile to the documented Python/LLM-agent use: `SystemExit` tears down the
host process and, being a `BaseException` (not `Exception`), slips past a plain
`except Exception`. These are ordinary exceptions, so a caller can `except
FlowCVError` (or a specific subclass) and recover; the CLI turns them back into a
clean `sys.exit(message)` at the top level.
"""


class FlowCVError(Exception):
    """Base for every error the library raises — catch this to handle them all."""


class AuthError(FlowCVError):
    """Login / cookie / session problem: the request was never authenticated."""


class RateLimitError(FlowCVError):
    """FlowCV returned HTTP 429 — too many requests (login is capped at ~100/day)."""


class NotFoundError(FlowCVError):
    """A looked-up section, entry, template, or link doesn't exist."""


class ApiError(FlowCVError):
    """Any other failure: a bad envelope, a network error, or a bad response."""
