# Command line

`bt` is the command-line program of the backtester. A strategy file says what to buy. `bt run` runs one strategy file, or a batch of them, on the same trade dates and writes one result file for each. Other commands read the result files. This page is for scripts and command-line users.

Every command prints one JSON document, pretty-printed over several lines (the examples below are compacted). An error prints `{"error": {"message": "...", "place": "..."}}` and ends with status 1. Only `--help` and `--version` print text. The examples write `bt`; from a source checkout, `cargo run -q -p bt --` does the same.

## What bt needs

A run needs a home: a folder that holds the raw provider files (`raw/`) and the prepared data (`data/prepared/`). Every command accepts `--home HOME_DIR`. Without it, `bt` uses the folder above the folder that holds the `bt` program. Preparing the data is not the subject of this page: a run on a home with no prepared data stops with "... is not prepared: run `bt data prepare`".

```bash
bt data status --home HOME_DIR
```

For each market (`us`, `hk`, `jp`), the reply shows whether raw data exists and the prepared generation: `as_of`, `first_session`, `last_session` and `companies`. A run window must end on or before `last_session`. `bt data status`, `bt run`, `bt screen` and `bt catalog` read the home. `bt check`, `bt export tables`, `bt export holdings` and `bt explore` need no home.

## A strategy file

A strategy file is JSON. This one keeps the companies with a market cap of at least one billion dollars outside Financial Services, then holds the three with the highest EBITDA yield:

```json
{
  "sleeves": [
    {"steps": [
      {"filter": "Market cap in dollars", "op": ">=", "value": "1000000000"},
      {"filter": "Sector", "op": "is not", "value": "Financial Services"},
      {"rank": "EBITDA yield", "order": "highest", "from": 1, "to": 3}
    ]}
  ]
}
```

The rules:
- A strategy file has `sleeves`. A sleeve has `steps`, and a `name` when the file has two or more sleeves. Each sleeve needs a Rank step.
- A sleeve runs its steps in order on all candidates. The candidates of a day are the companies of the market that pass its screen on that day: they have a usable report and price. Each step sees only what the steps before it kept.
- A Filter step is `{"filter": SOURCE, "op": OP, "value": THRESHOLD}`. `op` is `<`, `<=`, `>` or `>=`. A candidate with no value for the source fails the Filter.
- `Sector` and `Exchange` are text. They take `is` or `is not` and a text value with the exact spelling and case of the market's data. `bt check` needs no market data, so it accepts any text. `bt run`, `bt screen` and `bt export cross-section` refuse an `is` value that no company of the market has, and name `bt catalog`. An `is not` value that no company has is accepted.
- A Rank step is `{"rank": SOURCE, "order": "highest" or "lowest", "from": A, "to": B}`. It orders the candidates that have a value and keeps the positions A to B, with 1 <= A <= B. A candidate with no value is left out.
- A source is a name from `bt catalog` (case and repeated spaces do not matter), a variable of the file, or formula text. For example, the free-cash-flow yield is named `FCF yield`, in percent: `"5"` means 5%.

A threshold is decimal text in the display of its source. A plain JSON number is also accepted. The display is in the catalog (`display`) and in the reply of `bt check`. Two traps:
- `Market cap` is in millions of dollars: `"1000"` is one billion dollars. `Market cap in dollars` is in whole dollars: `"1000000000"` is one billion dollars. The same holds for `Enterprise value` and `Enterprise value in dollars`.
- A percent source takes the percent number: `"15"` means 15%, not `"0.15"`.

Results and exports hold values in whole dollars and as fractions (0.15 is 15%), not in millions or percent. The exception is `contribution`, in percentage points.

A strategy with several sleeves runs each sleeve on all candidates. The picks join into one portfolio of equal weights. A company that two sleeves pick is held once. The ranks of the joined picks count from 1 in sleeve order.

```json
{
  "sleeves": [
    {"name": "Cheap", "steps": [
      {"rank": "EV/EBITDA", "order": "lowest", "from": 1, "to": 3}
    ]},
    {"name": "Profitable", "steps": [
      {"filter": "Sector", "op": "is", "value": "Technology"},
      {"rank": "Net margin", "order": "highest", "from": 1, "to": 3}
    ]}
  ]
}
```

### Variables and formulas

`variables` maps a name to a formula, and `display` is optional. A step names the variable as its source:

