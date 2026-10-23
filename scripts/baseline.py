"""Verified January baselines, revision evidence and recoverable publication.

Both engines supply full-precision results using the contract in revalue.calculate.
This module owns report formatting and publication, never financial calculations.
Callers hold cache_access through recovery, calculation and final publication.
"""
from contextlib import closing
from datetime import date, datetime, timezone
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import re
import sqlite3
import time
import uuid

import cache_assets
import run

# Full-precision engines may differ only by floating-point roundoff. The much
# larger legacy text tolerance applies only to four-decimal archived reports.
REL_TOL=1e-12
ABS_TOL=1e-12
PRICE_FIELDS=('fiscal_price_date','valuation_date','fiscal_price','valuation_price','entry_price','exit_price')
HOLDING_FIELDS=('symbol','rank','fiscal','entry','exit',*PRICE_FIELDS,'market_cap','enterprise_value','ebitda','return_value','status')
YEAR_FIELDS=('year','entry','exit','spy_entry','spy_exit','spy_entry_price','spy_exit_price','spy','portfolio')


def cutoff(text):
    match=re.search(r'^Through (\d{4}-\d{2}-\d{2})\s*$',text,re.MULTILINE)
    if match is None: raise ValueError('Current reference report is missing its Through date.')
    return min(run.ASOF,date.fromisoformat(match[1]))


def _same(a,b):
    if type(a) in (int,float) and type(b) in (int,float):
        return math.isfinite(a) and math.isfinite(b) and math.isclose(a,b,rel_tol=REL_TOL,abs_tol=ABS_TOL)
    return a==b


def agree(prepared,independent):
    """Reject any difference in coverage, holdings, prices or annual results.

    Equal annual averages cannot conceal swapped or incorrectly priced holdings.
    Values in this comparison are unrounded; nonfinite numbers always fail.
    """
    if prepared['through']!=independent['through'] or [y['year'] for y in prepared['years']]!=list(range(run.FIRST_YEAR,run.LAST_YEAR+1)) or [y['year'] for y in prepared['years']]!=[y['year'] for y in independent['years']]:
        raise ValueError('Baseline engines disagree on historical coverage. Existing results were kept.')
    for a,b in zip(prepared['years'],independent['years']):
        context=str(a['year'])
        for key in YEAR_FIELDS:
            if not _same(a[key],b[key]): raise ValueError(f'Baseline engines disagree for {context}: {key}. Existing results were kept.')
        if len(a['holdings'])!=len(b['holdings']): raise ValueError(f'Baseline engines disagree for {context}: holding count. Existing results were kept.')
        for x,y in zip(a['holdings'],b['holdings']):
            for key in HOLDING_FIELDS:
                if not _same(x[key],y[key]): raise ValueError(f'Baseline engines disagree for {context}, {x["symbol"]}: {key}. Existing results were kept.')


def render(result):
    """Render the existing human-readable report from one verified baseline."""
    years=result['years']
    if not years: raise ValueError('The baseline has no historical years.')
    complete=[y for y in years if y['year']<run.LAST_YEAR]
    stopped=sum(h['status']=='Last available price' for y in years for h in y['holdings'])
    bankrupt=sum(h['status']=='Bankruptcy' for y in years for h in y['holdings'])
    lines=['Trading that stops before the January sale is kept.',
           'If the shares were acquired or redeemed, the exit is the last price.',
           'A bankruptcy would be entered as a total loss. This pass found no bankruptcy among the stops.' if not bankrupt else 'Identified bankruptcies are entered as total losses.',
           f'Stops kept at the last price: {stopped}',f'Bankruptcies at -100%: {bankrupt}','']
    for selected,label in [(complete,f'30-year window {years[0]["entry"]} to {complete[-1]["exit"]}' if complete else ''),(years,'Through '+years[-1]['exit'])]:
        if not selected:continue
        growth=run.wealth_path([y['portfolio'] for y in selected]);spy=run.wealth_path([y['spy'] for y in selected])
        start,end=date.fromisoformat(selected[0]['entry']),date.fromisoformat(selected[-1]['exit'])
        lines += [label,f'strategy growth of $1: {growth:.2f}',f'SPY growth of $1: {spy:.2f}',
                  f'strategy CAGR: {run.cagr(growth,start,end):.2%}',f'SPY CAGR: {run.cagr(spy,start,end):.2%}','']
    lines.append('year,portfolio,spy,names,stopped,bankrupt')
    for y in years:
        stocks=y['holdings']
        lines.append(f'{y["year"]},{y["portfolio"]:.4f},{y["spy"]:.4f},{len(stocks)},{sum(h["status"]=="Last available price" for h in stocks)},{sum(h["status"]=="Bankruptcy" for h in stocks)}')
    return '\n'.join(lines)+'\n'


