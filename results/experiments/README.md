# Prepared-data experiments

These reports are separate from the canonical `results/summary-exits.txt`.

- `top100-2015-2020.json`: an example top-100 query for six January books using the original 250-candidate screen and current last-price exit treatment. It includes the full selected holdings and settings. Additional early stops outside the original top 50 have not received the earlier manual bankruptcy review.
- `performance.json`: measured local preparation/query/build timings for the new data layer. These are observations from this environment, not performance guarantees.

Regenerate the sample with:

```bash
python3 scripts/research.py screen --top 100 --first 2015 --last 2020 --output results/experiments/top100-2015-2020.json
```

The first January book has fewer than 100 usable names in the original 250-candidate pool. Full-universe top-100 claims require broader price coverage and exit review. Use `status` and inspect short-year output before interpreting an experiment.
