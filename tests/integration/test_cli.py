"""Integration tests for the CLI surface."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from cost_optimizer.cli import app

runner = CliRunner()


def test_version_command() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "aws-cost-audit" in result.stdout


def test_help_runs() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "analyze" in result.stdout


def test_analyze_runs_against_mocked_aws(mocked_aws: None) -> None:
    """End-to-end: analyze command runs without exploding."""
    result = runner.invoke(app, ["analyze", "--region", "us-east-1"])
    # No real instances exist in moto, so 0 findings expected; exit 0.
    assert result.exit_code == 0
    # Should produce *some* output (the header at minimum)
    assert len(result.stdout) > 0


def test_analyze_with_markdown_output_to_file(mocked_aws: None, tmp_path: Path) -> None:
    output_file = tmp_path / "report.md"
    result = runner.invoke(
        app,
        ["analyze", "--region", "us-east-1", "--format", "markdown", "--output", str(output_file)],
    )
    assert result.exit_code == 0
    assert output_file.exists()
    content = output_file.read_text()
    assert content.startswith("# AWS Cost Audit Report")


def test_analyze_with_json_output_to_file(mocked_aws: None, tmp_path: Path) -> None:
    output_file = tmp_path / "report.json"
    result = runner.invoke(
        app,
        ["analyze", "--region", "us-east-1", "--format", "json", "--output", str(output_file)],
    )
    assert result.exit_code == 0
    payload = json.loads(output_file.read_text())
    assert payload["schema_version"] == "1.0"
    assert "findings" in payload


def test_analyze_with_ai_mode(mocked_aws: None) -> None:
    """--ai-mode should still run and complete cleanly."""
    result = runner.invoke(app, ["analyze", "--region", "us-east-1", "--ai-mode"])
    assert result.exit_code == 0


def test_analyze_creates_parent_directories(mocked_aws: None, tmp_path: Path) -> None:
    nested = tmp_path / "deep" / "nested" / "report.md"
    result = runner.invoke(
        app,
        ["analyze", "--region", "us-east-1", "--format", "markdown", "--output", str(nested)],
    )
    assert result.exit_code == 0
    assert nested.exists()