def changes(previous,current):
    """Describe exact old/new observations; migration never invents old prices."""
    old={y['year']:y for y in (previous or {}).get('years',[])}
    result=[]
    for year in current['years']:
        before=old.get(year['year'])
        totals={key:dict(before=before.get(key) if before else None,after=year[key]) for key in YEAR_FIELDS
                if key!='year' and not _same(before.get(key) if before else None,year[key])}
        stocks={h['symbol']:h for h in (before or {}).get('holdings',[])}
        now={h['symbol']:h for h in year['holdings']}
        holdings=[]
        for symbol in sorted(stocks.keys()|now.keys()):
            a,b=stocks.get(symbol),now.get(symbol)
            fields={key:dict(before=a.get(key) if a else None,after=b.get(key) if b else None) for key in HOLDING_FIELDS if key!='symbol'
                    and not _same(a.get(key) if a else None,b.get(key) if b else None)}
            if a is None or b is None or fields:
                holdings.append(dict(symbol=symbol,change='added' if a is None else 'removed' if b is None else 'changed',fields=fields))
        if totals or holdings: result.append(dict(year=year['year'],totals=totals,holdings=holdings))
    for year in sorted(old.keys()-{y['year'] for y in current['years']}):
        result.append(dict(year=year,removed=True,previous=old[year]))
    return result


def _sha(path):
    digest=hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda:handle.read(1024*1024),b''):digest.update(block)
    return digest.hexdigest()


def _replace(source,destination):
    for attempt in range(len(cache_assets.PUBLISH_RETRY_DELAYS)+1):
        try: source.replace(destination);return
        except PermissionError as error:
            if getattr(error,'winerror',None) not in (5,32,33) or attempt==len(cache_assets.PUBLISH_RETRY_DELAYS):raise
            time.sleep(cache_assets.PUBLISH_RETRY_DELAYS[attempt])


