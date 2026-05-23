"""Tests for the EC2 idle analyzer."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import boto3
import pytest

from cost_optimizer.analyzers.ec2_idle import EC2IdleAnalyzer
from cost_optimizer.aws.client import AwsClient
from cost_optimizer.core import Severity

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakePricing:
    """Test double for EC2Pricing that returns deterministic values."""

    def __init__(self, hourly_usd_by_type: dict[str, float] | None = None) -> None:
        self._prices = hourly_usd_by_type or {
            "t3.micro": 0.0104,
            "m5.large": 0.096,
            "g5.12xlarge": 5.672,
            "p4d.24xlarge": 32.77,
        }

    def monthly_usd(self, instance_type: str, region: str) -> float:
        return self._prices.get(instance_type, 0.10) * 730.0


def _make_instance(
    *,
    instance_id: str = "i-0123456789abcdef0",
    instance_type: str = "m5.large",
    state: str = "running",
    launched_days_ago: int = 30,
    tags: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build a fake describe_instances Instance dict."""
    now = datetime.now(timezone.utc)
    return {
        "InstanceId": instance_id,
        "InstanceType": instance_type,
        "State": {"Name": state},
        "LaunchTime": now - timedelta(days=launched_days_ago),
        "Tags": [{"Key": k, "Value": v} for k, v in (tags or {}).items()],
    }


def _patch_describe_instances(analyzer: EC2IdleAnalyzer, instances: list[dict[str, Any]]) -> Any:
    """Make analyzer.aws.paginate return a single page with the given instances."""
    page = {"Reservations": [{"Instances": instances}]}
    return patch.object(analyzer.aws, "paginate", return_value=iter([page]))


def _patch_metrics(
    analyzer: EC2IdleAnalyzer,
    *,
    max_cpu: float,
    max_net_bytes_per_sec: float,
    data_points: int = 336,  # 14 days * 24 hours
) -> Any:
    """Replace _fetch_metrics with a fixed return value."""
    from cost_optimizer.analyzers.ec2_idle import _Metrics

    return patch.object(
        analyzer,
        "_fetch_metrics",
        return_value=_Metrics(
            max_cpu_percent=max_cpu,
            max_network_bytes_per_sec=max_net_bytes_per_sec,
            data_points=data_points,
        ),
    )


# ---------------------------------------------------------------------------
# Configuration & construction
# ---------------------------------------------------------------------------


class TestConfiguration:
    def test_default_thresholds_are_conservative(self, aws_client: AwsClient) -> None:
        a = EC2IdleAnalyzer(aws_client, pricing=FakePricing())
        assert a.lookback_days == 14
        assert a.cpu_threshold_percent == 10.0
        assert a.network_threshold_bytes_per_sec == 1_000_000
        assert a.min_instance_age_days == 7

    def test_thresholds_are_overridable(self, aws_client: AwsClient) -> None:
        a = EC2IdleAnalyzer(
            aws_client,
            lookback_days=30,
            cpu_threshold_percent=5.0,
            pricing=FakePricing(),
        )
        assert a.lookback_days == 30
        assert a.cpu_threshold_percent == 5.0

    def test_name_and_metadata(self, aws_client: AwsClient) -> None:
        a = EC2IdleAnalyzer(aws_client, pricing=FakePricing())
        assert a.name == "ec2_idle"
        assert a.ai_workload_relevant is True


# ---------------------------------------------------------------------------
# Skip rules
# ---------------------------------------------------------------------------


