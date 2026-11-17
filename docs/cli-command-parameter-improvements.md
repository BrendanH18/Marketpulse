# Two hundred offline command discovery improvements

[User guide](usage.md) · [Report operations](cli-composable-reports.md) ·
[Issue #164](https://github.com/BrendanH18/Marketpulse/issues/164)

The `command-parameters` dataset adds 197 combinations with existing report and
summary operations. Three validation messages gain spelling suggestions, bringing
the batch to exactly 200 improvements and the report registry to 59 datasets.

## Find options and arguments

`report command-parameters` returns one row per visible, registered parameter of
the commands listed by `report commands`. The rows follow the same command
order as that catalog, with parameters in registered order for each command.
The catalog uses registered program metadata and runs without opening the
ledger or contacting a provider.

| Field | Meaning |
| --- | --- |
| `command` | Command path, such as `accounts add`. |
| `position` | One-based position among the command's visible parameters. |
| `name` | Parameter name. |
| `kind` | `option` or `argument`. |
| `flags` | Array with a positional argument's name or an option's registered flags, including aliases and paired flags. |
| `required` | Boolean indicating whether the parameter is required. |
| `type` | Click's name for the parameter type. |
| `help` | Registered option help, null for an option without help, or empty text for a positional argument. |

Find commands with a `--dry-run` option and show its help:

```bash
marketpulse report command-parameters --has-item 'flags="--dry-run"' --fields command,help
```

List the required parameters of `accounts add` in registered order:

```bash
marketpulse report command-parameters --where 'command=accounts add' --where required=true --sort position
```

Compare the number of required and optional parameters by command:

```bash
marketpulse summarize command-parameters --group-by command \
  --metric required=true-count:required --metric optional=false-count:required
```

## Numbered inventory

For entries 1–197, each `number` from the shared operation catalog identifies
that same numbered improvement on `command-parameters`. An operation accepted
by both `report` and `summarize` counts once. The `commands` column tells you
which entry points accept each syntax.

```bash
marketpulse report report-operations --fields number,commands,syntax --format markdown
```

| Entries | Operation batch | Count |
| --- | --- | --- |
| 1–20 | [Base reports](cli-composable-reports.md) | 20 |
| 21–60 | [Report refinements](cli-report-improvements.md) | 40 |
| 61–100 | [Summary metrics](cli-report-summaries.md) | 40 |
| 101–150 | [Derived fields](cli-report-derived-datasets.md) | 50 |
| 151–180 | [Report and summary expansion](cli-report-expansion.md) | 30 |
| 181–197 | [Further derived fields and summary metrics](thousand-improvements.md) | 17 |

The last three entries show a close spelling in the validation error. Each
example exits with status 2.

| No. | Input | Suggested spelling |
| --- | --- | --- |
| 198 | `marketpulse summarize sources --metric size=counnt` | `count` |
| 199 | `marketpulse summarize sources --metric size=count --having contains-anyy:size=[]` | `contains-any` |
| 200 | `marketpulse report command-parameters --derive label=upper:commmand` | `command` |