```json
{
  "variables": {
    "Cash cover": {"formula": "Cash and equivalents / positive(Current liabilities)", "display": "multiple"}
  },
  "sleeves": [
    {"steps": [
      {"filter": "Cash cover", "op": ">", "value": "0.5"},
      {"filter": "ROE", "op": ">", "value": "15"},
      {"rank": "Cash cover", "order": "highest", "from": 1, "to": 3}
    ]}
  ]
}
```

- A variable name must not be a name of the catalog or another variable's name. A formula can use the variables above it.
- A formula has a unit, and `display` must be a display of that unit (`units` in the catalog). Without `display`, the default display of the unit applies. The default of a ratio is `percent`: in `Revenue / Net income`, the threshold `"5"` means 5%, which is the ratio 0.05. Write `"display": "multiple"` for a plain ratio.
- A name inside a formula reads the quantity in its own unit: dollars in whole dollars and a ratio as a fraction. The same name as a whole step reads the built-in in its display. `ROE` as a step with `"15"` means 15%. In the step `ROE * 2`, ROE is 0.15 and the step is in percent, so `"30"` means 30%: `bt check` shows `stored` 15.0 for the first and 0.3 for the second.
- A step can also hold formula text directly. It is shown in the default display of its unit, and only a variable can choose another display.
- A catalog name with `step_only` true can be a whole step but not part of a formula.

The catalog lists the names, formula functions, units and limits. Print it:

```bash
bt catalog --market us --home HOME_DIR
```

The reply is one JSON document. A row of `names`:

```text
{"name": "Market cap", "kind": "built-in", "unit": "USD", "display": "usd_million", "step_only": false}
```

