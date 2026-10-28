"""
Singleton PostgresSaver checkpointer for LangGraph state persistence.

PostgresSaver (synchronous) is used because all graph nodes, database session
makers, and FastAPI routes in this project are fully synchronous.  A single
module-level instance is created once on application startup; every call to
``get_checkpointer()`` returns that same instance.
"""
from __future__ import annotations

import re
import logging
from typing import Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

_checkpointer = None        # module-level singleton
_checkpointer_conn = None   # raw psycopg3 connection kept alive


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_psycopg3_dsn(database_url: str) -> str:
    """
    Convert a SQLAlchemy-style DATABASE_URL to a plain psycopg3 DSN.

    Examples::

        postgresql://user:pass@host:5432/db
        postgresql+psycopg2://user:pass@host:5432/db
        postgresql+asyncpg://user:pass@host:5432/db
            → all become:
        postgresql://user:pass@host:5432/db
    """
    return re.sub(r"postgresql\+\w+://", "postgresql://", database_url)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def setup_checkpointer() -> None:
    """
    Create the ``PostgresSaver`` singleton and call ``.setup()`` to ensure the
    LangGraph checkpoint tables (``checkpoints``, ``checkpoint_blobs``,
    ``checkpoint_writes``) exist in the database.

    Called once from the FastAPI ``lifespan`` startup handler.
    """
    global _checkpointer, _checkpointer_conn

    try:
        import psycopg                              # psycopg3
        from langgraph.checkpoint.postgres import PostgresSaver

        dsn = _make_psycopg3_dsn(settings.DATABASE_URL)

        # A long-lived synchronous psycopg3 connection for the checkpointer.
        # autocommit=True is required by PostgresSaver.
        _checkpointer_conn = psycopg.connect(dsn, autocommit=True)
        _checkpointer = PostgresSaver(_checkpointer_conn)
        _checkpointer.setup()   # idempotent – creates tables if they don't exist
        logger.info("LangGraph PostgresSaver checkpointer initialized successfully.")
    except Exception as exc:
        logger.warning(
            "Could not initialize PostgresSaver checkpointer: %s. "
            "Investigation state will NOT be persisted across restarts.",
            exc,
        )
        _checkpointer = None
        _checkpointer_conn = None


def teardown_checkpointer() -> None:
    """Close the long-lived psycopg3 connection on application shutdown."""
    global _checkpointer_conn
    if _checkpointer_conn is not None:
        try:
            _checkpointer_conn.close()
            logger.info("LangGraph PostgresSaver connection closed.")
        except Exception:
            pass
        _checkpointer_conn = None


def get_checkpointer() -> Optional[object]:
    """Return the initialized ``PostgresSaver`` instance, or ``None`` if it
    was not successfully set up (e.g. DB unreachable during startup)."""
    return _checkpointer
