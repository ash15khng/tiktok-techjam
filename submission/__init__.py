"""TechJam submission package.

The official evaluator imports :class:`submission.agent.Agent`. Implementation
modules live under :mod:`submission.src` so the package can be submitted as one
self-contained directory.
"""

from submission.agent import Agent

__all__ = ["Agent"]
