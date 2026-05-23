# aws-cost-optimizer

> Find waste in AWS accounts. Prioritized by impact, with a focus on AI workloads.

`aws-cost-optimizer` is a Python CLI that scans an AWS account for cost waste — idle compute, unattached storage, over-provisioned NAT gateways, underutilized GPUs — and produces a prioritized, actionable report.

Most cost-optimization tools give you a 200-row CSV and call it a day. This tool gives you the top 10 things to fix this week, each with a one-line "how to fix" and an estimated monthly saving.

It's particularly useful for AI/ML workloads, where GPU spend, inference idle time, and data egress dominate cost in ways that traditional FinOps tools surface poorly.

## Why this exists

AI workloads have a different cost shape than typical web infrastructure:

- A single underutilized `g5.12xlarge` costs more per month than 50 underutilized `t3.medium`s.
- Inference endpoints sit idle between requests but billing continues.
- Training jobs leak EBS volumes when interrupted.
- Cross-region model artifact replication generates massive NAT egress.

Standard cost tools don't prioritize these. This one does.

## Quickstart

```bash
pip install aws-cost-optimizer

# Configure AWS credentials however you normally do
export AWS_PROFILE=my-account

# Run the full scan
cost-optimizer analyze

# Focus on AI workload waste specifically
cost-optimizer analyze --ai-mode

# Save markdown report
cost-optimizer analyze --output report.md
```

## Sample output

```
                AWS Cost Optimizer Report
                                                              
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

- [x] EC2 idle detection
- [x] EBS waste (unattached volumes, old snapshots)
- [x] NAT gateway egress analysis
- [x] Unused Elastic IPs
- [x] GPU underutilization (AI mode)
- [ ] SageMaker endpoint idle time
- [ ] Bedrock provisioned throughput analysis
- [ ] S3 storage class optimization
- [ ] Reserved Instance / Savings Plan recommendations
- [ ] Multi-account scan via AWS Organizations

## Contributing

Issues and PRs welcome. See [docs/analyzers.md](docs/analyzers.md) for how to add a new analyzer.

## License

Apache 2.0. See [LICENSE](LICENSE).
