# Two hundred offline discovery improvements

[User guide](usage.md) · [Report operations](cli-composable-reports.md) ·
[Issue #162](https://github.com/BrendanH18/Marketpulse/issues/162)

This batch adds **exactly 200 improvements** using the same dataset × operation
counting convention as earlier reporting batches: **one new dataset × 197 existing
shared operations, plus three CLI typo suggestions = 200**. These are 197 new
combinations of existing operations with a dataset, not 197 new operations.
The registry now has 58 datasets; the shared operation catalog stays at 197.

`report-fields` lists the field names of every registered report dataset,
including itself. It contains program metadata only: it opens no tracker,
reads no portfolio, and makes no network requests. Rows follow
source registration order and each source's schema order.

| Field | Meaning |
| --- | --- |
| `source` | Report dataset name. |
| `group` | Dataset family, such as portfolio, reference or system. |
| `position` | One-based field position within that source's schema. |
| `field` | Field name accepted by report and summary options. |

Find datasets containing a currency column:

```bash
marketpulse report report-fields --where field=currency --fields source,group
```

List the holdings schema in column order:

```bash
marketpulse report report-fields --where source=holdings --sort position
```

Count fields by dataset:

```bash
marketpulse summarize report-fields --group-by source --metric fields=count
```

Close misspellings of a report source, summary source or derived-field function
now suggest a valid spelling. Suggestions appear in the error message only;
the command still fails with exit code 2 and never runs a guessed command.
For example, `report report-fiels` suggests `report-fields`.

## Numbered inventory

Entries 1–197 apply the existing catalog operations to `report-fields`. Operations
accepted by both commands count once, as in earlier inventories. Syntax uses the
same placeholders as `report report-operations`: replace FIELD with a schema
field, NAME with an output column name, and other uppercase tokens with values.
Summary options require a metric; `--descending` requires a sort field and
`--format lines` requires one output column.

| No. | Dataset | Family | Syntax |
| --- | --- | --- | --- |
| 1 | `report-fields` | projection | `--fields FIELD,FIELD` |
| 2 | `report-fields` | projection | `--omit FIELD,FIELD` |
| 3 | `report-fields` | filter | `--where FIELD=VALUE` |
| 4 | `report-fields` | filter | `--not FIELD=VALUE` |
| 5 | `report-fields` | filter | `--contains FIELD=TEXT` |
| 6 | `report-fields` | filter | `--prefix FIELD=TEXT` |
| 7 | `report-fields` | filter | `--suffix FIELD=TEXT` |
| 8 | `report-fields` | filter | `--present FIELD` |
| 9 | `report-fields` | filter | `--missing FIELD` |
| 10 | `report-fields` | sort | `--sort FIELD` |
| 11 | `report-fields` | sort | `--descending` |
| 12 | `report-fields` | page | `--offset N` |
| 13 | `report-fields` | page | `--limit N` |
| 14 | `report-fields` | selection | `--unique FIELD` |
| 15 | `report-fields` | count | `--count` |
| 16 | `report-fields` | format | `--format jsonl` |
| 17 | `report-fields` | format | `--format csv` |
| 18 | `report-fields` | format | `--format tsv` |
| 19 | `report-fields` | format | `--format markdown` |
| 20 | `report-fields` | page | `--page-info` |
| 21 | `report-fields` | filter | `--ieq FIELD=TEXT` |
| 22 | `report-fields` | filter | `--ine FIELD=TEXT` |
| 23 | `report-fields` | filter | `--not-contains FIELD=TEXT` |
| 24 | `report-fields` | filter | `--not-prefix FIELD=TEXT` |
| 25 | `report-fields` | filter | `--not-suffix FIELD=TEXT` |
| 26 | `report-fields` | filter | `--gt FIELD=NUMBER` |
| 27 | `report-fields` | filter | `--ge FIELD=NUMBER` |
| 28 | `report-fields` | filter | `--lt FIELD=NUMBER` |
| 29 | `report-fields` | filter | `--le FIELD=NUMBER` |
| 30 | `report-fields` | filter | `--between FIELD=LOW,HIGH` |
| 31 | `report-fields` | filter | `--outside FIELD=LOW,HIGH` |
| 32 | `report-fields` | filter | `--in FIELD=JSON_ARRAY` |
| 33 | `report-fields` | filter | `--not-in FIELD=JSON_ARRAY` |
| 34 | `report-fields` | filter | `--empty FIELD` |
| 35 | `report-fields` | filter | `--nonempty FIELD` |
| 36 | `report-fields` | filter | `--is-type FIELD=TYPE` |
| 37 | `report-fields` | filter | `--length FIELD=N` |
| 38 | `report-fields` | filter | `--min-length FIELD=N` |
| 39 | `report-fields` | filter | `--max-length FIELD=N` |
| 40 | `report-fields` | filter | `--glob FIELD=PATTERN` |
| 41 | `report-fields` | transform | `--lower FIELD` |
| 42 | `report-fields` | transform | `--upper FIELD` |
| 43 | `report-fields` | transform | `--strip FIELD` |
| 44 | `report-fields` | transform | `--lstrip FIELD` |
| 45 | `report-fields` | transform | `--rstrip FIELD` |
| 46 | `report-fields` | transform | `--replace FIELD=JSON_PAIR` |
| 47 | `report-fields` | transform | `--fill FIELD=JSON` |
| 48 | `report-fields` | transform | `--null-if FIELD=JSON` |
| 49 | `report-fields` | transform | `--stringify FIELD` |
| 50 | `report-fields` | transform | `--encode-json FIELD` |
| 51 | `report-fields` | transform | `--decode-json FIELD` |
| 52 | `report-fields` | transform | `--length-of FIELD` |
| 53 | `report-fields` | transform | `--round FIELD=DIGITS` |
| 54 | `report-fields` | column | `--rename FIELD=NAME` |
| 55 | `report-fields` | column | `--constant NAME=JSON` |
| 56 | `report-fields` | column | `--row-number NAME` |
| 57 | `report-fields` | sort | `--sort-ci FIELD` |
| 58 | `report-fields` | window | `--reverse-rows` |
| 59 | `report-fields` | window | `--tail N` |
| 60 | `report-fields` | window | `--every N` |
| 61 | `report-fields` | summary | `--metric NAME=count` |
| 62 | `report-fields` | summary | `--metric NAME=present:FIELD` |
| 63 | `report-fields` | summary | `--metric NAME=missing:FIELD` |
| 64 | `report-fields` | summary | `--metric NAME=empty:FIELD` |
| 65 | `report-fields` | summary | `--metric NAME=nonempty:FIELD` |
| 66 | `report-fields` | summary | `--metric NAME=distinct:FIELD` |
| 67 | `report-fields` | summary | `--metric NAME=duplicates:FIELD` |
| 68 | `report-fields` | summary | `--metric NAME=first:FIELD` |
| 69 | `report-fields` | summary | `--metric NAME=last:FIELD` |
| 70 | `report-fields` | summary | `--metric NAME=first-present:FIELD` |
| 71 | `report-fields` | summary | `--metric NAME=last-present:FIELD` |
| 72 | `report-fields` | summary | `--metric NAME=mode:FIELD` |
| 73 | `report-fields` | summary | `--metric NAME=mode-count:FIELD` |
| 74 | `report-fields` | summary | `--metric NAME=values:FIELD` |
| 75 | `report-fields` | summary | `--metric NAME=distinct-values:FIELD` |
| 76 | `report-fields` | summary | `--metric NAME=number-count:FIELD` |
| 77 | `report-fields` | summary | `--metric NAME=number-distinct:FIELD` |
| 78 | `report-fields` | summary | `--metric NAME=number-sum:FIELD` |
| 79 | `report-fields` | summary | `--metric NAME=number-min:FIELD` |
| 80 | `report-fields` | summary | `--metric NAME=number-max:FIELD` |
| 81 | `report-fields` | summary | `--metric NAME=number-mean:FIELD` |
| 82 | `report-fields` | summary | `--metric NAME=number-median:FIELD` |
| 83 | `report-fields` | summary | `--metric NAME=number-range:FIELD` |
| 84 | `report-fields` | summary | `--metric NAME=positive-count:FIELD` |
| 85 | `report-fields` | summary | `--metric NAME=negative-count:FIELD` |
| 86 | `report-fields` | summary | `--metric NAME=zero-count:FIELD` |
| 87 | `report-fields` | summary | `--metric NAME=positive-sum:FIELD` |
| 88 | `report-fields` | summary | `--metric NAME=negative-sum:FIELD` |
| 89 | `report-fields` | summary | `--metric NAME=absolute-sum:FIELD` |
| 90 | `report-fields` | summary | `--metric NAME=true-count:FIELD` |
| 91 | `report-fields` | summary | `--metric NAME=false-count:FIELD` |
| 92 | `report-fields` | summary | `--metric NAME=string-count:FIELD` |
| 93 | `report-fields` | summary | `--metric NAME=array-count:FIELD` |
| 94 | `report-fields` | summary | `--metric NAME=object-count:FIELD` |
| 95 | `report-fields` | summary | `--metric NAME=length-sum:FIELD` |
| 96 | `report-fields` | summary | `--metric NAME=length-min:FIELD` |
| 97 | `report-fields` | summary | `--metric NAME=length-max:FIELD` |
| 98 | `report-fields` | summary | `--metric NAME=length-mean:FIELD` |
| 99 | `report-fields` | summary | `--metric NAME=text-min:FIELD` |
| 100 | `report-fields` | summary | `--metric NAME=text-max:FIELD` |
| 101 | `report-fields` | derive | `--derive NAME=year:FIELD` |
| 102 | `report-fields` | derive | `--derive NAME=quarter:FIELD` |
| 103 | `report-fields` | derive | `--derive NAME=month:FIELD` |
| 104 | `report-fields` | derive | `--derive NAME=day:FIELD` |
| 105 | `report-fields` | derive | `--derive NAME=weekday:FIELD` |
| 106 | `report-fields` | derive | `--derive NAME=day-of-year:FIELD` |
| 107 | `report-fields` | derive | `--derive NAME=iso-week:FIELD` |
| 108 | `report-fields` | derive | `--derive NAME=year-month:FIELD` |
| 109 | `report-fields` | derive | `--derive NAME=year-quarter:FIELD` |
| 110 | `report-fields` | derive | `--derive NAME=year-week:FIELD` |
| 111 | `report-fields` | derive | `--derive NAME=month-name:FIELD` |
| 112 | `report-fields` | derive | `--derive NAME=weekday-name:FIELD` |
| 113 | `report-fields` | derive | `--derive NAME=date:FIELD` |
| 114 | `report-fields` | derive | `--derive NAME=month-start:FIELD` |
| 115 | `report-fields` | derive | `--derive NAME=month-end:FIELD` |
| 116 | `report-fields` | derive | `--derive NAME=quarter-start:FIELD` |
| 117 | `report-fields` | derive | `--derive NAME=quarter-end:FIELD` |
| 118 | `report-fields` | derive | `--derive NAME=year-start:FIELD` |
| 119 | `report-fields` | derive | `--derive NAME=year-end:FIELD` |
| 120 | `report-fields` | derive | `--derive NAME=week-start:FIELD` |
| 121 | `report-fields` | derive | `--derive NAME=is-weekend:FIELD` |
| 122 | `report-fields` | derive | `--derive NAME=days-from:FIELD:DATE` |
| 123 | `report-fields` | derive | `--derive NAME=number:FIELD` |
| 124 | `report-fields` | derive | `--derive NAME=abs:FIELD` |
| 125 | `report-fields` | derive | `--derive NAME=negate:FIELD` |
| 126 | `report-fields` | derive | `--derive NAME=sign:FIELD` |
| 127 | `report-fields` | derive | `--derive NAME=floor:FIELD` |
| 128 | `report-fields` | derive | `--derive NAME=ceil:FIELD` |
| 129 | `report-fields` | derive | `--derive NAME=round:FIELD:DIGITS` |
| 130 | `report-fields` | derive | `--derive NAME=bin:FIELD:WIDTH` |
| 131 | `report-fields` | derive | `--derive NAME=add:FIELD:NUMBER` |
| 132 | `report-fields` | derive | `--derive NAME=multiply:FIELD:NUMBER` |
| 133 | `report-fields` | derive | `--derive NAME=add-field:FIELD:FIELD` |
| 134 | `report-fields` | derive | `--derive NAME=subtract-field:FIELD:FIELD` |
| 135 | `report-fields` | derive | `--derive NAME=multiply-field:FIELD:FIELD` |
| 136 | `report-fields` | derive | `--derive NAME=divide-field:FIELD:FIELD` |
| 137 | `report-fields` | derive | `--derive NAME=lower:FIELD` |
| 138 | `report-fields` | derive | `--derive NAME=upper:FIELD` |
| 139 | `report-fields` | derive | `--derive NAME=trim:FIELD` |
| 140 | `report-fields` | derive | `--derive NAME=left:FIELD:N` |
| 141 | `report-fields` | derive | `--derive NAME=before:FIELD:TEXT` |
| 142 | `report-fields` | derive | `--derive NAME=after-last:FIELD:TEXT` |
| 143 | `report-fields` | derive | `--derive NAME=length:FIELD` |
| 144 | `report-fields` | derive | `--derive NAME=text:FIELD` |
| 145 | `report-fields` | derive | `--derive NAME=type:FIELD` |
| 146 | `report-fields` | derive | `--derive NAME=is-missing:FIELD` |
| 147 | `report-fields` | derive | `--derive NAME=coalesce:FIELD:JSON` |
| 148 | `report-fields` | derive | `--derive NAME=equals:FIELD:JSON` |
| 149 | `report-fields` | derive | `--derive NAME=item:FIELD:N` |
| 150 | `report-fields` | derive | `--derive NAME=key:FIELD:NAME` |
| 151 | `report-fields` | filter | `--regex FIELD=PATTERN` |
| 152 | `report-fields` | filter | `--not-regex FIELD=PATTERN` |
| 153 | `report-fields` | filter | `--iglob FIELD=PATTERN` |
| 154 | `report-fields` | filter | `--not-glob FIELD=PATTERN` |
| 155 | `report-fields` | filter | `--contains-any FIELD=JSON_ARRAY` |
| 156 | `report-fields` | filter | `--contains-all FIELD=JSON_ARRAY` |
| 157 | `report-fields` | filter | `--date-from FIELD=YYYY-MM-DD` |
| 158 | `report-fields` | filter | `--date-to FIELD=YYYY-MM-DD` |
| 159 | `report-fields` | filter | `--has-item FIELD=JSON` |
| 160 | `report-fields` | filter | `--has-key FIELD=KEY` |
| 161 | `report-fields` | selection | `--duplicates FIELD` |
| 162 | `report-fields` | selection | `--singletons FIELD` |
| 163 | `report-fields` | selection | `--unique-last FIELD` |
| 164 | `report-fields` | summary | `--metric NAME=date-min:FIELD` |
| 165 | `report-fields` | summary | `--metric NAME=date-max:FIELD` |
| 166 | `report-fields` | summary | `--metric NAME=date-count:FIELD` |
| 167 | `report-fields` | summary | `--metric NAME=date-span:FIELD` |
| 168 | `report-fields` | summary | `--metric NAME=number-variance:FIELD` |
| 169 | `report-fields` | summary | `--metric NAME=number-stdev:FIELD` |
| 170 | `report-fields` | summary | `--metric NAME=number-q1:FIELD` |
| 171 | `report-fields` | summary | `--metric NAME=number-q3:FIELD` |
| 172 | `report-fields` | summary | `--metric NAME=value-counts:FIELD` |
| 173 | `report-fields` | summary | `--metric NAME=repeated-values:FIELD` |
| 174 | `report-fields` | group | `--having FILTER:NAME=VALUE` |
| 175 | `report-fields` | group | `--totals` |
| 176 | `report-fields` | format | `--format html` |
| 177 | `report-fields` | format | `--format text` |
| 178 | `report-fields` | format | `--format records` |
| 179 | `report-fields` | format | `--format lines` |
| 180 | `report-fields` | format | `--format json-columns` |
| 181 | `report-fields` | derive | `--derive NAME=add-days:FIELD:N` |
| 182 | `report-fields` | derive | `--derive NAME=add-months:FIELD:N` |
| 183 | `report-fields` | derive | `--derive NAME=divide:FIELD:NUMBER` |
| 184 | `report-fields` | derive | `--derive NAME=at-least:FIELD:NUMBER` |
| 185 | `report-fields` | derive | `--derive NAME=at-most:FIELD:NUMBER` |
| 186 | `report-fields` | derive | `--derive NAME=percent-of-field:FIELD:FIELD` |
| 187 | `report-fields` | derive | `--derive NAME=right:FIELD:N` |
| 188 | `report-fields` | derive | `--derive NAME=contains:FIELD:TEXT` |
| 189 | `report-fields` | derive | `--derive NAME=starts-with:FIELD:TEXT` |
| 190 | `report-fields` | derive | `--derive NAME=ends-with:FIELD:TEXT` |
| 191 | `report-fields` | summary | `--metric NAME=number-p10:FIELD` |
| 192 | `report-fields` | summary | `--metric NAME=number-p90:FIELD` |
| 193 | `report-fields` | summary | `--metric NAME=number-iqr:FIELD` |
| 194 | `report-fields` | summary | `--metric NAME=number-mean-absolute-deviation:FIELD` |
| 195 | `report-fields` | summary | `--metric NAME=present-percent:FIELD` |
| 196 | `report-fields` | summary | `--metric NAME=date-distinct:FIELD` |
| 197 | `report-fields` | summary | `--metric NAME=longest-text:FIELD` |

| No. | CLI improvement | Example |
| --- | --- | --- |
| 198 | Suggest a close report source name. | `marketpulse report report-fiels` |
| 199 | Suggest a close summary source name. | `marketpulse summarize report-fiels --metric rows=count` |
| 200 | Suggest a close derived-field function name. | `marketpulse report report-fields --derive label=uppper:field` |

## Verification

The shared dataset matrices run their output assertions against all 58 schemas,
including `report-fields`. A separate catalog integration test invokes every one
of the 197 operation syntaxes on the real metadata dataset using each accepting
command. Metadata and CLI tests also exercise actual rows, schema ordering,
filtering, grouping, suggestions and the absence of tracker/network startup.
A documentation inventory check keeps the numbered 200 entries aligned with
the shared operation catalog.