The reply has `names`, one row like this for each source name: `kind` is `built-in`, `input`, `measure` or `field`, `display` is the display of a threshold, and `step_only` is described above. It also has `functions` and `operators` (how to write a formula), `units` (the displays that each formula unit allows, and its default), `limits` (the largest sizes the program accepts), and `sectors` and `exchanges` (the text values of this market's companies). To list names in a script, read the JSON, for example `[n["name"] for n in catalog["names"] if n["kind"] == "built-in"]`.

## Checking a file

```bash
bt check value.json two.json
```

`bt check` reads strategy files without market data. For each file it prints `canonical` (the compact form), `identity` (the SHA-256 of the canonical form: two files that mean the same have the same identity), `variables`, and for each sleeve its steps. A step shows its `source` (`kind` and the name as the catalog spells it), `unit`, `display` and, for a number Filter, `stored`, the threshold as the program compares it. For a number Filter of `value.json` it prints:

```text
{"step": "filter", "source": {"kind": "field", "name": "Market cap in dollars"}, "unit": "USD", "display": "usd", "stored": 1000000000.0}
```

The first file that is refused stops the command with status 1, and `place` names the file, the step and, in a formula, the characters. For a step with the source `Market capp`, in `bad.json`:

```text
{"error": {"message": "“Market capp” is not a known name or a variable of this file. Did you mean “Market cap”?", "place": "bad.json: sleeves[1].steps[1], characters 1–11"}}
```

## Running

```bash
bt run value.json --market us --start 2021-07-01 --end 2023-06-28 --every 6m --home HOME_DIR --out value-out
```

`--market` is `us`, `hk` or `jp`. The window starts on the first session on or after `--start` and ends on the last session on or before `--end`. The last period exits at the end of the window. Choose one schedule:

| Schedule | Arguments | Trials |
|---|---|---|
| Fixed | `--every 13w` or `--every 3m` | 1 |
| Random | `--every 3m --random 24 --seed 7` | `--random` |
| Explicit | `--dates 2021-07-01,2022-01-03,2022-09-01` | 1 |

- A random trial trades on one random session in every interval. `--random` needs `--every`. `--seed` needs `--random`. Without `--seed`, `bt` draws one and reports it as `seed`. The same seed, settings and prepared data give the same dates and the same results again.
- `--dates` cannot be combined with `--every` or `--random`. Explicit dates are sessions, in increasing order, from the first session of the window and before its last one.
- A random or explicit trial holds cash at 0% from the start of the window to its first trade.

`--out` must be a folder that is new or empty. `bt run` writes `<out>/<file name without extension>.sqlite` for each strategy file, so two files in one batch must not have the same name.

Give several strategy files to run them as one batch. The script at the end of this page writes `variants/pe-20.json` and `variants/pe-30.json`:

```bash
bt run variants/pe-20.json variants/pe-30.json --market us --start 2021-07-01 \
  --end 2023-06-28 --every 3m --random 24 --seed 1 --home HOME_DIR --out out
```

A batch runs every file on the same trade dates, so a difference between the results comes from the strategy files. This is the fast way to compare variants. A file gives the same result alone or in a batch. The reply, trimmed:

```text
{"market": "us",
 "schedule": {"start": "2021-07-01", "end": "2023-06-28", "random": {"every": {"months": 3}, "trials": 24, "seed": 1}},
 "seed": 1, "generation": 1, "as_of": "2023-06-30T07:30:00+00:00", "seconds": 0.138,
 "runs": [
  {"file": "variants/pe-20.json", "result": "out/pe-20.sqlite", "identity": "07b7dab9...0bd1",
   "cagr": [0.20442863965307168, 0.31863415235653636, ...],
   "median": 0.2231423980113897, "worst": 0.17427889225150506, "best": 0.3515725426415688,
   "spy_median": 0.3497105377847103, "beat_spy": 2, "min_holdings": 2},
  {"file": "variants/pe-30.json", ...}]}
```

- `schedule` repeats the settings, with the seed. `generation` and `as_of` name the prepared data that the batch read. `seconds` is the program's own time for the whole batch. `runs` has one entry for each file, in the order given (a shell glob sorts the names).
- `cagr` has the compound annual growth rate of each trial, in trial order (trials are numbered from 1), from the first session of the window to its last. It is a fraction: 0.20 is 20% a year.
- `median`, `worst` and `best` are the median, lowest and highest `cagr`. `spy_median` is the median of SPY's CAGR over the same trials. `beat_spy` is the number of trials whose CAGR is above SPY's.
- `min_holdings` is the fewest holdings in any period of any trial. A value below the picks that the strategy asks for (the size of the last Rank step, or the sum of these sizes over the sleeves) means a period had fewer picks. `0` means a period held cash.

A run stops with an error and status 1, and writes no result file for any file of the batch, when:

- an argument is wrong (`place` is `arguments` or the argument);
- a strategy file is refused (`place` starts with the file), including an `is` text value that no company of the market has;
- the `--out` folder is not new or empty, or two files have the same name;
- the schedule does not fit the data: `end` after `last_session`, or an explicit date that is not a session;
- a selected company has no valid exit price (`place` is the file, the market, the trial, the entry day and the symbol);
- a formula with `at(X, DATE)` has a `DATE` after the entry day of a candidate.

## Reading results

The next commands read result files and need no home and no market data.

```bash
bt export tables out/pe-20.sqlite out/pe-30.sqlite --out tables
```

`--out` must be new or empty. The folder gets `manifest.json` and one `.jsonl` file for each table, with one JSON row on each line. Every row starts with `case`, the name of the result file without extension. The reply gives the number of rows for each table. The tables, with their keys:

- `trials` (`case`, `trial`): one row for each trial, with its `cagr` and SPY's.
- `statistics` (`case`, `statistic`): the `value` of each statistic over the trials, such as `cagr.median` and `beat_spy`.
- `periods` (`case`, `trial`, `period`): the entry, the exit and the returns of each period.
- `holdings` (`case`, `trial`, `period`, `rank`): one row for each holding, with its `return`, `weight` and `contribution`, and also its `status`, `ranking_value` and `sleeve`. `return` is the holding's return from its entry to its exit in US dollars; how dividends and prices enter it is in [Dividends](research-workflow.md#dividends).
- `steps` (`case`, `trial`, `period`, `rank`, `sleeve`, `step`): the `value` that each step read for a holding.
- `curve` (`case`, `trial`, `period`, `day`): the return to date on each day of a period.
- `growth` (`case`, `trial`, `day`) and `band` (`case`, `day`): the value of 1 for the strategy and for SPY on each day, and its median, lowest and highest over the trials.
- `sectors` (`case`, `trial`, `sector`) and `contributions` (`case`, `trial`, `period`): the share of each sector in the holdings, and the gains and losses of each period.

Every row names its columns: read a row by the names of its fields.

```bash
bt export holdings out/pe-30.sqlite --out holdings
```

This writes the `holdings` table only, with one more column for each number source of the steps, named `source:` and the source (for example `source:EBITDA yield`).

```bash
bt explore out/pe-30.sqlite --trial 1 --periods 2-5 --ranks 1-2
```

`bt explore` totals one trial over the periods A to B (counted from 1) and the holdings with the ranks A to B. The ranks must be inside the ranks of the strategy. The reply has the window (`start`, `end`), `total_return`, `growth`, `cagr`, their SPY values, `cash_days`, `empty` and `short`. `--trial all` totals all trials of a random run: the reply has `statistics`, named as in the `statistics` table, and `trials`. A fixed or explicit run has trial 1 only.

```bash
bt screen value.json --market us --home HOME_DIR
```

`bt screen` selects with the strategy file on the latest session of the market. The reply has `day`, `identity` and `picks`. Each pick has `rank`, `symbol`, `name`, `sector`, `ranking_value` and `steps`: for each step, its `value` and, for a Rank step, its `step_rank`.

### Cross-section

```bash
bt export cross-section cover.json --market us --start 2021-07-01 --end 2023-06-28 --every 6m --home HOME_DIR --out cross
```

`bt export cross-section` is for studying a variable against the next period's returns over every candidate of the entry days, which a run selects from, not only the holdings. It takes one strategy file, `--market`, `--out` and a schedule as `bt run` does (`--every`, `--random` with `--seed`, or `--dates`), and it needs the home. It ignores the steps, but the file must still pass `bt check`: each sleeve needs a Rank step. The reply has `schedule`, `seed`, `generation`, `as_of` and `rows`, the number of rows written.

`--out` gets `manifest.json` and `cross_section.jsonl`. The table `cross_section` has one row for every candidate of each period's entry day. Its key is `day` (the entry day), `exit` and `symbol`; a period that several trials share is written once. The columns are:

- the candidate's fields: `name`, `sector`, `exchange`, `candidate_rank` (a US tie rank; empty in `hk` and `jp` rows), `fiscal`, `entry`, `market_cap`, `enterprise_value`, `ebitda`, `ebitda_yield`, `ev_ebitda` and `spread`, in whole dollars or as fractions;
- the built-in values, one column for each built-in, named by its id, for example `filter:pe`, `filter:roe` and `metric:ev_ebitda:multiple`, as fractions or plain numbers;
- `variable:<name>`, one column for each variable of the file, such as `variable:Cash cover`, in the unit of the formula;
- `return`, the return from the entry to the exit of the period. It is null when the candidate has no valid exit price, or enters on or after the exit.

A value is null when the candidate has no value for it. A formula error stops the command as it stops a run. A missing exit price does not: it gives a null `return`.

## A loop for a script

The script below writes variants of one strategy that differ in one threshold, checks them, runs them as one batch, prints the medians and exports the tables of the best one. Replace `HOME_DIR` in the script with your home folder. A variant file looks like this:

```json
{"sleeves": [{"steps": [{"filter": "P/E", "op": "<", "value": "20"}, {"rank": "EBITDA yield", "order": "highest", "from": 1, "to": 3}]}]}
```

```python
import json, pathlib, subprocess

HOME = "HOME_DIR"  # replace with your home folder

def bt(*args):
    done = subprocess.run(["bt", *args], capture_output=True, text=True)
    reply = json.loads(done.stdout)
    if done.returncode:
        raise SystemExit(f"{reply['error']['place']}: {reply['error']['message']}")
    return reply

pathlib.Path("variants").mkdir(exist_ok=True)
files = []
for pe in (10, 15, 20, 25, 30, 40):
    steps = [{"filter": "P/E", "op": "<", "value": str(pe)},
             {"rank": "EBITDA yield", "order": "highest", "from": 1, "to": 3}]
    path = f"variants/pe-{pe}.json"
    pathlib.Path(path).write_text(json.dumps({"sleeves": [{"steps": steps}]}))
    files.append(path)

bt("check", *files)
reply = bt("run", *files, "--market", "us", "--start", "2021-07-01", "--end", "2023-06-28",
           "--every", "3m", "--random", "24", "--seed", "1", "--home", HOME, "--out", "loop-out")
runs = sorted(reply["runs"], key=lambda r: r["median"], reverse=True)
for r in runs:
    print(f"{r['file']:20} median {r['median']:.3f}  worst {r['worst']:.3f}  best {r['best']:.3f}"
          f"  SPY {r['spy_median']:.3f}  beat {r['beat_spy']:2}  holdings {r['min_holdings']}")
bt("export", "tables", runs[0]["result"], "--out", "loop-best")
```

The output of the script:

```text
variants/pe-30.json  median 0.258  worst 0.200  best 0.394  SPY 0.350  beat  3  holdings 2
variants/pe-40.json  median 0.228  worst 0.172  best 0.351  SPY 0.350  beat  3  holdings 2
...
```

The folder `loop-best` then holds the tables of `variants/pe-30.json`. Before each new run, remove `loop-out` and `loop-best` or choose other folder names, because `--out` must be new or empty. Change the values in the `for` line, or the strategy, to run other variants. Twenty variants are twenty files in one `bt run`.
