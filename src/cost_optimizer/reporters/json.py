"""JSON reporter — machine-readable output for downstream tools.

Designed for piping to ``jq``, posting to Slack via webhook, or feeding
into a Lambda that creates JIRA tickets. The schema is stable across
versions; new fields are additive.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from cost_optimizer import __version__
from cost_optimizer.reporters.base import Reporter

if TYPE_CHECKING:
    from cost_optimizer.core.orchestrator import ScanResult


class JsonReporter(Reporter):
    """Render findings as a JSON document."""

    def __init__(self, *, indent: int | None = 2) -> None:
        # indent=None produces compact output, suitable for streaming.
        self.indent = indent

    def render(self, result: ScanResult) -> str:
        payload: dict[str, Any] = {
            "schema_version": "1.0",
            "tool_version": __version__,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "account_id": result.account_id,
            "region": result.region,
            "scan_duration_seconds": round(result.duration_seconds, 3),
            "summary": {
                "total_findings": len(result.findings),
                "total_monthly_savings_usd": round(result.total_monthly_savings_usd, 2),
            },
            "findings": [self._serialize_finding(f) for f in result.findings],
            "failures": [
                {
                    "analyzer": fail.analyzer,
                    "error_type": fail.error_type,
                    "message": fail.message,
                }
                for fail in result.failures
            ],
        }
        return json.dumps(payload, indent=self.indent, default=str)

    @staticmethod
    def _serialize_finding(finding: Any) -> dict[str, Any]:
        return {
            "analyzer": finding.analyzer,
            "resource_id": finding.resource_id,
            "resource_type": finding.resource_type,
            "region": finding.region,
            "title": finding.title,
            "description": finding.description,
            "monthly_savings_usd": round(finding.monthly_savings_usd, 2),
            "severity": finding.severity.value,
            "fix_suggestion": finding.fix_suggestion,
            "metadata": finding.metadata,
        }
