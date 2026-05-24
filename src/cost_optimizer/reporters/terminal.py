"""Terminal reporter — pretty output for interactive CLI use.

Uses ``rich`` to produce a colored, well-aligned table of findings.
This is what users see by default when they run ``cost-optimizer
analyze`` without an ``--output`` flag.
"""

from __future__ import annotations

import io
from typing import TYPE_CHECKING

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from cost_optimizer.core import Severity
from cost_optimizer.reporters.base import Reporter

if TYPE_CHECKING:
    from cost_optimizer.core.orchestrator import ScanResult


_SEVERITY_STYLE: dict[Severity, str] = {
    Severity.HIGH: "bold red",
    Severity.MEDIUM: "yellow",
    Severity.LOW: "dim",
}


class TerminalReporter(Reporter):
    """Render findings as a colored rich table for stdout."""

    def __init__(self, *, show_fix_suggestions: bool = False) -> None:
        # Fix suggestions get long; off by default for the summary table.
        # Users can pass --detail to a finding or use `cost-optimizer detail`.
        self.show_fix_suggestions = show_fix_suggestions

    def render(self, result: ScanResult) -> str:
        # Render into an in-memory buffer so the result is a plain string.
        # The CLI can decide whether to print, log, or capture it.
        buffer = io.StringIO()
        console = Console(file=buffer, force_terminal=True, width=120)

        console.print(self._build_header(result))
        console.print()

        if not result.findings:
            console.print("[green]No cost waste detected. Account looks clean.[/]")
        else:
            console.print(self._build_table(result))

        if result.failures:
            console.print()
            console.print(self._build_failures(result))

        console.print()
        console.print(self._build_footer(result))

        return buffer.getvalue()

    def _build_header(self, result: ScanResult) -> Panel:
        title = Text("AWS Cost Audit Report", style="bold cyan")
        body = Text()
        body.append("Account: ", style="dim")
        body.append(result.account_id or "unknown")
        body.append("    Region: ", style="dim")
        body.append(result.region)
        return Panel(body, title=title, title_align="left", border_style="cyan")

    def _build_table(self, result: ScanResult) -> Table:
        table = Table(
            show_header=True,
            header_style="bold",
            border_style="dim",
            expand=False,
        )
        table.add_column("#", justify="right", style="dim", width=3)
        table.add_column("Finding", overflow="fold")
        table.add_column("Resource", style="dim")
        table.add_column("Savings/mo", justify="right")
        table.add_column("Severity", justify="center")

        for i, finding in enumerate(result.findings, start=1):
            sev_style = _SEVERITY_STYLE[finding.severity]
            savings = (
                f"${finding.monthly_savings_usd:,.0f}"
                if finding.monthly_savings_usd > 0
                else "[dim]—[/]"
            )
            table.add_row(
                str(i),
                finding.title,
                finding.resource_id,
                savings,
                Text(finding.severity.value, style=sev_style),
            )

        if self.show_fix_suggestions:
            # Detailed mode: append fix suggestions below the table.
            table.add_section()
            for i, finding in enumerate(result.findings, start=1):
                table.add_row(
                    str(i),
                    Text(f"Fix: {finding.fix_suggestion}", style="dim italic"),
                    "",
                    "",
                    "",
                )

        return table

    def _build_failures(self, result: ScanResult) -> Panel:
        text = Text()
        for fail in result.failures:
            text.append(f"• {fail.analyzer}: ", style="bold yellow")
            text.append(f"{fail.error_type}: {fail.message}\n", style="yellow")
        return Panel(
            text,
            title=f"[yellow]{len(result.failures)} analyzer(s) failed[/]",
            title_align="left",
            border_style="yellow",
        )

    def _build_footer(self, result: ScanResult) -> Text:
        text = Text()
        text.append("Estimated monthly savings: ", style="dim")
        text.append(
            f"${result.total_monthly_savings_usd:,.0f}",
            style="bold green",
        )
        text.append(f"   ({len(result.findings)} finding(s), ", style="dim")
        text.append(f"scan took {result.duration_seconds:.1f}s)", style="dim")
        return text
