# Documentation

Start with the [project README](../README.md).

## To understand the method

- [Methodology](methodology.md): the original US January study, its universe, exit rules, frozen result and limits.
- [Research workflow](research-workflow.md): market rules, data preparation, screening, schedules, random trials and the data panel.
- [Custom variables](custom-variables.md): the formula language, time rules, variable library and execution.
- [Parameter catalog](parameter-catalog.md): the FMP fields behind each financial input, and the excluded items.

## To read the code

- [Architecture guide](architecture-guide/dist/index.html): a plain-language, offline guide to how the program works, with diagrams and a file map. Open the file in a browser.
- [Source map](source-map.md): which package owns each part of the code.
- [Schedule calendar](schedule-calendar.md): how fixed and random rebalance dates are planned.
- [Portfolio results](portfolio-results.md): the contract for complete dated backtest results.
- [Result evidence](result-evidence.md): the bounded format that stores a result's full evidence.
- [Durable evidence](durable-evidence.md): how the queue and saved library store complete results.
- [Evidence views](evidence-views.md): reading, exploring and exporting stored results.

## To run and deploy it

- [Website](../website/README.md): the pages, the queue, the saved library and the server.
- [Data files](../data/README.md): the local databases and what can be rebuilt.
- [Workspaces](workspaces.md): the WSL source checkout, the native Windows runtime and deployment.
- [Tools](../tools/README.md): deployment, operations and FMP API probes.
- [Command line](command-line.md): how to write a strategy file, and how to check, run and read backtests with the `bt` program.

## Words used in these documents

| Word | Meaning |
|---|---|
| Book | The stock records for one buy date and one sell or mark date. |
| Pool | The set of candidate stocks that a strategy selects from. |
| Sheet | The stored candidate rows of one entry date and one pool. A strategy selects from a sheet. |
| Lane | One named value for each candidate, such as market cap. A Filter or Rank step reads one lane. |
| Scalar | One plain number for a company on a date. |
| Capture | The exact strategy and formulas stored with a run, so the result reopens the same way. |
| Evidence | The complete stored record of a result: its periods, holdings and trials. Reading it calculates nothing. |
| Owner | The one module that defines a rule or a file format. Other code calls it and does not repeat it. |

The architecture guide has a longer list of financial and website words.
