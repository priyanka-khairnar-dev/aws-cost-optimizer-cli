# Architecture

## Goals

`aws-cost-optimizer` is built around four design goals, in priority order:

1. **Findings are data.** Analyzers produce structured `Finding` objects; reporters consume them. This separation means we can add new output formats (JSON, HTML, Slack) without touching analyzer code, and we can test analyzers in isolation from output.

2. **Plugin-style analyzers.** Each waste category lives in its own module behind a common `Analyzer` interface. Adding "S3 storage class optimization" or "SageMaker endpoint idle" is a new file, not a refactor.

3. **Read-only, always.** The tool never modifies AWS resources. The IAM policy in the README only includes `Describe*`, `Get*`, and `List*` actions. Even by accident, this tool cannot delete your data.

4. **Testable without AWS.** All analyzers are unit-tested against `moto`-mocked AWS. CI runs without credentials. You can develop on a plane.

## Component overview

```
                ┌─────────────────────┐
                │   CLI (typer)       │
                │   cost-optimizer    │
                │     analyze         │
                │     detail          │
                │     --ai-mode       │
                └──────────┬──────────┘
                           │
                ┌──────────▼──────────┐
                │  Orchestrator       │
                │  - load config      │
                │  - select analyzers │
                │  - aggregate        │
                └──────────┬──────────┘
                           │
             ┌─────────────┼─────────────┐
             │             │             │
      ┌──────▼────┐  ┌─────▼─────┐  ┌────▼──────┐
      │ EC2 Idle  │  │ EBS Waste │  │ NAT/Egress│
      │ Analyzer  │  │ Analyzer  │  │ Analyzer  │
      └──────┬────┘  └─────┬─────┘  └────┬──────┘
             │             │             │
             └─────────────┼─────────────┘
                           │
                ┌──────────▼──────────┐
                │  AWS Client Layer   │
                │  - boto3 sessions   │
                │  - pagination       │
                │  - retry/backoff    │
                └─────────────────────┘
```

## Key design decisions

### Why `Finding` is a frozen dataclass

Findings flow through orchestrator → reporters → output. If any layer could mutate them, we'd get heisenbugs where the JSON reporter sees different values from the terminal reporter. Freezing them removes the bug class entirely.

The cost is a tiny amount of boilerplate (`object.__setattr__` in `__post_init__` to compute severity). Worth it.

### Why `Severity` is derived from savings, not from the analyzer

A naive approach lets each analyzer say "this is HIGH severity." But a HIGH-severity unused EIP ($4/month) and a HIGH-severity idle GPU ($2,300/month) need to be ordered correctly in the final report.

Deriving severity from dollar impact gives consistent prioritization across analyzers without each one needing to know the global picture.

### Why we wrap boto3

Three reasons:

1. **Testability.** With `moto`, we can run the full analyzer suite in CI without AWS credentials. The `AwsClient` is the only place boto3 is touched.

2. **Pagination is verbose.** `client.get_paginator(...).paginate(...)` is everywhere in AWS code. Hiding it behind `aws.paginate(...)` removes ~3 lines from every analyzer.

3. **Future caching.** When the tool scales to multi-account / multi-region, we'll need to cache `describe_instances` results across analyzers (idle EC2 and GPU underutilization both call it). The wrapper is the natural place for that cache.

### Why analyzers are classes, not functions

Analyzers carry config (thresholds, lookback windows, exclusion tags). Pushing that config through function arguments gets unwieldy fast. Classes also make it easy to share helpers via method extraction without polluting the module namespace.

### Why pricing lives in a `core/pricing.py` module (planned)

Cost estimates need pricing data: how much does a `g5.12xlarge` cost per hour in `us-east-1`? The AWS Pricing API is its own service, with its own pagination and quirks. Concentrating that knowledge in one module means analyzers stay focused on detection, not pricing.

### Why no async

This tool's I/O is bursty rather than sustained — a scan completes in 30-60 seconds. Async boto3 (`aioboto3`) adds complexity (different mocking, different error handling, harder debugging) for marginal speedup. If scans ever take >5 minutes, we'll revisit. Premature async is a real anti-pattern.

## Project structure

```
src/cost_optimizer/
├── cli.py                  # User-facing CLI (typer)
├── core/
│   ├── analyzer.py         # Analyzer base, Finding dataclass, Severity enum
│   ├── orchestrator.py     # Runs analyzers, aggregates findings
│   ├── config.py           # Config loading (pydantic)
│   └── pricing.py          # AWS pricing helpers
├── aws/
│   ├── client.py           # boto3 session wrapper
│   └── pagination.py       # paginator helpers (if needed beyond client)
├── analyzers/              # One file per analyzer
│   ├── ec2_idle.py
│   ├── ebs_waste.py
│   ├── nat_egress.py
│   ├── unused_eips.py
│   └── gpu_underutilization.py
└── reporters/              # One file per output format
    ├── terminal.py         # Pretty CLI output (rich)
    ├── markdown.py         # Markdown report file
    └── json.py             # Machine-readable
```

## Adding a new analyzer

See [analyzers.md](analyzers.md).

## Non-goals

To stay focused, the tool deliberately does *not* try to:

- **Modify AWS resources.** Recommendations only.
- **Replace commercial FinOps tools** like Vantage, CloudHealth, Spot.io. Those are dashboard-driven and span many clouds. This is a CLI with an opinionated focus on AI workloads.
- **Support GCP and Azure.** AWS-only by design. Multi-cloud requires different abstractions that would muddy the codebase.
- **Be a long-running service.** It's a one-shot CLI. If you want continuous monitoring, write a wrapper that runs this on a schedule and posts to Slack.
