"""Statistics and progress reporting with rich output."""

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    BarColumn,
    TaskProgressColumn,
    TimeRemainingColumn,
)
from rich.table import Table
from rich.text import Text

from .scanner import ScanResult

# Use ASCII-compatible symbols on Windows to avoid encoding issues
if sys.platform == "win32":
    SYM_CHECK = "[OK]"
    SYM_CROSS = "[X]"
    SYM_WARN = "[!]"
else:
    SYM_CHECK = "✓"
    SYM_CROSS = "✗"
    SYM_WARN = "⚠"


@dataclass
class ProcessingStats:
    """Statistics from processing files."""
    total: int = 0
    successful: int = 0
    failed: int = 0
    skipped: int = 0
    verified: int = 0
    verification_failed: int = 0
    
    # Track failures for reporting
    failures: list[tuple[Path, str]] = field(default_factory=list)
    verification_failures: list[tuple[Path, str]] = field(default_factory=list)
    
    @property
    def success_rate(self) -> float:
        if self.total == 0:
            return 0.0
        return (self.successful / self.total) * 100


class Reporter:
    """Rich-based reporter for CLI output."""
    
    def __init__(self, console: Console | None = None):
        self.console = console or Console()
    
    def print_scan_stats(self, result: ScanResult, directory: Path, recursive: bool) -> None:
        """Print statistics about a scan result."""
        # Create stats table
        table = Table(title="Scan Results", show_header=True, header_style="bold cyan")
        table.add_column("Category", style="dim")
        table.add_column("Count", justify="right")
        table.add_column("Status", justify="center")
        
        # Main stats
        table.add_row(
            "Media files with metadata",
            str(result.total_pairs),
            f"[green]{SYM_CHECK} Ready to process[/green]" if result.total_pairs > 0 else "[dim]None[/dim]"
        )
        table.add_row(
            "Orphan JSON files",
            str(result.total_orphan_jsons),
            f"[yellow]{SYM_WARN} No matching media[/yellow]" if result.total_orphan_jsons > 0 else "[dim]None[/dim]"
        )
        table.add_row(
            "Media without metadata",
            str(result.total_orphan_media),
            "[dim]Will be skipped[/dim]" if result.total_orphan_media > 0 else "[dim]None[/dim]"
        )
        table.add_row(
            "Album metadata (skipped)",
            str(len(result.skipped_jsons)),
            "[dim]Not per-image metadata[/dim]" if result.skipped_jsons else "[dim]None[/dim]"
        )
        
        # Print header
        mode = "recursive" if recursive else "single directory"
        self.console.print(Panel(
            f"[bold]Directory:[/bold] {directory}\n[bold]Mode:[/bold] {mode}",
            title="Scan Configuration",
            border_style="blue"
        ))
        
        self.console.print(table)
        self.console.print()
    
    def print_extension_breakdown(self, result: ScanResult) -> None:
        """Print breakdown by file extension."""
        if not result.pairs:
            return
        
        # Count by extension
        ext_counts: dict[str, int] = {}
        for pair in result.pairs:
            ext = pair.media_path.suffix.lower()
            ext_counts[ext] = ext_counts.get(ext, 0) + 1
        
        table = Table(title="Files by Extension", show_header=True, header_style="bold magenta")
        table.add_column("Extension", style="cyan")
        table.add_column("Count", justify="right")
        table.add_column("Percentage", justify="right")
        
        total = len(result.pairs)
        for ext, count in sorted(ext_counts.items(), key=lambda x: -x[1]):
            pct = (count / total) * 100
            table.add_row(ext, str(count), f"{pct:.1f}%")
        
        self.console.print(table)
        self.console.print()
    
    def print_directory_breakdown(self, result: ScanResult, max_dirs: int = 10) -> None:
        """Print breakdown by directory."""
        if not result.pairs:
            return
        
        # Count by directory
        dir_counts: dict[str, int] = {}
        for pair in result.pairs:
            dir_name = pair.media_path.parent.name
            dir_counts[dir_name] = dir_counts.get(dir_name, 0) + 1
        
        table = Table(title="Files by Directory (Top 10)", show_header=True, header_style="bold magenta")
        table.add_column("Directory", style="cyan", max_width=50)
        table.add_column("Count", justify="right")
        
        for dir_name, count in sorted(dir_counts.items(), key=lambda x: -x[1])[:max_dirs]:
            table.add_row(dir_name, str(count))
        
        if len(dir_counts) > max_dirs:
            remaining = len(dir_counts) - max_dirs
            table.add_row(f"... and {remaining} more", "", style="dim")
        
        self.console.print(table)
        self.console.print()
    
    def print_sample_files(self, result: ScanResult, count: int = 5) -> None:
        """Print a sample of files to be processed."""
        if not result.pairs:
            return
        
        self.console.print(f"[bold]Sample files to process:[/bold]")
        for pair in result.pairs[:count]:
            self.console.print(f"  [cyan]{pair.media_name}[/cyan]")
        
        if len(result.pairs) > count:
            remaining = len(result.pairs) - count
            self.console.print(f"  [dim]... and {remaining} more[/dim]")
        
        self.console.print()
    
    def create_progress(self) -> Progress:
        """Create a progress bar for processing."""
        return Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeRemainingColumn(),
            console=self.console,
        )
    
    def print_processing_results(self, stats: ProcessingStats) -> None:
        """Print results after processing."""
        # Status
        if stats.failed == 0 and stats.verification_failed == 0:
            status_style = "green"
            status_icon = SYM_CHECK
            status_text = "All operations completed successfully"
        elif stats.successful > 0:
            status_style = "yellow"
            status_icon = SYM_WARN
            status_text = "Completed with some errors"
        else:
            status_style = "red"
            status_icon = SYM_CROSS
            status_text = "Operation failed"
        
        # Results table
        table = Table(title="Processing Results", show_header=True, header_style="bold cyan")
        table.add_column("Metric", style="dim")
        table.add_column("Count", justify="right")
        table.add_column("Status", justify="center")
        
        table.add_row(
            "Total files",
            str(stats.total),
            ""
        )
        table.add_row(
            "Successful",
            str(stats.successful),
            f"[green]{SYM_CHECK}[/green]" if stats.successful > 0 else "[dim]-[/dim]"
        )
        table.add_row(
            "Failed",
            str(stats.failed),
            f"[red]{SYM_CROSS}[/red]" if stats.failed > 0 else f"[green]{SYM_CHECK}[/green]"
        )
        table.add_row(
            "Skipped",
            str(stats.skipped),
            "[dim]-[/dim]" if stats.skipped > 0 else ""
        )
        
        if stats.verified > 0 or stats.verification_failed > 0:
            table.add_row(
                "Verified",
                str(stats.verified),
                f"[green]{SYM_CHECK}[/green]" if stats.verified > 0 else "[dim]-[/dim]"
            )
            table.add_row(
                "Verification failed",
                str(stats.verification_failed),
                f"[red]{SYM_CROSS}[/red]" if stats.verification_failed > 0 else f"[green]{SYM_CHECK}[/green]"
            )
        
        self.console.print()
        self.console.print(Panel(
            f"[{status_style}]{status_icon} {status_text}[/{status_style}]\n"
            f"Success rate: [bold]{stats.success_rate:.1f}%[/bold]",
            title="Summary",
            border_style=status_style
        ))
        self.console.print(table)
        
        # Print failures if any
        if stats.failures:
            self.console.print()
            self.console.print("[bold red]Failed files:[/bold red]")
            for path, error in stats.failures[:10]:
                self.console.print(f"  [red]{SYM_CROSS}[/red] {path.name}: {error}")
            if len(stats.failures) > 10:
                self.console.print(f"  [dim]... and {len(stats.failures) - 10} more[/dim]")
        
        if stats.verification_failures:
            self.console.print()
            self.console.print("[bold yellow]Verification failures:[/bold yellow]")
            for path, error in stats.verification_failures[:10]:
                self.console.print(f"  [yellow]{SYM_WARN}[/yellow] {path.name}: {error}")
            if len(stats.verification_failures) > 10:
                self.console.print(f"  [dim]... and {len(stats.verification_failures) - 10} more[/dim]")
    
    def print_cleanup_results(self, deleted: int, failed: int, skipped: int) -> None:
        """Print results after cleanup."""
        if failed == 0:
            status = f"[green]{SYM_CHECK} Cleanup completed successfully[/green]"
        else:
            status = f"[yellow]{SYM_WARN} Cleanup completed with errors[/yellow]"
        
        self.console.print()
        self.console.print(Panel(
            f"{status}\n"
            f"Deleted: [bold]{deleted}[/bold] | Failed: [bold]{failed}[/bold] | Skipped: [bold]{skipped}[/bold]",
            title="Cleanup Summary",
            border_style="blue"
        ))
    
    def confirm_action(self, message: str) -> bool:
        """Ask for user confirmation."""
        self.console.print(f"\n[bold yellow]{message}[/bold yellow]")
        response = input("Continue? [y/N]: ").strip().lower()
        return response in ("y", "yes")
    
    def print_error(self, message: str) -> None:
        """Print an error message."""
        self.console.print(f"[bold red]Error:[/bold red] {message}")
    
    def print_warning(self, message: str) -> None:
        """Print a warning message."""
        self.console.print(f"[bold yellow]Warning:[/bold yellow] {message}")
    
    def print_info(self, message: str) -> None:
        """Print an info message."""
        self.console.print(f"[bold blue]Info:[/bold blue] {message}")
    
    def print_success(self, message: str) -> None:
        """Print a success message."""
        self.console.print(f"[bold green]{SYM_CHECK}[/bold green] {message}")

