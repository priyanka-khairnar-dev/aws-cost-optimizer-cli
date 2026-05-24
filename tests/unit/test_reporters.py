"""Tests for reporters: terminal, markdown, JSON."""

from __future__ import annotations

import json

from cost_optimizer.core import Finding
from cost_optimizer.core.orchestrator import AnalyzerFailure, ScanResult
from cost_optimizer.reporters import JsonReporter, MarkdownReporter, TerminalReporter


def _finding(savings: float = 100.0, **overrides: object) -> Finding:
    defaults = {
        "analyzer": "ec2_idle",
        "resource_id": "i-1234567890abcdef0",
        "resource_type": "ec2-instance",
        "region": "us-east-1",
        "title": "Idle m5.large",
        "description": "Peak CPU 3.5% over 14 days.",
        "monthly_savings_usd": savings,
        "fix_suggestion": "Stop or right-size the instance.",
        "metadata": {"max_cpu_percent": 3.5},
    }
    defaults.update(overrides)
    return Finding(**defaults)  # type: ignore[arg-type]


def _result(
    findings: list[Finding] | None = None,
    failures: list[AnalyzerFailure] | None = None,
) -> ScanResult:
    return ScanResult(
        findings=findings or [],
        failures=failures or [],
        account_id="123456789012",
        region="us-east-1",
        duration_seconds=2.5,
    )


# ---------------------------------------------------------------------------
# Terminal reporter
# ---------------------------------------------------------------------------


class TestTerminalReporter:
    def test_clean_account_message(self) -> None:
        output = TerminalReporter().render(_result())
        assert "No cost waste detected" in output

    def test_shows_findings_in_table(self) -> None:
        result = _result([_finding(savings=500), _finding(savings=200)])
        output = TerminalReporter().render(result)
        assert "Idle m5.large" in output
        assert "$500" in output
        assert "$200" in output

    def test_shows_total_savings_in_footer(self) -> None:
        result = _result([_finding(savings=300), _finding(savings=150)])
        output = TerminalReporter().render(result)
        assert "$450" in output

    def test_shows_account_and_region_in_header(self) -> None:
        output = TerminalReporter().render(_result())
        assert "123456789012" in output
        assert "us-east-1" in output

    def test_shows_failures_when_present(self) -> None:
        result = _result(
            failures=[AnalyzerFailure(analyzer="broken", error_type="RuntimeError", message="boom")]
        )
        output = TerminalReporter().render(result)
        assert "broken" in output
        assert "RuntimeError" in output
        assert "boom" in output

    def test_omits_failures_section_when_none(self) -> None:
        output = TerminalReporter().render(_result([_finding()]))
        assert "failed" not in output.lower()

    def test_detail_mode_shows_fix_suggestions(self) -> None:
        result = _result([_finding(fix_suggestion="Restart the cluster gracefully.")])
        output = TerminalReporter(show_fix_suggestions=True).render(result)
        assert "Restart the cluster gracefully" in output

    def test_zero_savings_finding_does_not_show_dollar_amount(self) -> None:
        result = _result([_finding(savings=0)])
        output = TerminalReporter().render(result)
        # Should still appear in the table
        assert "Idle m5.large" in output


# ---------------------------------------------------------------------------
# Markdown reporter
# ---------------------------------------------------------------------------


class TestMarkdownReporter:
    def test_starts_with_h1_title(self) -> None:
        output = MarkdownReporter().render(_result())
        assert output.startswith("# AWS Cost Audit Report")

    def test_summary_table_includes_severity_breakdown(self) -> None:
        result = _result([_finding(savings=2000), _finding(savings=100), _finding(savings=5)])
        output = MarkdownReporter().render(result)
        assert "HIGH" in output
        assert "MEDIUM" in output
        assert "LOW" in output
        assert "**Total**" in output

    def test_clean_account_shows_clean_message(self) -> None:
        output = MarkdownReporter().render(_result())
        assert "No cost waste detected" in output

    def test_each_finding_gets_its_own_section(self) -> None:
        result = _result([_finding(title="Idle EC2 #1"), _finding(title="Idle EC2 #2")])
        output = MarkdownReporter().render(result)
        assert "### 1. " in output
        assert "### 2. " in output

    def test_finding_section_includes_fix_suggestion(self) -> None:
        result = _result([_finding(fix_suggestion="Terminate and stop the bleeding.")])
        output = MarkdownReporter().render(result)
        assert "Terminate and stop the bleeding" in output

    def test_failures_table_present_when_failures_exist(self) -> None:
        result = _result(
            failures=[
                AnalyzerFailure(analyzer="ec2_idle", error_type="AccessDenied", message="no perms")
            ]
        )
        output = MarkdownReporter().render(result)
        assert "## Analyzer failures" in output
        assert "AccessDenied" in output

    def test_pipe_in_failure_message_is_escaped(self) -> None:
        result = _result(failures=[AnalyzerFailure(analyzer="x", error_type="E", message="a|b|c")])
        output = MarkdownReporter().render(result)
        assert "a\\|b\\|c" in output

    def test_account_id_and_region_in_header(self) -> None:
        output = MarkdownReporter().render(_result())
        assert "123456789012" in output
        assert "us-east-1" in output


# ---------------------------------------------------------------------------
# JSON reporter
# ---------------------------------------------------------------------------


class TestJsonReporter:
    def test_output_is_valid_json(self) -> None:
        output = JsonReporter().render(_result([_finding()]))
        # Should not raise
        json.loads(output)

    def test_top_level_keys(self) -> None:
        output = JsonReporter().render(_result([_finding()]))
        payload = json.loads(output)
        for key in (
            "schema_version",
            "tool_version",
            "generated_at",
            "account_id",
            "region",
            "scan_duration_seconds",
            "summary",
            "findings",
            "failures",
        ):
            assert key in payload, f"missing top-level key: {key}"

    def test_summary_totals(self) -> None:
        result = _result([_finding(savings=100), _finding(savings=250)])
        payload = json.loads(JsonReporter().render(result))
        assert payload["summary"]["total_findings"] == 2
        assert payload["summary"]["total_monthly_savings_usd"] == 350.0

    def test_findings_include_metadata(self) -> None:
        finding = _finding(metadata={"max_cpu_percent": 4.2, "instance_type": "m5.large"})
        payload = json.loads(JsonReporter().render(_result([finding])))
        assert payload["findings"][0]["metadata"]["max_cpu_percent"] == 4.2
        assert payload["findings"][0]["metadata"]["instance_type"] == "m5.large"

    def test_severity_is_string(self) -> None:
        payload = json.loads(JsonReporter().render(_result([_finding(savings=1000)])))
        assert payload["findings"][0]["severity"] == "HIGH"
        assert isinstance(payload["findings"][0]["severity"], str)

    def test_compact_mode_produces_single_line(self) -> None:
        output = JsonReporter(indent=None).render(_result([_finding()]))
        assert "\n" not in output

    def test_indented_mode_pretty_prints(self) -> None:
        output = JsonReporter(indent=2).render(_result([_finding()]))
        assert "\n" in output
        assert "  " in output

    def test_empty_account_produces_valid_output(self) -> None:
        payload = json.loads(JsonReporter().render(_result()))
        assert payload["findings"] == []
        assert payload["failures"] == []
        assert payload["summary"]["total_findings"] == 0
