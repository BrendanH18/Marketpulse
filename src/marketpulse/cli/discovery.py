"""Offline command discovery from Click's registered command tree."""

from __future__ import annotations

import csv
import io
import json
from typing import Any

import click

from .root import main


def _catalog(group: click.Group, prefix: str = "", depth: int = 1) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name, command in sorted(group.commands.items()):
        if command.hidden:
            continue
        path = f"{prefix} {name}".strip()
        params = []
        for param in command.params:
            if isinstance(param, click.Option) and param.hidden:
                continue
            params.append(
                {
                    "name": param.name,
                    "kind": "option" if isinstance(param, click.Option) else "argument",
                    "flags": param.opts + param.secondary_opts,
                    "required": param.required,
                    "type": param.type.name,
                    "help": param.help if isinstance(param, click.Option) else "",
                }
            )
        rows.append(
            {
                "command": path,
                "group": isinstance(command, click.Group),
                "depth": depth,
                "help": " ".join((command.help or "").split()),
                "parameters": params,
            }
        )
        if isinstance(command, click.Group):
            rows.extend(_catalog(command, path, depth + 1))
    return rows


@main.command("commands")
@click.option("--group", "group_name", help="Only this command group and its descendants.")
@click.option("--search", help="Find text in command paths and help, ignoring case.")
@click.option("--option", "option_name", help="Find commands accepting this option (e.g. --json).")
@click.option("--leaves", is_flag=True, help="Only executable leaf commands.")
@click.option("--groups", is_flag=True, help="Only command groups.")
@click.option("--depth", type=click.IntRange(min=1), help="Maximum command nesting depth.")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable command catalog.")
@click.option("--csv", "as_csv", is_flag=True, help="Export command catalog to CSV.")
@click.option("--markdown", is_flag=True, help="Export a Markdown command reference.")
@click.option("--count", is_flag=True, help="Count matching commands before pagination.")
@click.option("--limit", type=click.IntRange(min=1), help="Maximum rows to show.")
@click.option("--offset", type=click.IntRange(min=0), default=0, help="Skip matching rows.")
@click.option("--descending", is_flag=True, help="Reverse alphabetical command order.")
@click.option("--details", is_flag=True, help="Include parameter names, flags, types and help.")
def commands(
    group_name,
    search,
    option_name,
    leaves,
    groups,
    depth,
    as_json,
    as_csv,
    markdown,
    count,
    limit,
    offset,
    descending,
    details,
) -> None:
    """Browse commands and options without opening the ledger or contacting providers."""
    if sum((as_json, as_csv, markdown, count)) > 1:
        raise click.UsageError("Choose one of --json, --csv, --markdown or --count.")
    if leaves and groups:
        raise click.UsageError("Choose --leaves or --groups.")
    if count and (limit is not None or offset):
        raise click.UsageError("--count cannot be combined with pagination.")
    rows = _catalog(main)
    if group_name:
        group_name = " ".join(group_name.split())
        if not any(r["command"] == group_name and r["group"] for r in rows):
            raise click.BadParameter("Unknown command group.", param_hint="--group")
        rows = [r for r in rows if r["command"] == group_name or r["command"].startswith(group_name + " ")]
    if search:
        rows = [r for r in rows if search.casefold() in (r["command"] + " " + r["help"]).casefold()]
    if option_name:
        flag = option_name if option_name.startswith("-") else "--" + option_name
        rows = [r for r in rows if any(flag in p["flags"] for p in r["parameters"] if p["kind"] == "option")]
    rows = [
        r
        for r in rows
        if (not leaves or not r["group"]) and (not groups or r["group"]) and (depth is None or r["depth"] <= depth)
    ]
    if count:
        click.echo(len(rows))
        return
    rows.sort(key=lambda r: r["command"], reverse=descending)
    rows = rows[offset:][:limit]
    if not details:
        rows = [{k: v for k, v in r.items() if k != "parameters"} for r in rows]
    if as_json:
        click.echo(json.dumps(rows, ensure_ascii=False))
    elif as_csv:
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(
            stream, fieldnames=["command", "group", "depth", "help"] + (["parameters"] if details else [])
        )
        writer.writeheader()
        for r in rows:
            writer.writerow(
                {**r, **({"parameters": json.dumps(r["parameters"], ensure_ascii=False)} if details else {})}
            )
        click.echo(stream.getvalue(), nl=False)
    else:
        if markdown:
            click.echo("| Command | Help |\n| --- | --- |")
        for r in rows:
            parameter_details = []
            if details:
                for p in r["parameters"]:
                    label = ", ".join(p["flags"]) or p["name"]
                    parameter_details.append(
                        f"{label} ({p['type']}{', required' if p['required'] else ''}) {p['help']}"
                    )
            if markdown:
                help_text = r["help"]
                if parameter_details:
                    help_text += "<br>" + "<br>".join(parameter_details)
                help_text = help_text.replace("|", "&#124;")
                click.echo(f"| `marketpulse {r['command']}` | {help_text} |")
            else:
                click.echo(f"{r['command']}  {r['help']}")
                for detail in parameter_details:
                    click.echo("  " + detail)
