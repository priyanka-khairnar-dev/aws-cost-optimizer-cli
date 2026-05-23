# Writing a new analyzer

Every analyzer is a class that inherits from `Analyzer` and implements `analyze()`. This document walks through writing one end to end.

## The shape

```python
# src/cost_optimizer/analyzers/my_analyzer.py
from __future__ import annotations

import logging

from cost_optimizer.core import Analyzer, Finding

logger = logging.getLogger(__name__)


class MyAnalyzer(Analyzer):
    name = "my_analyzer"
    description = "Detect waste of type X."
    ai_workload_relevant = False  # set True if this is AI-specific

    def __init__(self, aws_client, *, my_threshold: float = 0.05) -> None:
        super().__init__(aws_client, my_threshold=my_threshold)
        self.my_threshold = my_threshold

    def analyze(self) -> list[Finding]:
        findings: list[Finding] = []
        for page in self.aws.paginate("ec2", "describe_instances"):
            for reservation in page["Reservations"]:
                for instance in reservation["Instances"]:
                    if self._is_wasteful(instance):
                        findings.append(self._build_finding(instance))
        return findings

    def _is_wasteful(self, instance: dict) -> bool:
        ...

    def _build_finding(self, instance: dict) -> Finding:
        ...
```

Then register it in `src/cost_optimizer/analyzers/__init__.py`:

```python
from cost_optimizer.analyzers.my_analyzer import MyAnalyzer

ALL_ANALYZERS = [
    ...,
    MyAnalyzer,
]
```

## Checklist before merging an analyzer

- [ ] Inherits from `Analyzer`, sets `name` and `description`.
- [ ] All AWS calls go through `self.aws` (never raw `boto3`).
- [ ] All paginated APIs use `self.aws.paginate(...)`.
- [ ] `analyze()` returns `list[Finding]`, never raises for empty results.
- [ ] Each `Finding` has a meaningful `title`, `description`, and concrete `fix_suggestion`.
- [ ] `monthly_savings_usd` is computed from real pricing data, not hardcoded.
- [ ] Unit test under `tests/unit/test_analyzers/test_<name>.py` using `moto`.
- [ ] Listed in `ALL_ANALYZERS`.
- [ ] If AI-workload-specific, `ai_workload_relevant = True`.
- [ ] Doc comment at the top of the module explains *what* this detects and *why* it's worth detecting.

## Testing patterns

Use `moto` to seed AWS state, then run the analyzer against it:

```python
import boto3
from cost_optimizer.analyzers.my_analyzer import MyAnalyzer


def test_detects_idle_instance(aws_client):
    # Seed state via boto3 (moto intercepts)
    ec2 = boto3.client("ec2", region_name="us-east-1")
    ec2.run_instances(ImageId="ami-12345678", InstanceType="t3.micro", MinCount=1, MaxCount=1)

    findings = MyAnalyzer(aws_client).analyze()

    assert len(findings) == 1
    assert findings[0].resource_type == "ec2-instance"
```

## What good analyzers look like

The best analyzers in this codebase share a few traits:

- **Specific, not generic.** "Idle EC2 instances" is good. "Suboptimal resources" is bad. The narrower the analyzer, the more actionable the finding.
- **Conservative thresholds.** Default thresholds should produce *zero* false positives in a healthy account. Users can lower thresholds if they want noisier scans.
- **Real-world fix suggestions.** "Delete this volume" is unhelpful if the user doesn't know whether the data is still needed. Good: "Volume has been unattached for 60 days. If unneeded, snapshot first (`aws ec2 create-snapshot ...`) then delete (`aws ec2 delete-volume ...`)."
- **Pricing-aware.** A finding without a dollar amount is just a warning. Use the AWS Pricing API (or the cached pricing in `core/pricing.py`) to compute `monthly_savings_usd`.
