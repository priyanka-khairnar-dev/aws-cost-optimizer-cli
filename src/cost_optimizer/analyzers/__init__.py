"""Analyzer implementations.

Each module here defines one ``Analyzer`` subclass. The orchestrator
discovers them via the ``ALL_ANALYZERS`` registry below.
"""

from __future__ import annotations

# Analyzers will be added to this list as they're implemented.
# Keeping a manual registry (vs entry-points discovery) is fine at this
# scale and makes the import order explicit.

ALL_ANALYZERS: list[type] = []
