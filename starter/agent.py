"""Compatibility import for the unmodified local evaluator.

The final submission entry point is :mod:`submission.agent`. Keeping this shim
allows ``python -m evaluator.local_evaluator`` to run without editing the
organizer-provided evaluator.
"""

from submission.agent import Agent

__all__ = ["Agent"]
