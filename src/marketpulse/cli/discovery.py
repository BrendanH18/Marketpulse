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
@click.option(
    "--exclude-option", "excluded_options", multiple=True, help="Exclude commands accepting this option (e.g. --json)."
)
@click.option("--leaves", is_flag=True, help="Only executable leaf commands.")
@click.option("--groups", is_flag=True, help="Only command groups.")
@click.option("--depth", type=click.IntRange(min=1), help="Maximum command nesting depth.")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable command catalog.")
@click.option("--jsonl", "as_jsonl", is_flag=True, help="Emit matching commands as JSON Lines.")
@click.option("--csv", "as_csv", is_flag=True, help="Export command catalog to CSV.")
@click.option("--markdown", is_flag=True, help="Export a Markdown command reference.")
@click.option("--count", is_flag=True, help="Count matching commands before pagination.")
@click.option("--limit", type=click.IntRange(min=1), help="Maximum rows to show.")
@click.option("--offset", type=click.IntRange(min=0), default=0, help="Skip matching rows.")
@click.option(
    "--sort",
    "sort_by",
    type=click.Choice(["command", "depth", "params"]),
    default="command",
    help="Order matching commands.",
)
@click.option("--descending", is_flag=True, help="Reverse command order.")
@click.option("--details", is_flag=True, help="Include parameter names, flags, types and help.")
@click.option("--exact", help="Select one complete command path, ignoring case and extra spaces.")
@click.option("--prefix", help="Match a command path prefix, ignoring case.")
@click.option("--exclude-group", "excluded_groups", multiple=True, help="Exclude a group and its descendants; repeat.")
@click.option("--min-depth", type=click.IntRange(min=1), help="Minimum command nesting depth.")
@click.option(
    "--has-arguments/--no-arguments", default=None, help="Select commands with or without positional arguments."
)
@click.option("--has-options/--no-options", default=None, help="Select commands with or without options.")
@click.option("--has-required/--no-required", default=None, help="Select commands with or without required parameters.")
@click.option("--param-type", help="Select commands having a parameter of this Click type, ignoring case.")
@click.option("--parameter-search", help="Find parameter names, flags, types or help containing this text.")
@click.option("--page-info", is_flag=True, help="With --json, include total, offset and limit before pagination.")
@click.option("--paths", is_flag=True, help="Print only command paths, one per line, for scripts.")
def commands(
    group_name,
    search,
    option_name,
    excluded_options,
    leaves,
    groups,
    depth,
    as_json,
    as_jsonl,
    as_csv,
    markdown,
    count,
    limit,
    offset,
    sort_by,
    descending,
    details,
    exact,
    prefix,
    excluded_groups,
    min_depth,
    has_arguments,
    has_options,
    has_required,
    param_type,
    parameter_search,
    page_info,
    paths,
) -> None:
    """Browse commands and options without opening the ledger or contacting providers."""
    if sum((as_json, as_jsonl, as_csv, markdown, count, paths)) > 1:
        raise click.UsageError("Choose one of --json, --jsonl, --csv, --markdown, --count or --paths.")
    if page_info and not as_json:
        raise click.UsageError("--page-info requires --json.")
    if paths and details:
        raise click.UsageError("--paths cannot be combined with --details.")
    if min_depth is not None and depth is not None and min_depth > depth:
        raise click.UsageError("--min-depth must be at most --depth.")
    if leaves and groups:
        raise click.UsageError("Choose --leaves or --groups.")
    if count and (limit is not None or offset):
        raise click.UsageError("--count cannot be combined with pagination.")
    rows = _catalog(main)
    for label, value in (
        ("--exact", exact),
        ("--prefix", prefix),
        ("--parameter-search", parameter_search),
        ("--param-type", param_type),
    ):
        if value is not None and not value.strip():
            raise click.BadParameter("Cannot be blank.", param_hint=label)
    if any(not value.strip() for value in excluded_options):
        raise click.BadParameter("Cannot be blank.", param_hint="--exclude-option")
    excluded = {" ".join(value.split()) for value in excluded_groups}
    valid_groups = {r["command"] for r in rows if r["group"]}
    if excluded - valid_groups:
        raise click.BadParameter("Unknown command group.", param_hint="--exclude-group")
    if excluded:
        rows = [r for r in rows if not any(r["command"] == g or r["command"].startswith(g + " ") for g in excluded)]
    if exact is not None:
        wanted = " ".join(exact.split()).casefold()
        rows = [r for r in rows if r["command"].casefold() == wanted]
    if prefix is not None:
        wanted = " ".join(prefix.split()).casefold()
        rows = [r for r in rows if r["command"].casefold().startswith(wanted)]
    if group_name:
        group_name = " ".join(group_name.split())
        if group_name not in valid_groups:
            raise click.BadParameter("Unknown command group.", param_hint="--group")
        rows = [r for r in rows if r["command"] == group_name or r["command"].startswith(group_name + " ")]
    if search:
        rows = [r for r in rows if search.casefold() in (r["command"] + " " + r["help"]).casefold()]
    if option_name:
        flag = option_name if option_name.startswith("-") else "--" + option_name
        rows = [r for r in rows if any(flag in p["flags"] for p in r["parameters"] if p["kind"] == "option")]
    if excluded_options:
        excluded_flags = {
            opt.strip() if opt.strip().startswith("-") else "--" + opt.strip() for opt in excluded_options
        }
        rows = [
            r
            for r in rows
            if not any(flag in excluded_flags for p in r["parameters"] if p["kind"] == "option" for flag in p["flags"])
        ]
    wanted_type = param_type.strip().casefold() if param_type is not None else None
    rows = [
        r
        for r in rows
        if (not leaves or not r["group"])
        and (not groups or r["group"])
        and (depth is None or r["depth"] <= depth)
        and (min_depth is None or r["depth"] >= min_depth)
        and (has_arguments is None or any(p["kind"] == "argument" for p in r["parameters"]) == has_arguments)
        and (has_options is None or any(p["kind"] == "option" for p in r["parameters"]) == has_options)
        and (has_required is None or any(p["required"] for p in r["parameters"]) == has_required)
        and (wanted_type is None or any(p["type"].casefold() == wanted_type for p in r["parameters"]))
        and (
            parameter_search is None
            or any(
                parameter_search.strip().casefold()
                in " ".join([p["name"] or "", *p["flags"], p["type"], p["help"] or ""]).casefold()
                for p in r["parameters"]
            )
        )
    ]
    if count:
        click.echo(len(rows))
        return
    if sort_by == "depth":
        rows.sort(key=lambda r: (r["depth"], r["command"]), reverse=descending)
    elif sort_by == "params":
        rows.sort(key=lambda r: (len(r["parameters"]), r["command"]), reverse=descending)
    else:
        rows.sort(key=lambda r: r["command"], reverse=descending)
    total = len(rows)
    rows = rows[offset:][:limit]
    if paths:
        for row in rows:
            click.echo(row["command"])
        return
    if not details:
        rows = [{k: v for k, v in r.items() if k != "parameters"} for r in rows]
    if as_json:
        payload = {"rows": rows, "total": total, "offset": offset, "limit": limit} if page_info else rows
        click.echo(json.dumps(payload, ensure_ascii=False))
    elif as_jsonl:
        for row in rows:
            click.echo(json.dumps(row, ensure_ascii=False))
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