class TestSkipRules:
    def test_stopped_instances_are_skipped(self, aws_client: AwsClient) -> None:
        analyzer = EC2IdleAnalyzer(aws_client, pricing=FakePricing())
        instance = _make_instance(state="stopped")
        with _patch_describe_instances(analyzer, [instance]):
            findings = analyzer.analyze()
        assert findings == []

    def test_terminated_instances_are_skipped(self, aws_client: AwsClient) -> None:
        analyzer = EC2IdleAnalyzer(aws_client, pricing=FakePricing())
        instance = _make_instance(state="terminated")
        with _patch_describe_instances(analyzer, [instance]):
            findings = analyzer.analyze()
        assert findings == []

    def test_young_instances_are_skipped(self, aws_client: AwsClient) -> None:
        analyzer = EC2IdleAnalyzer(aws_client, pricing=FakePricing())
        # 3 days old < default min_instance_age_days=7
        instance = _make_instance(launched_days_ago=3)
        with (
            _patch_describe_instances(analyzer, [instance]),
            _patch_metrics(analyzer, max_cpu=1.0, max_net_bytes_per_sec=100),
        ):
            findings = analyzer.analyze()
        assert findings == []

    def test_excluded_instances_are_skipped(self, aws_client: AwsClient) -> None:
        analyzer = EC2IdleAnalyzer(aws_client, pricing=FakePricing())
        instance = _make_instance(tags={"cost-audit:exclude": "DR-standby"})
        with (
            _patch_describe_instances(analyzer, [instance]),
            _patch_metrics(analyzer, max_cpu=1.0, max_net_bytes_per_sec=100),
        ):
            findings = analyzer.analyze()
        assert findings == []


# ---------------------------------------------------------------------------
# Idleness detection logic
# ---------------------------------------------------------------------------


class TestIdleDetection:
    def test_truly_idle_instance_is_reported(self, aws_client: AwsClient) -> None:
        analyzer = EC2IdleAnalyzer(aws_client, pricing=FakePricing())
        instance = _make_instance(instance_id="i-deadbeef00000001", instance_type="m5.large")
        with (
            _patch_describe_instances(analyzer, [instance]),
            _patch_metrics(analyzer, max_cpu=3.0, max_net_bytes_per_sec=500),
        ):
            findings = analyzer.analyze()
        assert len(findings) == 1
        assert findings[0].resource_id == "i-deadbeef00000001"
        assert findings[0].resource_type == "ec2-instance"

    def test_high_cpu_instance_is_not_reported(self, aws_client: AwsClient) -> None:
        """An instance with peak CPU above threshold isn't idle."""
        analyzer = EC2IdleAnalyzer(aws_client, pricing=FakePricing())
        instance = _make_instance()
        with (
            _patch_describe_instances(analyzer, [instance]),
            _patch_metrics(analyzer, max_cpu=85.0, max_net_bytes_per_sec=500),
        ):
            findings = analyzer.analyze()
        assert findings == []

    def test_high_network_instance_is_not_reported(self, aws_client: AwsClient) -> None:
        """NAT / streaming workloads have low CPU but high network — not idle."""
        analyzer = EC2IdleAnalyzer(aws_client, pricing=FakePricing())
        instance = _make_instance()
        with (
            _patch_describe_instances(analyzer, [instance]),
            _patch_metrics(
                analyzer,
                max_cpu=2.0,
                max_net_bytes_per_sec=5_000_000,  # 5 MB/s sustained
            ),
        ):
            findings = analyzer.analyze()
        assert findings == []

    def test_no_cloudwatch_data_is_not_reported(self, aws_client: AwsClient) -> None:
        """If CloudWatch has no data points, we can't conclude idleness."""
        analyzer = EC2IdleAnalyzer(aws_client, pricing=FakePricing())
        instance = _make_instance()
        with (
            _patch_describe_instances(analyzer, [instance]),
            _patch_metrics(analyzer, max_cpu=0.0, max_net_bytes_per_sec=0, data_points=0),
        ):
            findings = analyzer.analyze()
        assert findings == []

    def test_threshold_boundary_strictly_less_than(self, aws_client: AwsClient) -> None:
        """CPU exactly at threshold should NOT be reported (strict inequality)."""
        analyzer = EC2IdleAnalyzer(aws_client, cpu_threshold_percent=10.0, pricing=FakePricing())
        instance = _make_instance()
        with (
            _patch_describe_instances(analyzer, [instance]),
            _patch_metrics(analyzer, max_cpu=10.0, max_net_bytes_per_sec=500),
        ):
            findings = analyzer.analyze()
        assert findings == []


# ---------------------------------------------------------------------------
# Finding contents
# ---------------------------------------------------------------------------


