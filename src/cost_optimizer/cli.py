"""Command-line interface."""

from __future__ import annotations

import logging
import sys
from enum import Enum
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.logging import RichHandler

from cost_optimizer import __version__
from cost_optimizer.analyzers import ALL_ANALYZERS
from cost_optimizer.aws.client import AwsClient
from cost_optimizer.core import Orchestrator
from cost_optimizer.reporters import JsonReporter, MarkdownReporter, TerminalReporter

app = typer.Typer(
    name="cost-optimizer",
    help="Find waste in AWS accounts.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()


class OutputFormat(str, Enum):
    """Supported output formats for the analyze command."""

    TERMINAL = "terminal"
    MARKDOWN = "markdown"
    JSON = "json"


def _configure_logging(verbose: bool) -> None:
    """Set up structured logging via rich."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=console, rich_tracebacks=True)],
    )


@app.callback()
def main(
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Enable debug logging.")] = False,
) -> None:
    """aws-cost-audit — find waste in AWS accounts."""
    _configure_logging(verbose)


@app.command()
def version() -> None:
    """Print version and exit."""
    console.print(f"aws-cost-audit [bold cyan]{__version__}[/]")


@app.command()
def analyze(
    profile: Annotated[
        str | None,
        typer.Option(help="AWS profile name. Falls back to default credential chain."),
    ] = None,
    region: Annotated[str, typer.Option(help="AWS region to scan.")] = "us-east-1",
    ai_mode: Annotated[
        bool,
        typer.Option("--ai-mode", help="Focus on AI workload waste (GPU, inference)."),
    ] = False,
    output_format: Annotated[
        OutputFormat,
        typer.Option(
            "--format",
            "-f",
            help="Output format. Defaults to terminal if no --output file given.",
        ),
    ] = OutputFormat.TERMINAL,
    output: Annotated[
        Path | None,
        typer.Option(
            "--output",
            "-o",
            help="Write report to a file. Defaults to printing to stdout.",
        ),
    ] = None,
    detail: Annotated[
        bool,
        typer.Option(
            "--detail",
            help="Include full fix suggestions in terminal output (verbose).",
        ),
    ] = False,
) -> None:
    """Run a cost analysis on an AWS account."""
    # Build the AWS client and orchestrator.
    aws_client = AwsClient(profile=profile, region=region)
    orchestrator = Orchestrator(aws_client)

    if not ALL_ANALYZERS:
        console.print("[red]No analyzers registered — this is a bug.[/]")
        raise typer.Exit(code=1)

    # Run the scan. Per-analyzer failures are captured inside; we don't
    # need a try/except here.
    result = orchestrator.run(ALL_ANALYZERS, ai_mode=ai_mode)

    # Choose reporter.
    reporter: TerminalReporter | MarkdownReporter | JsonReporter
    if output_format is OutputFormat.MARKDOWN:
        reporter = MarkdownReporter()
    elif output_format is OutputFormat.JSON:
        reporter = JsonReporter()
    else:
        reporter = TerminalReporter(show_fix_suggestions=detail)

    rendered = reporter.render(result)

    # Write or print.
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
        console.print(f"[green]Report written to[/] [bold]{output}[/]")
        console.print(
            f"[dim]{len(result.findings)} finding(s), "
            f"${result.total_monthly_savings_usd:,.0f}/mo estimated savings.[/]"
        )
    else:
        # Terminal reporter has its own colored output; print as-is.
        # Markdown/JSON go to stdout unformatted.
        if output_format is OutputFormat.TERMINAL:
            # The terminal reporter rendered to its own console; print raw.
            sys.stdout.write(rendered)
        else:
            console.print(rendered, markup=False, highlight=False)

    # Exit code: non-zero only if all analyzers failed. Findings themselves
    # are informational, not error conditions.
    if result.failures and not result.findings:
        raise typer.Exit(code=2)


if __name__ == "__main__":
    app()
