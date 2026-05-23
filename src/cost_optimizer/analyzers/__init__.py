"""Analyzer implementations.

Each module here defines one ``Analyzer`` subclass. The orchestrator
discovers them via the ``ALL_ANALYZERS`` registry below.
"""

from __future__ import annotations

from cost_optimizer.analyzers.ec2_idle import EC2IdleAnalyzer
from cost_optimizer.core import Analyzer

# Keeping a manual registry (vs entry-points discovery) is fine at this
# scale and makes the import order explicit. Order matters: analyzers
# are run sequentially, and pricing API responses are cached, so grouping
# EC2-family analyzers together is mildly more efficient.

ALL_ANALYZERS: list[type[Analyzer]] = [
    EC2IdleAnalyzer,
]

__all__ = ["ALL_ANALYZERS", "EC2IdleAnalyzer"]
