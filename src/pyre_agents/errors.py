"""Runtime errors for Pyre lifecycle operations."""

from __future__ import annotations


class PyreError(Exception):
    """Base class for Pyre runtime errors."""


class AgentNotFoundError(PyreError):
    """Raised when looking up a non-existent agent."""


class AgentInvocationError(PyreError):
    """Raised when an agent invocation crashes."""


class AgentTerminatedError(PyreError):
    """Raised when an agent exceeded restart intensity and is terminated."""


class SystemStoppedError(PyreError):
    """Raised when a call is attempted on a runtime that is shutting down."""
