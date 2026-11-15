## Ten new derived-field functions

`--derive NAME=FUNCTION:FIELD:ARGUMENT` gains 10 functions, numbered 51–60 by
`marketpulse report derive-functions` and 181–190 by
`marketpulse report report-operations`. Each works in `report` and `summarize`
on every dataset: **10 × 57 = 570** dataset/operation combinations. They read
saved values offline, never change saved data, and give null for a value they
do not apply to. Invalid arguments are rejected before any data is loaded.

| No. | Function | Argument | Result | Description |
| --- | --- | --- | --- | --- |
| 1 | `add-days` | `N` | string | The date `N` days later; a negative `N` counts back. |
| 2 | `add-months` | `N` | string | The date `N` calendar months later; a day past the end of a shorter month becomes its last day. |
| 3 | `divide` | `NUMBER` | number | The value divided by `NUMBER`, which must not be zero. |
| 4 | `at-least` | `NUMBER` | number | The larger of the value and `NUMBER`. |
| 5 | `at-most` | `NUMBER` | number | The smaller of the value and `NUMBER`. |
| 6 | `percent-of-field` | `FIELD` | number | The value as a percentage of another field's value; null when that value is zero. |
| 7 | `right` | `N` | string | The last `N` characters (`N` from 1 to 999,999,999). |
| 8 | `contains` | `TEXT` | boolean | True when the text contains `TEXT`, matching case. |
| 9 | `starts-with` | `TEXT` | boolean | True when the text starts with `TEXT`, matching case. |
| 10 | `ends-with` | `TEXT` | boolean | True when the text ends with `TEXT`, matching case. |

Dates are read as the existing date functions read them, and a shifted date
outside the years 1 to 9999 is null; `N` for `add-days` and `add-months` is a
whole number from -999,999,999 to 999,999,999. The number functions use the
same 28-digit decimal arithmetic and JSON number rule as the existing ones. The
three text tests compare text exactly as written, unlike the case-insensitive
`--contains`, `--prefix` and `--suffix` filters. Full rules:
[Derived fields](../cli-report-derived-datasets.md#functions).

```bash
# End of the 30-day window after each sale (fictional data).
marketpulse report transactions --where type=SELL --derive window_end=add-days:date:30 --fields date,symbol,window_end
# Positions listed on the TSX, counted.
marketpulse summarize positions --derive tsx=ends-with:symbol:.TO --group-by tsx --metric positions=count
```
