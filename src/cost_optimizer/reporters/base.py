"""Reporter base class.

Reporters consume a ``ScanResult`` and render it to a specific output
format. They know nothing about analyzers or AWS — purely about
presenting findings to a destination (stdout, a file, etc.).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cost_optimizer.core.orchestrator import ScanResult


class Reporter(ABC):
    """Render a ScanResult to some output target."""

    @abstractmethod
    def render(self, result: ScanResult) -> str:
        """Return the report as a string."""
        raise NotImplementedError
