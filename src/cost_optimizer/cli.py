"""Command-line interface."""

from __future__ import annotations

import logging
from typing import Annotated

import typer
from rich.console import Console
from rich.logging import RichHandler

from cost_optimizer import __version__

app = typer.Typer(
    name="cost-optimizer",
    help="Find waste in AWS accounts.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()


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
        bool, typer.Option("--ai-mode", help="Focus on AI workload waste (GPU, inference).")
    ] = False,
    output: Annotated[
        str | None, typer.Option("--output", "-o", help="Write markdown report to file.")
    ] = None,
) -> None:
    """Run a cost analysis on an AWS account."""
    # Implementation lands in the next commit. Keeping the surface area
    # locked in early so the README, --help, and integration tests are stable.
    console.print(
        f"[yellow]analyze[/] (stub) — profile={profile} region={region} "
        f"ai_mode={ai_mode} output={output}"
    )
    console.print("[dim]Implementation coming in next commit.[/]")


if __name__ == "__main__":
    app()
