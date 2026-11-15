### Seven new summary operations

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