class TestFindingContents:
    def test_finding_has_meaningful_title_and_description(self, aws_client: AwsClient) -> None:
        analyzer = EC2IdleAnalyzer(aws_client, pricing=FakePricing())
        instance = _make_instance(
            instance_id="i-1234567890abcdef0",
            instance_type="g5.12xlarge",
            tags={"Name": "training-worker-3"},
        )
        with (
            _patch_describe_instances(analyzer, [instance]),
            _patch_metrics(analyzer, max_cpu=4.0, max_net_bytes_per_sec=100),
        ):
            findings = analyzer.analyze()
        assert len(findings) == 1
        f = findings[0]
        assert "g5.12xlarge" in f.title
        assert "i-1234567890abcdef0" in f.title
        assert "training-worker-3" in f.description
        assert "14 days" in f.description

    def test_gpu_instance_gets_gpu_specific_fix(self, aws_client: AwsClient) -> None:
        analyzer = EC2IdleAnalyzer(aws_client, pricing=FakePricing())
        instance = _make_instance(instance_type="p4d.24xlarge")
        with (
            _patch_describe_instances(analyzer, [instance]),
            _patch_metrics(analyzer, max_cpu=1.0, max_net_bytes_per_sec=50),
        ):
            findings = analyzer.analyze()
        assert "GPU" in findings[0].fix_suggestion
        assert "Bedrock" in findings[0].fix_suggestion or "SageMaker" in findings[0].fix_suggestion

    def test_severity_derived_from_savings(self, aws_client: AwsClient) -> None:
        """A pricey GPU instance should land at HIGH severity."""
        analyzer = EC2IdleAnalyzer(aws_client, pricing=FakePricing())
        instance = _make_instance(instance_type="g5.12xlarge")
        with (
            _patch_describe_instances(analyzer, [instance]),
            _patch_metrics(analyzer, max_cpu=2.0, max_net_bytes_per_sec=50),
        ):
            findings = analyzer.analyze()
        assert findings[0].severity is Severity.HIGH
        # 5.672 * 730 = ~4140/mo
        assert findings[0].monthly_savings_usd > 4000

    def test_metadata_captures_utilization_numbers(self, aws_client: AwsClient) -> None:
        analyzer = EC2IdleAnalyzer(aws_client, pricing=FakePricing())
        instance = _make_instance()
        with (
            _patch_describe_instances(analyzer, [instance]),
            _patch_metrics(analyzer, max_cpu=3.7, max_net_bytes_per_sec=12_500),
        ):
            findings = analyzer.analyze()
        meta = findings[0].metadata
        assert meta["max_cpu_percent"] == pytest.approx(3.7)
        assert meta["max_network_mb_per_sec"] == pytest.approx(0.0125)
        assert meta["lookback_days"] == 14


# ---------------------------------------------------------------------------
# Pricing failures
# ---------------------------------------------------------------------------


class TestPricingFailures:
    def test_pricing_lookup_failure_yields_zero_savings_not_crash(
        self, aws_client: AwsClient
    ) -> None:
        """Tool should degrade gracefully when pricing is unavailable."""
        from cost_optimizer.core.pricing import PricingLookupError

        broken_pricing = MagicMock()
        broken_pricing.monthly_usd.side_effect = PricingLookupError("nope")

        analyzer = EC2IdleAnalyzer(aws_client, pricing=broken_pricing)
        instance = _make_instance()
        with (
            _patch_describe_instances(analyzer, [instance]),
            _patch_metrics(analyzer, max_cpu=2.0, max_net_bytes_per_sec=100),
        ):
            findings = analyzer.analyze()
        assert len(findings) == 1
        assert findings[0].monthly_savings_usd == 0.0


# ---------------------------------------------------------------------------
# Integration with moto-seeded EC2
# ---------------------------------------------------------------------------


class TestModoIntegration:
    def test_analyzer_runs_against_moto_ec2_without_crashing(self, aws_client: AwsClient) -> None:
        """Smoke test: seed an instance via moto and let the analyzer process it.

        Moto's CloudWatch returns no data by default, so we expect no
        findings — but the analyzer should complete without raising.
        """
        ec2 = boto3.client("ec2", region_name="us-east-1")
        ec2.run_instances(
            ImageId="ami-12345678",
            InstanceType="t3.micro",
            MinCount=1,
            MaxCount=1,
        )
        analyzer = EC2IdleAnalyzer(aws_client, pricing=FakePricing())
        # Should not raise, even with empty CloudWatch.
        findings = analyzer.analyze()
        # No findings expected — moto has no CW data for the instance.
        assert isinstance(findings, list)
