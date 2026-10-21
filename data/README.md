# Prepared research database

`research.sqlite` is generated locally from the saved JSON cache. It is excluded from Git and can be rebuilt without an API key or downloads:

```bash
python3 scripts/research.py prepare
```

Preparation reads each cached company price history once, writes compact January snapshots, and verifies the original top-50 annual returns before atomically replacing the database. Running preparation again without input changes only checks file metadata and returns immediately.

The database contains company metadata, cleaned annual financial observations with availability dates, January holding periods, entry valuations/holding returns for both original-screen candidates and the wider set with cached prices, and separate latest-session valuations for cached currently-listed companies with an exact-date price. It does not duplicate daily histories: those stay in `raw/px/`. Changes to rebalance frequency require additional preparation.

The original-screen pool retains the original reported-value thresholds and 250-name pre-price buffer. The broader pool covers only companies with cached prices, not all names in the universe. Missing prices are not downloaded automatically. Run `python3 scripts/research.py status` to inspect annual coverage.

Queries use read-only connections and check core input files, calculation code, and the price-directory timestamp without scanning every price file. Preparation checks the full per-price-file size/timestamp manifest. After editing an existing price file, run preparation to incorporate and validate the change; queries are reads of the last prepared snapshot. The `.building` database is temporary; a failed preparation preserves the previous completed database. Fingerprints are local freshness checks, not cryptographic verification of downloaded data.

`latest_snapshots` stores prospective picks with no holding return. Latest-date metadata records the actual cached session and coverage. The canonical report's saved Through date constrains historical snapshots independently of newer latest-session prices. After extending price data, run preparation then rebuild the website; an open HTML file is a saved snapshot, not a live data feed.

Schema 4 stores `screening_metrics`: ready-to-rank multiple/yield pairs keyed
by mode, pool, year, symbol and catalog metric ID. Latest observations use year
0. Preparation computes all formulas, including screening-date EV divided by
three-year average EBITDA, and preserves the default metric's exact existing
values. Missing history omits a pair. Consumers join or export these values;
they never reconstruct formulas. Catalog and calculator code in
`scripts/metrics.py` participates in freshness checks.
