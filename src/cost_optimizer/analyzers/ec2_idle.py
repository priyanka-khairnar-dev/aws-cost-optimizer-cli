"""Detect EC2 instances that have been consistently idle.

We define "idle" as: over a configurable lookback window (default 14 days),
the instance's maximum CPU stayed below a threshold AND its maximum network
throughput stayed below a threshold.

Using ``Maximum`` rather than ``Average`` is intentional. An instance that
averages 3% CPU but peaks at 80% twice a day is doing real work; an
instance whose *peak* is 4% across two weeks is genuinely idle.

Combining CPU with network catches:

- NAT instances and bastion hosts (low CPU, high network — not idle).
- Streaming/proxy workloads (low CPU, high network — not idle).
- True zombies (low CPU, low network — idle).

Findings include a ``fix_suggestion`` that gives a concrete next action
(stop, terminate, or right-size) rather than the vague "consider reviewing".
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from cost_optimizer.core import Analyzer, Finding
from cost_optimizer.core.pricing import EC2Pricing, PricingLookupError

if TYPE_CHECKING:
    from cost_optimizer.aws.client import AwsClient

logger = logging.getLogger(__name__)

# CloudWatch's GetMetricStatistics imposes a maximum of 1,440 data points
# per request. With a 1-hour period (3600s), that's 60 days of history,
# which is more than we need.
_METRIC_PERIOD_SECONDS = 3600

# Tag that suppresses findings on a resource (e.g., for DR standbys).
_EXCLUSION_TAG_KEY = "cost-audit:exclude"


@dataclass(frozen=True)
class _Metrics:
    """Container for the CloudWatch metrics we examined."""

    max_cpu_percent: float
    max_network_bytes_per_sec: float
    data_points: int


class EC2IdleAnalyzer(Analyzer):
    """Find EC2 instances with sustained low CPU and network utilization."""

    name = "ec2_idle"
    description = "Detect EC2 instances that have been idle for an extended period."
    ai_workload_relevant = True  # idle GPUs are the biggest single win for AI shops

    # Defaults are deliberately conservative — a healthy account should
    # produce zero false positives. Users can tighten these via config.
    DEFAULT_LOOKBACK_DAYS = 14
    DEFAULT_CPU_THRESHOLD_PERCENT = 10.0
    DEFAULT_NETWORK_THRESHOLD_BYTES_PER_SEC = 1_000_000  # 1 MB/s
    DEFAULT_MIN_INSTANCE_AGE_DAYS = 7

    def __init__(
        self,
        aws_client: AwsClient,
        *,
        lookback_days: int = DEFAULT_LOOKBACK_DAYS,
        cpu_threshold_percent: float = DEFAULT_CPU_THRESHOLD_PERCENT,
        network_threshold_bytes_per_sec: float = DEFAULT_NETWORK_THRESHOLD_BYTES_PER_SEC,
        min_instance_age_days: int = DEFAULT_MIN_INSTANCE_AGE_DAYS,
        pricing: EC2Pricing | None = None,
    ) -> None:
        super().__init__(
            aws_client,
            lookback_days=lookback_days,
            cpu_threshold_percent=cpu_threshold_percent,
            network_threshold_bytes_per_sec=network_threshold_bytes_per_sec,
            min_instance_age_days=min_instance_age_days,
        )
        self.lookback_days = lookback_days
        self.cpu_threshold_percent = cpu_threshold_percent
        self.network_threshold_bytes_per_sec = network_threshold_bytes_per_sec
        self.min_instance_age_days = min_instance_age_days
        # Dependency-inject pricing so tests can supply a fake.
        self.pricing = pricing or EC2Pricing(aws_client)

    def analyze(self) -> list[Finding]:
        findings: list[Finding] = []
        now = datetime.now(timezone.utc)
        min_age = timedelta(days=self.min_instance_age_days)

        for page in self.aws.paginate("ec2", "describe_instances"):
            for reservation in page["Reservations"]:
                for instance in reservation["Instances"]:
                    finding = self._evaluate_instance(instance, now, min_age)
                    if finding is not None:
                        findings.append(finding)
        return findings

    def _evaluate_instance(
        self,
        instance: dict[str, Any],
        now: datetime,
        min_age: timedelta,
    ) -> Finding | None:
        """Return a Finding if the instance is idle, else None."""
        instance_id = instance["InstanceId"]
        state = instance["State"]["Name"]

        # Stopped instances aren't billing for compute — they're an EBS
        # concern, handled by a separate analyzer.
        if state != "running":
            logger.debug("Skipping %s: state=%s", instance_id, state)
            return None

        # Honor the exclusion tag.
        tags = {tag["Key"]: tag["Value"] for tag in instance.get("Tags", [])}
        if _EXCLUSION_TAG_KEY in tags:
            logger.debug("Skipping %s: has %s tag", instance_id, _EXCLUSION_TAG_KEY)
            return None

        # Skip too-young instances — CloudWatch data would be too sparse
        # to be meaningful.
        launch_time = instance["LaunchTime"]
        if now - launch_time < min_age:
            logger.debug(
                "Skipping %s: launched %s ago (< min age %s)",
                instance_id,
                now - launch_time,
                min_age,
            )
            return None

        metrics = self._fetch_metrics(instance_id, now)
        if metrics.data_points == 0:
            logger.warning(
                "No CloudWatch data for %s — detailed monitoring may be off",
                instance_id,
            )
            return None

        if not self._is_idle(metrics):
            return None

        return self._build_finding(instance, metrics, tags)

    def _fetch_metrics(self, instance_id: str, now: datetime) -> _Metrics:
        """Pull max CPU and max network throughput over the lookback window."""
        start = now - timedelta(days=self.lookback_days)
        cw = self.aws.cloudwatch

        cpu_resp = cw.get_metric_statistics(
            Namespace="AWS/EC2",
            MetricName="CPUUtilization",
            Dimensions=[{"Name": "InstanceId", "Value": instance_id}],
            StartTime=start,
            EndTime=now,
            Period=_METRIC_PERIOD_SECONDS,
            Statistics=["Maximum"],
            Unit="Percent",
        )
        cpu_points = cpu_resp.get("Datapoints", [])
        max_cpu = max((dp["Maximum"] for dp in cpu_points), default=0.0)

        # NetworkOut is usually a better idleness signal than NetworkIn —
        # idle instances still receive scan/probe traffic. We sum both
        # and convert from "bytes per period" to "bytes per second".
        net_resp = cw.get_metric_statistics(
            Namespace="AWS/EC2",
            MetricName="NetworkOut",
            Dimensions=[{"Name": "InstanceId", "Value": instance_id}],
            StartTime=start,
            EndTime=now,
            Period=_METRIC_PERIOD_SECONDS,
            Statistics=["Maximum"],
            Unit="Bytes",
        )
        net_points = net_resp.get("Datapoints", [])
        max_net_bytes_per_period = max((dp["Maximum"] for dp in net_points), default=0.0)
        max_net_bytes_per_sec = max_net_bytes_per_period / _METRIC_PERIOD_SECONDS

        return _Metrics(
            max_cpu_percent=max_cpu,
            max_network_bytes_per_sec=max_net_bytes_per_sec,
            data_points=len(cpu_points),
        )

    def _is_idle(self, metrics: _Metrics) -> bool:
        return (
            metrics.max_cpu_percent < self.cpu_threshold_percent
            and metrics.max_network_bytes_per_sec < self.network_threshold_bytes_per_sec
        )

    def _build_finding(
        self,
        instance: dict[str, Any],
        metrics: _Metrics,
        tags: dict[str, str],
    ) -> Finding:
        instance_id = instance["InstanceId"]
        instance_type = instance["InstanceType"]
        name_tag = tags.get("Name", "(no Name tag)")

        # Estimate savings. If pricing lookup fails, still surface the
        # finding with $0 — it remains useful as a noisy signal.
        try:
            monthly_usd = self.pricing.monthly_usd(instance_type, self.aws.region)
        except PricingLookupError as exc:
            logger.warning("Pricing lookup failed for %s: %s", instance_id, exc)
            monthly_usd = 0.0

        title = f"Idle {instance_type} — {instance_id}"
        description = (
            f"Instance {instance_id} ({name_tag}, type {instance_type}) has been idle "
            f"for the last {self.lookback_days} days. "
            f"Peak CPU: {metrics.max_cpu_percent:.1f}% "
            f"(threshold {self.cpu_threshold_percent:.0f}%). "
            f"Peak network: {metrics.max_network_bytes_per_sec / 1_000_000:.2f} MB/s "
            f"(threshold {self.network_threshold_bytes_per_sec / 1_000_000:.0f} MB/s)."
        )
        fix_suggestion = _suggest_fix(instance_type, metrics)

        return Finding(
            analyzer=self.name,
            resource_id=instance_id,
            resource_type="ec2-instance",
            region=self.aws.region,
            title=title,
            description=description,
            monthly_savings_usd=monthly_usd,
            fix_suggestion=fix_suggestion,
            metadata={
                "instance_type": instance_type,
                "name": name_tag,
                "max_cpu_percent": metrics.max_cpu_percent,
                "max_network_mb_per_sec": metrics.max_network_bytes_per_sec / 1_000_000,
                "lookback_days": self.lookback_days,
            },
        )


def _suggest_fix(instance_type: str, metrics: _Metrics) -> str:
    """Pick a fix recommendation based on instance family and metrics shape."""
    # GPU instances are the highest-leverage win — call them out specifically.
    is_gpu = instance_type.startswith(("g", "p"))

    if is_gpu:
        return (
            "GPU instances cost an order of magnitude more than CPU instances. "
            f"If {instance_type} is unused, stop it now. If it's used intermittently, "
            "consider on-demand stop/start scheduling or a smaller GPU instance. "
            "For inference workloads, check whether SageMaker Serverless Inference "
            "or AWS Bedrock would be cheaper than holding the instance idle."
        )

    if metrics.max_cpu_percent < 2 and metrics.max_network_bytes_per_sec < 1000:
        return (
            "Instance shows essentially zero activity. Verify it's not a forgotten "
            "experiment, snapshot the volumes if data matters, then terminate."
        )

    return (
        f"Right-size or stop. If still needed, downgrade to a smaller instance "
        f"in the same family (e.g., one or two sizes down from {instance_type}). "
        "If unused, snapshot critical volumes and terminate."
    )