class Baseline:
    """Own a report/database pair and its history at the established file paths.

    A durable journal marks an unfinished generation. Readers reject it;
    preparation finishes it idempotently before inspecting source freshness.
    Previous reports and priced snapshots remain in immutable history folders.
    """
    def __init__(self,results,database):
        self.results=Path(results);self.database=Path(database)
        self.report=self.results/'summary-exits.txt'
        self.history=self.results/'baseline-history'
        self.journal=self.database.with_name(self.database.name+'.publication.json')

    def through(self):return cutoff(self.report.read_text(encoding='utf-8'))

    def check_ready(self,db):
        if self.journal.exists():raise ValueError('Baseline publication is unfinished. Retry preparation to recover the verified result.')
        row=db.execute("SELECT value FROM metadata WHERE key='baseline_report_sha'").fetchone()
        if row and json.loads(row[0])!=_sha(self.report):raise ValueError('The reference report and prepared database differ. Retry preparation.')

    def previous(self):
        if not self.database.exists():return None
        with closing(sqlite3.connect(self.database)) as db:
            row=db.execute("SELECT value FROM metadata WHERE key='baseline_result'").fetchone()
            if row:return json.loads(row[0])
            # Legacy databases contain dates and returns, but no historical
            # prices. Never read today's raw file to guess yesterday's price.
            db.row_factory=sqlite3.Row
            import research
            groups=research.aggregate(research.screen(db))
            periods={p['year']:dict(p) for p in db.execute('SELECT * FROM periods')}
            return dict(through=str(self.through()),legacy_prices_unavailable=True,years=[dict(year=year,entry=periods[year]['entry'],exit=periods[year]['exit'],
                        spy=periods[year]['spy'],portfolio=group['portfolio'],holdings=[{key:h.get(key) for key in HOLDING_FIELDS} for h in group['holdings']])
                        for year,group in groups.items()])

    def recover(self):
        """Complete a hash-verified pending publication under cache ownership."""
        if not self.journal.exists():return
        journal=json.loads(self.journal.read_text(encoding='utf-8'))
        if not re.fullmatch(r'[0-9a-f]{32}',journal['generation']):raise ValueError('Invalid baseline publication generation.')
        folder=self.history/journal['generation']
        expected=[('report.pending','report'),('research.pending','database')]
        if [(a['source'],a['target']) for a in journal['artifacts']]!=expected:
            raise ValueError('Invalid baseline publication journal. Saved results were kept.')
        artifacts=[(folder/a['source'],getattr(self,a['target']),a['sha256']) for a in journal['artifacts']]
        # Locators are filenames and logical targets. Resolve them against this
        # owner's current paths, including after a move or an OS change.
        for source,target,digest in artifacts:
            if source.resolve().parent!=folder.resolve():
                raise ValueError('Invalid baseline publication source. Saved results were kept.')
            path=source if source.exists() else target
            if not path.exists() or _sha(path)!=digest:
                raise ValueError('Baseline recovery files do not match their receipts. Saved results were kept.')
        names=('previous-report.txt','previous-snapshot.json','snapshot.json','audit.json','report.txt')
        if [r['file'] for r in journal['evidence']]!=list(names):
            raise ValueError('Invalid baseline recovery evidence.')
        for receipt in journal['evidence']:
            path=folder/receipt['file']
            if path.resolve().parent!=folder.resolve() or not path.is_file() or _sha(path)!=receipt['sha256']:
                raise ValueError('Baseline recovery evidence does not match its receipts. Saved results were kept.')
        try:
            for source,target,digest in artifacts:
                if source.exists():_replace(source,target)
        except OSError as error:
            raise ValueError('Baseline publication was interrupted. Retry preparation to recover the verified result.') from error
        for source,target,digest in artifacts:
            if _sha(target)!=digest:raise ValueError('Baseline publication verification failed. Retry preparation.')
        self.journal.unlink()

    def publish(self,candidate,result):
        """Publish only an already agreed result and a closed candidate database.

        Preserve the prior report verbatim before creating the journal. Failure
        before that journal leaves the canonical pair intact. Later failure is
        recoverable from the staged artifacts and their exact content hashes.
        """
        old_bytes=self.report.read_bytes();previous=self.previous()
        delta=changes(previous,result)
        generation=uuid.uuid4().hex
        folder=self.history/generation;folder.mkdir(parents=True)
        cache_assets.publish_bytes(folder/'previous-report.txt',old_bytes)
        cache_assets.write_json(folder/'previous-snapshot.json',previous)
        cache_assets.write_json(folder/'snapshot.json',result)
        new_text=render(result)
        report_bytes=old_bytes if new_text==old_bytes.decode('utf-8').replace('\r\n','\n') else new_text.encode('utf-8')
        changed=bool(delta) or report_bytes!=old_bytes
        prior_revision=None
        if self.database.exists():
            with closing(sqlite3.connect(self.database)) as db:
                row=db.execute("SELECT value FROM metadata WHERE key='baseline_revision'").fetchone()
                if row:prior_revision=json.loads(row[0])
                if prior_revision:prior_revision['audit']=prior_revision['audit'].replace('\\','/')
        audit=dict(generation=generation,checked_at=datetime.now(timezone.utc).isoformat(),through=result['through'],
                   bootstrap=previous is None or previous.get('legacy_prices_unavailable',False),years=delta)
        revision=dict(generation=generation,through=result['through'],changed_years=[y['year'] for y in delta],
                      audit=(folder/'audit.json').relative_to(self.results).as_posix(),bootstrap=audit['bootstrap']) if changed else prior_revision
        cache_assets.write_json(folder/'audit.json',audit)
        # Keep an immutable report copy in history; publication consumes a copy.
        cache_assets.publish_bytes(folder/'report.txt',report_bytes)
        cache_assets.publish_bytes(folder/'report.pending',report_bytes)
        with closing(sqlite3.connect(candidate)) as db, db:
            for key,value in dict(baseline_result=result,baseline_revision=revision,baseline_report_sha=hashlib.sha256(report_bytes).hexdigest()).items():
                db.execute('INSERT OR REPLACE INTO metadata VALUES(?,?)',(key,json.dumps(value,allow_nan=False)))
        staged=folder/'research.pending'
        _replace(Path(candidate),staged)
        artifacts=[dict(source=name,target=target,sha256=_sha(folder/name))
                   for name,target in [('report.pending','report'),('research.pending','database')]]
        evidence=[dict(file=name,sha256=_sha(folder/name)) for name in ('previous-report.txt','previous-snapshot.json','snapshot.json','audit.json','report.txt')]
        cache_assets.write_json(self.journal,dict(generation=generation,artifacts=artifacts,evidence=evidence))
        self.recover()
        if not changed:
            # A latest-only rebuild must not create a historical revision.
            for p in folder.iterdir():p.unlink()
            folder.rmdir()
        return revision

    def audit(self,db):
        row=db.execute("SELECT value FROM metadata WHERE key='baseline_revision'").fetchone()
        revision=json.loads(row[0]) if row else None
        if not revision:return None
        revision['audit']=revision['audit'].replace('\\','/')
        path=self.results/revision['audit']
        return dict(summary=revision,details=json.loads(path.read_text(encoding='utf-8')))
