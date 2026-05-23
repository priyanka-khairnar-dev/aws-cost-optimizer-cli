"""Tests for the core analyzer abstractions."""

from __future__ import annotations

import pytest

from cost_optimizer.core import Finding, Severity


class TestSeverity:
    @pytest.mark.parametrize(
        ("savings", "expected"),
        [
            (1500.00, Severity.HIGH),
            (500.00, Severity.HIGH),
            (499.99, Severity.MEDIUM),
            (50.00, Severity.MEDIUM),
            (49.99, Severity.LOW),
            (0.00, Severity.LOW),
            (-10.0, Severity.LOW),  # weird input shouldn't crash
        ],
    )
    def test_from_monthly_savings(self, savings: float, expected: Severity) -> None:
        assert Severity.from_monthly_savings(savings) is expected


class TestFinding:
    def test_severity_is_derived_from_savings(self) -> None:
        f = Finding(
            analyzer="ec2_idle",
            resource_id="i-abc123",
            resource_type="ec2-instance",
            region="us-east-1",
            title="Idle g5.12xlarge",
            description="CPU < 5% for 14 days",
            monthly_savings_usd=2340.0,
            fix_suggestion="Stop or right-size to g5.2xlarge.",
        )
        assert f.severity is Severity.HIGH

    def test_finding_is_immutable(self) -> None:
        f = Finding(
            analyzer="ebs_waste",
            resource_id="vol-deadbeef",
            resource_type="ebs-volume",
            region="us-east-1",
            title="Unattached EBS volume",
            description="Not attached for 60 days",
            monthly_savings_usd=12.0,
            fix_suggestion="Delete volume.",
        )
        with pytest.raises(Exception):  # noqa: B017 — frozen dataclass raises FrozenInstanceError
            f.monthly_savings_usd = 99.0  # type: ignore[misc]

    def test_metadata_defaults_to_empty_dict(self) -> None:
        f = Finding(
            analyzer="x",
            resource_id="y",
            resource_type="z",
            region="us-east-1",
            title="t",
            description="d",
            monthly_savings_usd=0.0,
            fix_suggestion="f",
        )
        assert f.metadata == {}
