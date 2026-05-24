"""Scan orchestration.

The Orchestrator selects which analyzers to run, executes them, aggregates
their findings, and reports any per-analyzer failures back to the caller.
Critically, a single analyzer raising must not kill the whole scan — we
catch and record failures so the user still sees the findings that did
succeed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from time import perf_counter
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cost_optimizer.aws.client import AwsClient
    from cost_optimizer.core.analyzer import Analyzer, Finding

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AnalyzerFailure:
    """Captures a per-analyzer error so it can be reported without crashing."""

    analyzer: str
    error_type: str
    message: str


@dataclass(frozen=True)
class ScanResult:
    """The product of one full scan.

    Sorted by descending monthly savings so the highest-impact items come
    first. Failures are reported separately and don't poison the findings
    list.
    """

    findings: list[Finding]
    failures: list[AnalyzerFailure] = field(default_factory=list)
    account_id: str = ""
    region: str = ""
    duration_seconds: float = 0.0

    @property
    def total_monthly_savings_usd(self) -> float:
        return sum(f.monthly_savings_usd for f in self.findings)


class Orchestrator:
    """Runs a set of analyzers and produces a ScanResult.

    Analyzers are instantiated with default config — for per-analyzer
    config knobs, instantiate analyzers yourself and pass them to
    ``run_instances`` instead of using ``run``.
    """

    def __init__(self, aws_client: AwsClient) -> None:
        self.aws = aws_client

    def run(
        self,
        analyzer_classes: list[type[Analyzer]],
        *,
        ai_mode: bool = False,
    ) -> ScanResult:
        """Instantiate and run a list of analyzer classes."""
        selected = self._select_analyzers(analyzer_classes, ai_mode=ai_mode)
        instances = [cls(self.aws) for cls in selected]
        return self.run_instances(instances)

    def run_instances(self, analyzers: list[Analyzer]) -> ScanResult:
        """Run already-instantiated analyzers. Use when you need custom config."""
        start = perf_counter()
        findings: list[Finding] = []
        failures: list[AnalyzerFailure] = []

        for analyzer in analyzers:
            try:
                logger.info("Running %s", analyzer.name)
                t0 = perf_counter()
                results = analyzer.analyze()
                logger.info(
                    "  %s found %d issue(s) in %.2fs",
                    analyzer.name,
                    len(results),
                    perf_counter() - t0,
                )
                findings.extend(results)
            except Exception as exc:
                logger.warning("Analyzer %s failed: %s", analyzer.name, exc, exc_info=True)
                failures.append(
                    AnalyzerFailure(
                        analyzer=analyzer.name,
                        error_type=type(exc).__name__,
                        message=str(exc),
                    )
                )

        # Sort by impact, highest savings first. Ties broken by analyzer
        # name for stable output.
        findings.sort(key=lambda f: (-f.monthly_savings_usd, f.analyzer, f.resource_id))

        account_id = ""
        try:
            account_id = self.aws.get_account_id()
        except Exception as exc:
            logger.debug("Could not resolve account ID: %s", exc)

        return ScanResult(
            findings=findings,
            failures=failures,
            account_id=account_id,
            region=self.aws.region,
            duration_seconds=perf_counter() - start,
        )

    @staticmethod
    def _select_analyzers(
        analyzer_classes: list[type[Analyzer]],
        *,
        ai_mode: bool,
    ) -> list[type[Analyzer]]:
        """Filter the analyzer list based on the mode flags."""
        if ai_mode:
            return [cls for cls in analyzer_classes if cls.ai_workload_relevant]
        return list(analyzer_classes)
