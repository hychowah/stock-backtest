# Sector selection and result workspaces

Status: complete

The website separates Build strategy, Runs & queue, Saved results and Result
review. Navigation keeps the strategy form mounted. Opening a saved result
shows its recorded settings without changing the draft. Edit a copy restores
settings through the existing held-edit protection.

Review has Overview, Selection and Returns. Recorded settings stay in a desktop
side column and have a phone section. The bottom status bar uses the existing
run and queue owners. Its tray moves the same mounted queue panel.

Selection summarizes every original random trial, then drills into a trial,
rebalance and original stocks. Entry weights average equally across rebalances
within each trial, then equally across complete trials. Unknown sectors and
cash remain visible. Incomplete trials stay visible but do not enter the
combined average. Short books use their actual selection count. Sector filters
preserve recorded ranks, weights and returns.

Sector summaries read on demand through existing acquired-result ownership.
Replies contain compact counts and weights. Inline saved results use the same
aggregation without rewriting records. No financial calculations, durable
formats, market-data access or readiness gates changed.

Current contracts live in [result access](../../evidence-views.md),
[the README](../../../README.md) and
[the architecture guide](../../architecture-guide/dist/index.html).

Verification uses private synthetic fixtures, including 24-trial browser
review, legacy inline results, draft preservation, late responses and desktop
and phone layouts. Sector attribution and comparison with the eligible
universe remain outside this feature. This work establishes source behavior;
it does not qualify or deploy the installed runtime. Integration and
publication require separate authorization.
