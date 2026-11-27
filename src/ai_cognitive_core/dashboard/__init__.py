"""Dashboard web backend for ai_cognitive_core (local-only, no auth).

``create_app`` is loaded lazily (PEP 562) so that importing this
package never pulls in FastAPI, and so that
``python -m ai_cognitive_core.dashboard.app`` does not trigger a
double-import warning for the ``app`` submodule.
"""

from typing import Any

__all__ = ["create_app"]


def __getattr__(name: str) -> Any:
    if name == "create_app":
        from ai_cognitive_core.dashboard.app import create_app

        return create_app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
