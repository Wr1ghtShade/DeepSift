"""`deepsift` command: runs installed services locally and shows results as they arrive."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any

import typer
from deepsift_sdk import EntityType, Event, EventKind, Level
from deepsift_sdk.local import MAX_DEPTH, LocalRun, discover
from rich.console import Console
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
#: Intermediate entities used for correlation, kept in the JSON export but not in the table.
HIDDEN_TYPES = {EntityType.IMAGE, EntityType.IMAGE_HASH}

ServicesOpt = Annotated[
    list[str] | None,
    typer.Option("--service", "-s", help="Only run this service on the selector (repeatable)."),
]
OutputOpt = Annotated[
    Path | None, typer.Option("--output", "-o", help="Save findings as JSON to this file.")
]
MinLevelOpt = Annotated[
    Level, typer.Option("--min", help="Hide findings below this confidence level.")
]
OptOpt = Annotated[
    list[str] | None,
    typer.Option(
        "--opt",
        help="Service option as service.option=value, e.g. maigret.top_sites=0 (repeatable).",
    ),
]
DepthOpt = Annotated[
    int,
    typer.Option(
        "--depth",
        "-d",
        min=0,
        max=MAX_DEPTH,
        help="Pivot hops: run services on what was found (0 = selector only).",
    ),
]


def parse_options(pairs: list[str] | None, installed: dict) -> dict[str, dict[str, Any]]:
    """Turn ``service.option=value`` pairs into per-service options, typed by the manifest."""
    options: dict[str, dict[str, Any]] = {}
    for pair in pairs or []:
        name, _, value = pair.partition("=")
        service, _, option = name.partition(".")
        if not (service and option and _):
            raise ValueError(f"--opt expects service.option=value, got {pair!r}")
        if service not in installed:
            raise ValueError(f"unknown service in --opt: {service}")
        spec = installed[service].get_manifest().options.get(option)
        if spec is None:
            raise ValueError(f"{service} has no option {option!r}")
        options.setdefault(service, {})[option] = _coerce(spec, value, pair)
    return options


def _coerce(spec: Any, value: str, pair: str) -> Any:
    if spec.type == "int":
        try:
            return int(value)
        except ValueError as exc:
            raise ValueError(f"{pair}: expected an integer") from exc
    if spec.type == "bool":
        lowered = value.lower()
        if lowered not in ("true", "false", "1", "0", "yes", "no", "on", "off"):
            raise ValueError(f"{pair}: expected true or false")
        return lowered in ("true", "1", "yes", "on")
    if spec.type == "enum" and spec.values and value not in spec.values:
        raise ValueError(f"{pair}: expected one of {', '.join(map(str, spec.values))}")
    return value


@dataclass
class Lane:
    """Live state of one service, drawn as a row of the sieve."""

    tasks: set[str] = field(default_factory=set)
    finished: int = 0
    failed: int = 0
    last_error: str = ""
    done: int = 0
    total: int = 0
    found: int = 0

    @property
    def status(self) -> str:
        running = len(self.tasks) - self.finished
        if running > 0:
            return f"running ({running})" if len(self.tasks) > 1 else "running"
        if self.failed and self.failed == len(self.tasks):
            return f"[red]failed[/] {self.last_error}"
        if self.failed:
            return f"[green]done[/] [yellow]({self.failed} failed)[/]"
        return "[green]done[/]"

    @property
    def progress(self) -> str:
        if self.total:
            return f"{self.done}/{self.total}"
        if len(self.tasks) > 1:
            return f"{self.finished}/{len(self.tasks)} tasks"
        return ""


def _lanes_table(lanes: dict[str, Lane]) -> Table:
    table = Table(title="The sieve", title_justify="left", expand=False, box=None)
    table.add_column("Service", style="bold")
    table.add_column("Status")
    table.add_column("Progress", justify="right")
    table.add_column("Found", justify="right", style="magenta")
    for name, lane in lanes.items():
        table.add_row(name, lane.status, lane.progress, str(lane.found))
    return table


def _update(lanes: dict[str, Lane], event: Event) -> None:
    lane = lanes.setdefault(event.service, Lane())
    match event.event:
        case EventKind.STARTED:
            lane.tasks.add(event.task_id)
        case EventKind.PROGRESS:
            lane.done, lane.total = event.done or 0, event.total or 0
        case EventKind.ENTITY:
            lane.found += 1
        case EventKind.COMPLETED:
            lane.finished += 1
        case EventKind.FAILED:
            lane.finished += 1
            lane.failed += 1
            lane.last_error = f"{event.error.code.value}: {event.error.message}"


def _results_table(run: LocalRun, min_level: Level) -> Table:
    order = [Level.HIGH, Level.MEDIUM, Level.LOW]
    keep = order[: order.index(min_level) + 1]
    table = Table(title="Findings", title_justify="left")
    table.add_column("Site")
    table.add_column("Value", overflow="fold")
    table.add_column("Found by")
    table.add_column("Avatar", justify="center")
    table.add_column("Confidence")
    for finding in run.findings:
        if finding.level not in keep or finding.entity.type in HIDDEN_TYPES:
            continue
        entity = finding.entity
        site = str(entity.attributes.get("site", entity.type.value))
        if entity.type is EntityType.IDENTITY:
            site = f"name ({site})"
        table.add_row(
            site,
            entity.value,
            ", ".join(sorted(finding.sources)),
            Text(finding.avatar_group or "", style="bold cyan"),
            Text(f"{finding.level.value} ({finding.score:.2f})", style=LEVEL_STYLE[finding.level]),
        )
    return table


def _groups_note(run: LocalRun) -> str:
    lines = []
    for group in run.avatar_groups:
        sites = []
        for key in group.profiles:
            finding = run.finding(key)
            sites.append(str(finding.entity.attributes.get("site", key[1])) if finding else key[1])
        lines.append(f"Avatar {group.name}: same picture on {', '.join(sites)}")
    return "\n".join(lines)


def _save(run: LocalRun, path: Path) -> None:
    payload = {
        "selector": run.input.model_dump(mode="json") if run.input else None,
        "findings": [
            {
                "entity": f.entity.model_dump(mode="json"),
                "sources": f.sources,
                "score": f.score,
                "level": f.level.value,
                "avatar_group": f.avatar_group,
            }
            for f in run.findings
        ],
        "links": [
            {"from": list(link.source), "rel": link.rel, "to": list(link.target)}
            for link in run.links
        ],
        "avatar_groups": [
            {"name": g.name, "profiles": [list(k) for k in g.profiles], "phashes": list(g.phashes)}
            for g in run.avatar_groups
        ],
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


async def _investigate(
    selector: str,
    entity_type: EntityType | None,
    only: list[str] | None,
    depth: int,
    opts: list[str] | None,
) -> LocalRun:
    installed = discover()
    options = parse_options(opts, installed)
    services = {name: cls() for name, cls in installed.items()}
    run = LocalRun(services, max_depth=depth)
    lanes: dict[str, Lane] = {}
    with Live(_lanes_table(lanes), console=console, refresh_per_second=8, transient=False) as live:
        async for event in run.run(selector, entity_type=entity_type, only=only, options=options):
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
    depth: int,
    opts: list[str] | None,
) -> None:
    try:
        run = asyncio.run(_investigate(selector, entity_type, services, depth, opts))
    except ValueError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(2) from exc
    if run.input is not None:
        console.print(f"\n[bold]{run.input.type.value}[/] [cyan]{run.input.value}[/]")
    console.print(_results_table(run, min_level))
    note = _groups_note(run)
    if note:
        console.print(note, style="cyan")
    if output:
        _save(run, output)
        console.print(f"Saved {len(run.findings)} findings to {output}")


@app.command()
def user(
    username: str,
    service: ServicesOpt = None,
    output: OutputOpt = None,
    min_level: MinLevelOpt = Level.LOW,
    depth: DepthOpt = 1,
    opt: OptOpt = None,
) -> None:
    """Look for a username."""
    _run(username, EntityType.USERNAME, service, output, min_level, depth, opt)


@app.command()
def email(
    address: str,
    service: ServicesOpt = None,
    output: OutputOpt = None,
    min_level: MinLevelOpt = Level.LOW,
    depth: DepthOpt = 1,
    opt: OptOpt = None,
) -> None:
    """Look for an email address."""
    _run(address, EntityType.EMAIL, service, output, min_level, depth, opt)


@app.command()
def phone(
    number: str,
    service: ServicesOpt = None,
    output: OutputOpt = None,
    min_level: MinLevelOpt = Level.LOW,
    depth: DepthOpt = 1,
    opt: OptOpt = None,
) -> None:
    """Look for a phone number (international format, e.g. +33612345678)."""
    _run(number, EntityType.PHONE, service, output, min_level, depth, opt)


@app.command()
def domain(
    name: str,
    service: ServicesOpt = None,
    output: OutputOpt = None,
    min_level: MinLevelOpt = Level.LOW,
    depth: DepthOpt = 1,
    opt: OptOpt = None,
) -> None:
    """Look for a domain."""
    _run(name, EntityType.DOMAIN, service, output, min_level, depth, opt)


@app.command()
def image(
    url: str,
    service: ServicesOpt = None,
    output: OutputOpt = None,
    min_level: MinLevelOpt = Level.LOW,
    depth: DepthOpt = 1,
    opt: OptOpt = None,
) -> None:
    """Look into an image URL."""
    _run(url, EntityType.IMAGE, service, output, min_level, depth, opt)


@app.command()
def search(
    selector: str,
    service: ServicesOpt = None,
    output: OutputOpt = None,
    min_level: MinLevelOpt = Level.LOW,
    depth: DepthOpt = 1,
    opt: OptOpt = None,
) -> None:
    """Detect the selector's type, then run every matching service."""
    _run(selector, None, service, output, min_level, depth, opt)


@app.command()
def services() -> None:
    """List installed services."""
    installed = discover()
    if not installed:
        console.print("No service installed. Try `pip install deepsift[all]`.")
        return
    table = Table(title="Installed services", title_justify="left")
    for column in ("Service", "Version", "Accepts", "Returns", "State"):
        table.add_column(column)
    for name, cls in sorted(installed.items()):
        manifest = cls.get_manifest()
        missing = manifest.missing_secrets()
        optional = manifest.missing_optional_secrets()
        if missing:
            state = f"[yellow]needs {', '.join(missing)}[/]"
        elif optional:
            state = f"[green]ready[/] [dim](better with {', '.join(optional)})[/]"
        else:
            state = "[green]ready[/]"
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
