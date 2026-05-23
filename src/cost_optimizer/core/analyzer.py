"""Core abstractions for the analyzer plugin model.

Every analyzer produces ``Finding`` objects through a common interface. This
separation lets us mix and match analyzers, test each one in isolation, and
hand findings off to different reporters (terminal, markdown, JSON) without
the analyzers knowing anything about output format.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from cost_optimizer.aws.client import AwsClient


class Severity(str, Enum):
    """Impact-based severity for findings.

    Severity is derived from estimated monthly savings, not from the
    technical nature of the waste. A single $2,000/mo idle GPU is HIGH;
    fifty $1/mo unused EIPs combined are LOW.
    """

    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"

    @classmethod
    def from_monthly_savings(cls, usd: float) -> Severity:
        """Map dollars/month to severity buckets."""
        if usd >= 500:
            return cls.HIGH
        if usd >= 50:
            return cls.MEDIUM
        return cls.LOW


@dataclass(frozen=True)
class Finding:
    """A single waste finding from an analyzer.

    Findings are immutable data. They describe *what* is wasteful and
    *how much* it costs, but contain no formatting or output logic.
    """

    analyzer: str
    """Name of the analyzer that produced this finding (e.g., 'ec2_idle')."""

    resource_id: str
    """AWS resource identifier (instance ID, volume ID, etc.)."""

    resource_type: str
    """AWS resource type (e.g., 'ec2-instance', 'ebs-volume')."""

    region: str
    """AWS region where the resource lives."""

    title: str
    """Short human-readable description (one line)."""

    description: str
    """Longer explanation of why this is waste."""

    monthly_savings_usd: float
    """Estimated monthly savings if the waste is eliminated."""

    fix_suggestion: str
    """One-paragraph guidance on how to fix it."""

    severity: Severity = field(init=False)
    """Auto-computed from monthly_savings_usd."""

    metadata: dict[str, Any] = field(default_factory=dict)
    """Extra context (utilization metrics, age, tags, etc.)."""

    def __post_init__(self) -> None:
        # frozen=True means we can't assign normally; use object.__setattr__
        object.__setattr__(
            self, "severity", Severity.from_monthly_savings(self.monthly_savings_usd)
        )


class Analyzer(ABC):
    """Base class for all analyzers.

    Each analyzer focuses on one category of waste (idle EC2, unattached EBS,
    NAT egress, etc.). The orchestrator runs all enabled analyzers and
    aggregates their findings.

    Subclasses must implement ``analyze()`` and set the ``name`` class
    attribute. Configuration should be passed at __init__ time and stored
    on the instance — analyzers should be cheap to construct so tests can
    spin them up easily.
    """

    name: str
    """Unique identifier for the analyzer (used in config, output, logs)."""

    description: str
    """Human-readable description shown in CLI --list-analyzers."""

    ai_workload_relevant: bool = False
    """If True, included when --ai-mode is passed."""

    def __init__(self, aws_client: AwsClient, **config: Any) -> None:
        if not getattr(self, "name", None):
            raise TypeError(f"{type(self).__name__} must set a 'name' class attribute")
        self.aws = aws_client
        self.config = config

    @abstractmethod
    def analyze(self) -> list[Finding]:
        """Run the analysis and return findings.

        Implementations should:
        - Be idempotent (running twice produces the same result, modulo time)
        - Handle pagination internally (use ``self.aws.paginate(...)``)
        - Never modify AWS resources
        - Log progress for long-running scans
        """
        raise NotImplementedError
