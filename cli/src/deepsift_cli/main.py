"""`deepsift` command: runs installed services locally and shows results as they arrive."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import typer
from deepsift_sdk import EntityType, Event, EventKind, Level
from deepsift_sdk.local import LocalRun, discover
from rich.console import Console, Group
from rich.live import Live
from rich.table import Table
from rich.text import Text

app = typer.Typer(
    help="DeepSift: OSINT investigations from the terminal. Work in progress.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()

LEVEL_STYLE = {Level.HIGH: "bold green", Level.MEDIUM: "yellow", Level.LOW: "dim"}
LEVEL_LABEL = {Level.HIGH: "high", Level.MEDIUM: "medium", Level.LOW: "low"}

ServicesOpt = Annotated[
    list[str] | None,
    typer.Option("--service", "-s", help="Only run this service (repeatable)."),
]
OutputOpt = Annotated[
    Path | None, typer.Option("--output", "-o", help="Save findings as JSON to this file.")
]
MinLevelOpt = Annotated[
    Level, typer.Option("--min", help="Hide findings below this confidence level.")
]


@dataclass
class Lane:
    """Live state of one service, drawn as a row of the sieve."""

    status: str = "waiting"
    done: int = 0
    total: int = 0
    found: int = 0


def _lanes_table(lanes: dict[str, Lane]) -> Table:
    table = Table(title="The sieve", title_justify="left", expand=False, box=None)
    table.add_column("Service", style="bold")
    table.add_column("Status")
    table.add_column("Progress", justify="right")
    table.add_column("Found", justify="right", style="magenta")
    for name, lane in lanes.items():
        progress = f"{lane.done}/{lane.total}" if lane.total else ""
        table.add_row(name, lane.status, progress, str(lane.found))
    return table


def _update(lanes: dict[str, Lane], event: Event) -> None:
    lane = lanes.setdefault(event.service, Lane())
    match event.event:
        case EventKind.STARTED:
            lane.status = "running"
        case EventKind.PROGRESS:
            lane.done, lane.total = event.done or 0, event.total or 0
        case EventKind.ENTITY:
            lane.found += 1
        case EventKind.COMPLETED:
            lane.status = "[green]done[/]"
        case EventKind.FAILED:
            lane.status = f"[red]failed: {event.error.code.value}[/] {event.error.message}"


def _results_table(run: LocalRun, min_level: Level) -> Table:
    order = [Level.HIGH, Level.MEDIUM, Level.LOW]
    keep = order[: order.index(min_level) + 1]
    table = Table(title="Findings", title_justify="left")
    table.add_column("Site")
    table.add_column("Value", overflow="fold")
    table.add_column("Found by")
    table.add_column("Confidence")
    for finding in run.findings:
        if finding.level not in keep:
            continue
        site = str(finding.entity.attributes.get("site", finding.entity.type.value))
        table.add_row(
            site,
            finding.entity.value,
            ", ".join(sorted(finding.sources)),
            Text(
                f"{LEVEL_LABEL[finding.level]} ({finding.score:.2f})",
                style=LEVEL_STYLE[finding.level],
            ),
        )
    return table


def _save(run: LocalRun, path: Path) -> None:
    payload = {
        "selector": run.input.model_dump(mode="json") if run.input else None,
        "findings": [
            {
                "entity": f.entity.model_dump(mode="json"),
                "sources": f.sources,
                "score": f.score,
                "level": f.level.value,
            }
            for f in run.findings
        ],
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


async def _investigate(
    selector: str, entity_type: EntityType | None, only: list[str] | None
) -> LocalRun:
    services = {name: cls() for name, cls in discover().items()}
    run = LocalRun(services)
    lanes: dict[str, Lane] = {}
    with Live(_lanes_table(lanes), console=console, refresh_per_second=8, transient=False) as live:
        async for event in run.run(selector, entity_type=entity_type, only=only):
            _update(lanes, event)
            live.update(_lanes_table(lanes))
    if not lanes:
        kind = run.input.type.value if run.input else "this selector"
        console.print(f"[yellow]No installed service accepts {kind}.[/] Run `deepsift services`.")
    return run


def _run(
    selector: str,
    entity_type: EntityType | None,
    services: list[str] | None,
    output: Path | None,
    min_level: Level,
) -> None:
    try:
        run = asyncio.run(_investigate(selector, entity_type, services))
    except ValueError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(2) from exc
    if run.input is not None:
        console.print(f"\n[bold]{run.input.type.value}[/] [cyan]{run.input.value}[/]")
    console.print(Group(_results_table(run, min_level)))
    if output:
        _save(run, output)
        console.print(f"Saved {len(run.findings)} findings to {output}")


@app.command()
def user(
    username: str,
    service: ServicesOpt = None,
    output: OutputOpt = None,
    min_level: MinLevelOpt = Level.LOW,
) -> None:
    """Look for a username."""
    _run(username, EntityType.USERNAME, service, output, min_level)


@app.command()
def email(
    address: str,
    service: ServicesOpt = None,
    output: OutputOpt = None,
    min_level: MinLevelOpt = Level.LOW,
) -> None:
    """Look for an email address."""
    _run(address, EntityType.EMAIL, service, output, min_level)


@app.command()
def phone(
    number: str,
    service: ServicesOpt = None,
    output: OutputOpt = None,
    min_level: MinLevelOpt = Level.LOW,
) -> None:
    """Look for a phone number (international format, e.g. +33612345678)."""
    _run(number, EntityType.PHONE, service, output, min_level)


@app.command()
def domain(
    name: str,
    service: ServicesOpt = None,
    output: OutputOpt = None,
    min_level: MinLevelOpt = Level.LOW,
) -> None:
    """Look for a domain."""
    _run(name, EntityType.DOMAIN, service, output, min_level)


@app.command()
def search(
    selector: str,
    service: ServicesOpt = None,
    output: OutputOpt = None,
    min_level: MinLevelOpt = Level.LOW,
) -> None:
    """Detect the selector's type, then run every matching service."""
    _run(selector, None, service, output, min_level)


@app.command()
def services() -> None:
    """List installed services."""
    installed = discover()
    if not installed:
        console.print("No service installed. Try `pip install deepsift[sherlock]`.")
        return
    table = Table(title="Installed services", title_justify="left")
    for column in ("Service", "Version", "Accepts", "Returns", "State"):
        table.add_column(column)
    for name, cls in sorted(installed.items()):
        manifest = cls.get_manifest()
        missing = manifest.missing_secrets()
        state = f"[yellow]needs {', '.join(missing)}[/]" if missing else "[green]ready[/]"
        table.add_row(
            name,
            manifest.version,
            ", ".join(t.value for t in manifest.inputs),
            ", ".join(t.value for t in manifest.outputs),
            state,
        )
    console.print(table)


if __name__ == "__main__":
    app()
