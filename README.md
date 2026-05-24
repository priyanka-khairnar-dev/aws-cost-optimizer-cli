# aws-cost-audit

> Find waste in AWS accounts. Prioritized by impact, with a focus on AI workloads.

`aws-cost-audit` is a Python CLI that scans an AWS account for cost waste — idle compute, unattached storage, over-provisioned NAT gateways, underutilized GPUs — and produces a prioritized, actionable report.

Most cost-optimization tools give you a 200-row CSV and call it a day. This tool gives you the top 10 things to fix this week, each with a one-line "how to fix" and an estimated monthly saving.

It's particularly useful for AI/ML workloads, where GPU spend, inference idle time, and data egress dominate cost in ways that traditional FinOps tools surface poorly.

## Status

**Alpha.** The package is not yet published to PyPI. Install from source — instructions below.

## Why this exists

AI workloads have a different cost shape than typical web infrastructure:

- A single underutilized `g5.12xlarge` costs more per month than 50 underutilized `t3.medium`s.
- Inference endpoints sit idle between requests but billing continues.
- Training jobs leak EBS volumes when interrupted.
- Cross-region model artifact replication generates massive NAT egress.

Standard cost tools don't prioritize these. This one does.

## Installation

The package isn't on PyPI yet. Install from source using one of the methods below.

### Option 1: Install directly from a clone (development)

Use this if you want to hack on the tool or follow `main`.

```bash
git clone https://github.com/YOUR_USERNAME/aws-cost-audit.git
cd aws-cost-audit

python -m venv .venv
source .venv/bin/activate    # On Windows: .venv\Scripts\activate

pip install -e .
```

The `-e` flag installs in editable mode — changes to the source take effect immediately.

For development with linting and test tools:

```bash
pip install -e ".[dev]"
```

### Option 2: Build a wheel and install it

Use this when you want a clean, installable artifact you can copy to another machine or share with a colleague.

```bash
# Clone and enter the directory
git clone https://github.com/YOUR_USERNAME/aws-cost-audit.git
cd aws-cost-audit

# Install the build tool (one-time setup)
pip install build

# Build a wheel
python -m build --wheel

# The wheel lands in dist/
ls dist/
# → aws_cost_audit-0.1.0-py3-none-any.whl
```

Now install the wheel — either in the same environment or anywhere else you have Python:

```bash
pip install dist/aws_cost_audit-0.1.0-py3-none-any.whl
```

To install on a different machine, copy the `.whl` file over and run the same `pip install` command against the local path.

### Option 3: Install directly from GitHub (no clone)

If you just want to use the tool without cloning:

```bash
pip install git+https://github.com/YOUR_USERNAME/aws-cost-audit.git
```

This installs the latest `main`. To pin to a specific tag or commit:

```bash
pip install git+https://github.com/YOUR_USERNAME/aws-cost-audit.git@v0.1.0
```

### Coming soon: PyPI

Once the tool reaches feature parity with the v0.1.0 roadmap below, it will be published to PyPI as `aws-cost-audit`. You'll then be able to install with a single command:

```bash
# Not yet available — coming with v0.1.0 release
pip install aws-cost-audit
```

## Verifying installation

After installing by any method, the `cost-optimizer` command should be on your PATH:

```bash
cost-optimizer --help
cost-optimizer version
```

If the command isn't found, check that the venv where you installed the package is activated.

## Quickstart

```bash
# Configure AWS credentials however you normally do
export AWS_PROFILE=my-account

# Run the full scan (pretty terminal output)
cost-optimizer analyze

# Focus on AI workload waste specifically
cost-optimizer analyze --ai-mode

# Save a client-ready markdown report
cost-optimizer analyze --format markdown --output report.md

# Machine-readable output for pipelines
cost-optimizer analyze --format json --output report.json

# Show full fix suggestions inline in the terminal
cost-optimizer analyze --detail
```

See [examples/sample_report.md](examples/sample_report.md) for a full markdown report example.

## Sample output

```
                AWS Cost Audit Report

  Account: 123456789012   Region: us-east-1   Scan: 2026-05-23

  Estimated monthly savings: $4,287

  ┌──┬────────────────────────────────┬──────────┬─────────────┐
  │ #│ Finding                        │ Savings  │ Severity    │
  ├──┼────────────────────────────────┼──────────┼─────────────┤
  │ 1│ 3 idle g5.12xlarge instances   │ $2,340/mo│ HIGH        │
  │ 2│ NAT egress in us-east-1        │ $890/mo  │ HIGH        │
  │ 3│ 47 unattached EBS volumes      │ $612/mo  │ MEDIUM      │
  │ 4│ 12 unused Elastic IPs          │ $43/mo   │ LOW         │
  └──┴────────────────────────────────┴──────────┴─────────────┘

Run `cost-optimizer detail 1` for fix instructions on finding #1.
```

## Architecture

The tool is built around a plugin-style analyzer model. Each analyzer is a self-contained module that knows how to find one category of waste.

See [docs/architecture.md](docs/architecture.md) for design details, and [docs/analyzers.md](docs/analyzers.md) for how to write a new analyzer.

## IAM permissions required

This tool is **read-only**. It will never modify your AWS account.

Minimum IAM policy:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": [
      "ec2:Describe*",
      "cloudwatch:GetMetricStatistics",
      "cloudwatch:ListMetrics",
      "ce:GetCostAndUsage",
      "ce:GetRightsizingRecommendation",
      "pricing:GetProducts"
    ],
    "Resource": "*"
  }]
}
```

## Roadmap

- [x] Core abstractions (Analyzer interface, Finding dataclass, AWS client wrapper)
- [x] EC2 idle detection
- [ ] EBS waste (unattached volumes, old snapshots)
- [ ] NAT gateway egress analysis
- [ ] Unused Elastic IPs
- [ ] GPU underutilization (AI mode)
- [ ] Publish to PyPI as `aws-cost-audit`
- [ ] SageMaker endpoint idle time
- [ ] Bedrock provisioned throughput analysis
- [ ] S3 storage class optimization
- [ ] Reserved Instance / Savings Plan recommendations
- [ ] Multi-account scan via AWS Organizations

## Development

After cloning:

```bash
pip install -e ".[dev]"

# Run the same checks CI runs
ruff check src tests
ruff format --check src tests
mypy src
pytest -v
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full development workflow, PR conventions, and code style.

## Building distributions

For maintainers releasing a new version:

```bash
# Build both wheel and source distribution
python -m build

# Outputs:
#   dist/aws_cost_audit-X.Y.Z-py3-none-any.whl
#   dist/aws_cost_audit-X.Y.Z.tar.gz

# Verify the wheel installs cleanly in a fresh venv
python -m venv /tmp/verify-venv
/tmp/verify-venv/bin/pip install dist/aws_cost_audit-X.Y.Z-py3-none-any.whl
/tmp/verify-venv/bin/cost-optimizer version
```

PyPI publishing instructions will be added once we're ready for v0.1.0 release.

## License

Apache 2.0. See [LICENSE](LICENSE).
