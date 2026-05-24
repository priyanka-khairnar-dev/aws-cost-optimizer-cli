"""Tests for the Orchestrator."""

from __future__ import annotations

from typing import ClassVar
from unittest.mock import MagicMock

import pytest

from cost_optimizer.aws.client import AwsClient
from cost_optimizer.core import Analyzer, Finding, Orchestrator


class _FakeAnalyzer(Analyzer):
    """Configurable test double — pass findings and/or an exception."""

    name = "fake"
    description = "test"
    ai_workload_relevant = False

    def __init__(
        self,
        aws_client: AwsClient,
        *,
        findings: list[Finding] | None = None,
        raises: Exception | None = None,
    ) -> None:
        super().__init__(aws_client)
        self._findings = findings or []
        self._raises = raises

    def analyze(self) -> list[Finding]:
        if self._raises is not None:
            raise self._raises
        return list(self._findings)


def _finding(savings: float, analyzer: str = "fake", resource_id: str = "i-1") -> Finding:
    return Finding(
        analyzer=analyzer,
        resource_id=resource_id,
        resource_type="ec2-instance",
        region="us-east-1",
        title=f"Idle ({savings})",
        description="d",
        monthly_savings_usd=savings,
        fix_suggestion="fix",
    )


class TestOrchestratorRun:
    def test_collects_findings_from_all_analyzers(self, aws_client: AwsClient) -> None:
        a1 = _FakeAnalyzer(aws_client, findings=[_finding(100), _finding(50)])
        a2 = _FakeAnalyzer(aws_client, findings=[_finding(200)])

        result = Orchestrator(aws_client).run_instances([a1, a2])

        assert len(result.findings) == 3
        assert result.total_monthly_savings_usd == 350.0

    def test_findings_sorted_by_savings_descending(self, aws_client: AwsClient) -> None:
        a = _FakeAnalyzer(
            aws_client,
            findings=[_finding(50, resource_id="cheap"), _finding(500, resource_id="expensive")],
        )

        result = Orchestrator(aws_client).run_instances([a])

        assert result.findings[0].resource_id == "expensive"
        assert result.findings[1].resource_id == "cheap"

    def test_records_failure_when_analyzer_raises(self, aws_client: AwsClient) -> None:
        good = _FakeAnalyzer(aws_client, findings=[_finding(100)])
        broken = _FakeAnalyzer(aws_client, raises=RuntimeError("boom"))

        result = Orchestrator(aws_client).run_instances([good, broken])

        # Good analyzer's findings still present.
        assert len(result.findings) == 1
        # Failure captured.
        assert len(result.failures) == 1
        assert result.failures[0].error_type == "RuntimeError"
        assert "boom" in result.failures[0].message

    def test_one_failure_does_not_kill_subsequent_analyzers(self, aws_client: AwsClient) -> None:
        broken = _FakeAnalyzer(aws_client, raises=ValueError("explode"))
        good = _FakeAnalyzer(aws_client, findings=[_finding(99)])

        result = Orchestrator(aws_client).run_instances([broken, good])

        assert len(result.findings) == 1
        assert result.findings[0].monthly_savings_usd == 99.0
        assert len(result.failures) == 1

    def test_empty_analyzer_list_returns_empty_result(self, aws_client: AwsClient) -> None:
        result = Orchestrator(aws_client).run_instances([])
        assert result.findings == []
        assert result.failures == []

    def test_records_scan_duration(self, aws_client: AwsClient) -> None:
        a = _FakeAnalyzer(aws_client)
        result = Orchestrator(aws_client).run_instances([a])
        assert result.duration_seconds >= 0

    def test_captures_account_id(self, aws_client: AwsClient) -> None:
        a = _FakeAnalyzer(aws_client)
        result = Orchestrator(aws_client).run_instances([a])
        # moto returns a 12-digit string account ID
        assert len(result.account_id) == 12

    def test_account_id_lookup_failure_is_swallowed(self, aws_client: AwsClient) -> None:
        """If STS is unreachable, scan should still complete."""
        a = _FakeAnalyzer(aws_client, findings=[_finding(10)])
        broken_aws = MagicMock(spec=aws_client)
        broken_aws.region = "us-east-1"
        broken_aws.get_account_id.side_effect = RuntimeError("STS down")

        result = Orchestrator(broken_aws).run_instances([a])

        assert result.account_id == ""
        assert len(result.findings) == 1


class TestAiModeFiltering:
    class _AIRelevant(Analyzer):
        name = "ai_one"
        description = "ai"
        ai_workload_relevant = True
        _runs: ClassVar[int] = 0

        def analyze(self) -> list[Finding]:
            type(self)._runs += 1
            return []

    class _NotAIRelevant(Analyzer):
        name = "general_one"
        description = "general"
        ai_workload_relevant = False
        _runs: ClassVar[int] = 0

        def analyze(self) -> list[Finding]:
            type(self)._runs += 1
            return []

    def setup_method(self) -> None:
        # Reset class-level counters between tests.
        type(self)._AIRelevant._runs = 0
        type(self)._NotAIRelevant._runs = 0

    def test_ai_mode_runs_only_ai_relevant_analyzers(self, aws_client: AwsClient) -> None:
        Orchestrator(aws_client).run([self._AIRelevant, self._NotAIRelevant], ai_mode=True)
        assert self._AIRelevant._runs == 1
        assert self._NotAIRelevant._runs == 0

    def test_default_mode_runs_all_analyzers(self, aws_client: AwsClient) -> None:
        Orchestrator(aws_client).run([self._AIRelevant, self._NotAIRelevant], ai_mode=False)
        assert self._AIRelevant._runs == 1
        assert self._NotAIRelevant._runs == 1


class TestScanResult:
    def test_total_savings_is_sum_of_findings(self) -> None:
        from cost_optimizer.core.orchestrator import ScanResult

        result = ScanResult(findings=[_finding(100), _finding(250.50), _finding(0)])
        assert result.total_monthly_savings_usd == pytest.approx(350.50)

    def test_total_savings_zero_when_no_findings(self) -> None:
        from cost_optimizer.core.orchestrator import ScanResult

        result = ScanResult(findings=[])
        assert result.total_monthly_savings_usd == 0.0
