"""Smoke tests for the CLI surface."""

from __future__ import annotations

from typer.testing import CliRunner

from cost_optimizer.cli import app

runner = CliRunner()


def test_version_command() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "aws-cost-audit" in result.stdout


def test_analyze_stub_runs() -> None:
    result = runner.invoke(app, ["analyze", "--region", "us-east-1"])
    assert result.exit_code == 0


def test_help_runs() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "analyze" in result.stdout
