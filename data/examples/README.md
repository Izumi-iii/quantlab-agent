# Example data

All files in this directory are synthetic and exist only to demonstrate and test the application.

- `DEMO_A.csv` and `DEMO_B.csv` are valid daily examples with matching dates.
- `DEMO_GROWTH.csv` trends upward with modest day-to-day movement.
- `DEMO_DRAWDOWN.csv` rises first, falls sharply, then partially recovers.
- `DEMO_VOLATILE.csv` has larger alternating moves for volatility testing.
- `DEMO_FLAT.csv` stays close to 100 for low-volatility comparisons.
- `DEMO_PARTIAL_OVERLAP.csv` starts later than `DEMO_A.csv`, useful for common-date alignment tests.
- `DEMO_SHORT.csv` has only three observations, useful for short-sample warnings.
- `INVALID_DUPLICATE.csv` contains a conflicting duplicate date and must be rejected.
- `INVALID_MISSING_CLOSE.csv` is missing the required `close` column and must be rejected.
- `INVALID_NEGATIVE_PRICE.csv` contains a non-positive close and must be rejected.

The values do not describe real securities and must not be used for investment conclusions.
