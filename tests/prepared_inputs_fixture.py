"""Original-only private prepared inputs: a fictional raw cache, research and daily SQLite.

`PreparedInputs(configure=None)` writes a private fictional raw cache and runs
ordinary research and daily preparation on it. It then patches
`research.DATABASE`, `research.connect`, `daily.connect` and
`cache_access.workspace`. Ordinary owners, such as `Original` and
`facts.View`, then read only these files and take only the private
`WorkspaceAccess` in `owner`. Nothing is downloaded and no project data is read.

The default cache has one company, TEST, with sessions through 2015-10-20 (the
`test_research.PreparationTests` and `test_prepared_facts.ProjectionTests`
data). `configure(inputs)` runs before preparation. It may rewrite files under
`research.RAW` and enter patches into `inputs.context`. `history(companies,
first, last)` returns one such callable for a larger deterministic history.

Use the object as a context manager. `close()` undoes every patch and removes
the files. Attributes: `root` (private folder), `source` (research.sqlite),
`path` (daily.sqlite), `owner`, `context` (ExitStack) and `fixture` (the
ProjectionTests instance that owns the folder). `view()` borrows a `facts.View` of the daily
and research databases.
"""
from contextlib import ExitStack, closing, contextmanager
from datetime import date, timedelta
import json
from unittest.mock import patch

from backtest.engines.reference import legacy
from backtest.financial import rules
from backtest.inputs import daily, facts, financial_inputs, research
from backtest.runtime import cache_access
import test_prepared_facts


class PreparedInputs:
    def __init__(self, *, configure=None):
        self.context = ExitStack()
        self.fixture = test_prepared_facts.ProjectionTests('test_complete_chain_preserves_evidence_dates_and_latest_valuation')
        try:
            self.fixture.setUp()
            self.context.callback(self.fixture.doCleanups)
            self.source, self.path = self.fixture.source, self.fixture.path
            self.root = self.source.parent.parent
            research.signature.return_value['historical_through'] = '2015-10-20'
            if configure is not None:
                configure(self)
            self.fixture.prepare()
            self.owner = cache_access.WorkspaceAccess(self.root/'prepared-inputs.lock')
            ordinary_daily, ordinary_research = daily.connect, research.connect
            self.context.enter_context(patch.object(cache_access, 'workspace', self.owner))
            self.context.enter_context(patch.object(research, 'DATABASE', self.source))
            self.context.enter_context(patch.object(daily, 'connect',
                side_effect=lambda: ordinary_daily(self.path, self.source)))
            self.context.enter_context(patch.object(research, 'connect',
                side_effect=lambda path=self.source, **kw: ordinary_research(path, **kw)))
        except BaseException:
            self.close()
            raise

    @contextmanager
    def view(self):
        """Yield a borrowed view of the prepared daily and research databases; close them on exit."""
        with closing(daily.connect()) as db, closing(research.connect()) as source, \
                facts.View(db, source, lambda: None, lambda: None) as view:
            yield view

    def close(self):
        self.context.close()

    def __enter__(self):
        return self

    def __exit__(self, *unused):
        self.close()


def history(companies, first, last):
    """Return a `configure` callable with deterministic fictional assets.

    Symbols are Q0000, Q0001 and so on. Sessions are weekdays from 2 January
    of `first` through 20 October of `last`. FIRST_YEAR and LAST_YEAR follow.
    """
    def configure(inputs):
        raw = research.RAW
        start, through = date(first,1,2), date(last,10,20)
        sessions=[]; day=start
        while day<=through:
            if day.weekday()<5:sessions.append(day)
            day+=timedelta(days=1)
        through=sessions[-1]
        symbols=[f'Q{i:04d}' for i in range(companies)]
        (raw/'universe.json').write_text(json.dumps([dict(symbol=symbol,name='Fictional '+symbol,
            exchange='NYSE',sector='Technology' if i%2 else 'Energy',listed=True)
            for i,symbol in enumerate(symbols)]))
        earlier=[];day=date(first-2,1,1)
        while day<start:
            if day.weekday()<5:earlier.append(day)
            day+=timedelta(days=1)
        prices=sorted(set(sessions+earlier+[date(year,6,30) for year in range(first-5,last+1)]))
        # Each saved fiscal date is explicit. All returns and provider values
        # use these same dividend-adjusted prices; no external data is read.
        for path in (raw/'px').glob('*.json'):path.unlink()
        with (raw/'metrics.jsonl').open('w') as metrics:
            for i,symbol in enumerate(symbols):
                metrics.write(json.dumps(dict(symbol=symbol,rows=[dict(date=f'{year}-06-30',
                    marketCap=120e6+i*1e5,enterpriseValue=180e6+i*1e5,
                    evToEBITDA=5+i/10000,reportedCurrency='USD')
                    for year in range(first-5,last+1)]))+'\n')
                (raw/'px'/f'{symbol}.json').write_text(json.dumps(dict(div=[dict(date=str(day),
                    adjClose=20.+(day-date(first,1,1)).days*.0005+i*.0001)
                    for day in prices])))
                rows=[]
                for year in range(first-5,last+1):
                    revenue=100e6+(year-first)*1e6+(i%29)*1e5
                    operating=(-2e6 if i%17==0 else 20e6)+(year-first)*1e5+(i%13)*1e4
                    rows.append(dict(date=f'{year}-06-30',reportedCurrency='USD',
                        revenue=None if i%23==0 else revenue,operatingIncome=operating))
                financial_inputs.publish(raw,symbol,'income-statement',rows,{},raw/'coverage.json')
        (raw/'spy-div.json').write_text(json.dumps([dict(date=str(day),
            adjClose=100.+(day-start).days*.005) for day in sessions]))
        (raw/'treasury.json').write_text(json.dumps([dict(date=str(day),month3=2.,year10=3.) for day in sessions]))
        (research.RESULTS/'summary-exits.txt').write_text('Through '+str(through)+'\n')
        research.signature.return_value=dict(fixture='private-scalar-qualification',historical_through=str(through))
        # The research preparation fixture substitutes its canonical report
        # verifier. This history keeps that substitution explicit.
        research.verify_reference.side_effect=lambda db:research.prepared_baseline(db)
        for owner in (rules,legacy):
            inputs.context.enter_context(patch.object(owner,'FIRST_YEAR',first))
            inputs.context.enter_context(patch.object(owner,'LAST_YEAR',last))
    return configure
