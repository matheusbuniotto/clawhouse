"""API route modules."""

from clawhouse.api.routes.agents import _agent_routes
from clawhouse.api.routes.approvals import _approval_routes, _question_routes
from clawhouse.api.routes.assets import register_assets
from clawhouse.api.routes.memory import _memory_routes
from clawhouse.api.routes.schedules import _schedule_routes
from clawhouse.api.routes.sessions import _cancel_routes, _session_routes
from clawhouse.api.routes.status import _hatch_routes, _status_routes
from clawhouse.api.routes.suggestions import _composer_routes

__all__ = [
    "_agent_routes",
    "_approval_routes",
    "_cancel_routes",
    "_composer_routes",
    "_hatch_routes",
    "_memory_routes",
    "_question_routes",
    "_schedule_routes",
    "_session_routes",
    "_status_routes",
    "register_assets",
]
