# One thousand offline improvements

[User guide](usage.md) · [Report operations so far](cli-report-expansion.md) ·
[CLI improvements](cli-thousand-improvements.md) · [Terminal app improvements](tui-thousand-improvements.md) ·
[Issue #153](https://github.com/BrendanH18/Marketpulse/issues/153)

This batch adds exactly 1,000 features and improvements, counted the way the
earlier report batches (#137 to #146) were counted:

| Part | Count | How it is counted |
| --- | ---: | --- |
| [10 derived-field functions](#ten-derived-field-functions-570) for `--derive` | 570 | 10 functions × 57 datasets |
| [7 summary operations](#seven-summary-operations-399) for `summarize --metric` | 399 | 7 operations × 57 datasets |
| [16 CLI improvements](cli-thousand-improvements.md) | 16 | one each |
| [15 terminal app improvements](tui-thousand-improvements.md) | 15 | one each |
| **Total** | **1,000** | |

The 969 report items are combinations of 17 shared operations with the 57
datasets, not 969 unrelated features. `marketpulse report report-operations`
now lists 197 shared operations: numbers 181–190 are the derive functions and
191–197 the summary operations below. The 31 standalone improvements are listed
one by one in their own guides.

What stays the same: everything here is offline and read-only apart from the
CLI writes it guards; no financial calculation (ACB, FX, tax, valuation or
contribution room) changes; archived accounts stay hidden and API keys stay
redacted; `status --json` and the desktop bridge are unchanged.

## Ten derived-field functions (570)

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
[Derived fields](cli-report-derived-datasets.md#functions).

```bash
# End of the 30-day window after each sale (fictional data).
marketpulse report transactions --where type=SELL --derive window_end=add-days:date:30 --fields date,symbol,window_end
# Positions listed on the TSX, counted.
marketpulse summarize positions --derive tsx=ends-with:symbol:.TO --group-by tsx --metric positions=count
```

## Seven summary operations (399)

`marketpulse summarize SOURCE --metric NAME=OP:FIELD` gains seven operations. Each reads one
field, works on every dataset, and appears after the earlier fifty in `report summary-operations`,
`summarize SOURCE --describe` and `report report-operations` (issue 153). Numeric operations read
finite numbers and numeric strings, never booleans, NaN or infinity, exactly as the other number
operations do; the percentiles use the same inclusive, linearly interpolated method as `number-q1`
and `number-q3`.

| # | Operation | Field | Result | Description |
| --- | --- | --- | --- | --- |
| 1 | `number-p10` | required | decimal | Inclusive 10th percentile of finite numbers, interpolated like the quartiles; null without numbers. |
| 2 | `number-p90` | required | decimal | Inclusive 90th percentile of finite numbers, interpolated like the quartiles; null without numbers. |
| 3 | `number-iqr` | required | decimal | Third quartile minus first quartile of finite numbers, exact; null without numbers. |
| 4 | `number-mean-absolute-deviation` | required | decimal | Mean absolute distance of finite numbers from their mean, rounded once to 28 significant digits; null without numbers. |
| 5 | `present-percent` | required | decimal | Percentage of values that are not null or an empty string, rounded once to 28 significant digits; null without rows. |
| 6 | `date-distinct` | required | integer | Number of distinct calendar days among date values, as written; 0 without dates. |
| 7 | `longest-text` | required | string | Longest string by character count, the first in source order on ties; null without strings. |

The seven operations on all 57 datasets make 7 × 57 = 399 dataset/operation combinations.
