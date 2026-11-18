import re
import uuid
from contextvars import ContextVar

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
_SAFE = re.compile(r"^[A-Za-z0-9._-]{8,64}$")


def new_request_id(incoming: str | None) -> str:
    """Reuse a caller-supplied correlation id only if it is plainly safe to log; otherwise mint one."""
    return incoming if incoming and _SAFE.match(incoming) else uuid.uuid4().hex
