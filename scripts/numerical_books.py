"""Complete eligible candidate books over explicitly borrowed immutable inputs.

The prepared database remains caller-owned. Executors borrow immutable inputs;
they never download, publish trials or interpret independently written financial
formulas. Numeric arithmetic is extracted from the current source functions.
The original snapshot function supplies temporal, missing-price and exit guards.
"""
from array import array
from bisect import bisect_left, bisect_right
from calendar import monthrange
from datetime import date
import hashlib
import json
import math
from pathlib import Path
import time

import numpy as np
import backtest_control

from numerical_policy import PolicyProgram, FINANCIAL_FIELDS, require_supported
from numerical_generation import TEMPORAL_VERSION
LOOKUP_FIELDS = ('fiscal_raw', 'raw_entry', 'adjusted_entry', 'adjusted_exit',
                 'screen_adjusted', 'trailing_1y', 'trailing_3y')


class RequestPlan:
    """Request work requirements, without retained factors or selected results.

    Preserve every dated-book occurrence and its order. Resolve calendar targets
    and requested lookup dependencies once. Mandatory snapshot and exit inputs
    remain present even when no threshold consumes the trailing-price inputs.
    """
    def __init__(self, request, inputs):
        self.options = dict(request.get('options', request))
        require_supported(self.options)
        self.needed = frozenset(condition['field'] for condition in
                                self.options.get('filters', []) or [])
        # Both ranking pairs remain exposed to the unchanged SQL selector. The
        # mandatory slots also support source guards before numeric use.
        outputs = ('cap', 'ev', 'ebitda', 'return_value', 'multiple', 'yield_value',
                   'metric3_multiple', 'metric3_yield')
        outputs += tuple('filter_' + field for field in self.needed)
        dependencies = inputs.policy.dependencies(outputs)
        self.slots = tuple(sorted({0, 1, 3} | {slot for slot, field in enumerate(LOOKUP_FIELDS)
                                                   if field in dependencies and slot != 2}))
        self.books = ()
        if 'samples' in request:
            sessions = [date.fromisoformat(day) for day in sorted(inputs.sessions)]
            books = []
            for dates in request['samples']:
                _, _, periods = inputs.s.dated_periods(dates, request['start'],
                    request['end'], request['months'], sessions)
                books.extend((str(a), str(b), self.options['pool']) for a, b in periods)
            self.books = tuple(books)
        self.targets = {}
        for entry, _, _ in self.books:
            self.calendar(date.fromisoformat(entry))

    def calendar(self, entry):
        if entry not in self.targets:
            self.targets[entry] = (entry, *(entry.replace(year=entry.year-years,
                day=min(entry.day, monthrange(entry.year-years, entry.month)[1]))
                for years in (1, 3)))
        return self.targets[entry]


class PythonExecutor:
    """Batch report, price and policy execution with shared source guard logic.

    Override select_reports, resolve and calculate to test a different execution
    backend. Each evaluate result is an ordinary compute_period-shaped book.
    Inputs remain borrowed and immutable. Trace capture is an untimed proof aid.
    """
    def __init__(self,inputs,policy=None,limits=None):
        self.inputs = inputs
        self.policy = policy or inputs.policy
        self.limits = dict(limits or {})
        self.options = {}
        self.request_plan = None
        self.trace = {}
        assembly = self.limits.get('candidate_assembly', 'source')
        if assembly not in ('source', 'compiled'):
            raise ValueError('Unknown candidate assembly variant.')
        if assembly == 'compiled' and type(self).__name__ != 'NumbaExecutor':
            raise ValueError('Compiled candidate assembly requires Numba.')
        self.candidate_assembly = assembly
        self.stats = dict(backend='python',candidate_assembly=assembly,batches=0,books=0,candidate_rows=0)

    def begin(self,request):
        self.options = dict(request.get('options',request))
        require_supported(self.options)
        self.request_plan = RequestPlan(request, self.inputs) if self.limits.get('request_plan') else None
        self.trace = {}
        for key in ('report_seconds','lookup_seconds','planning_seconds',
                    'numeric_seconds','source_guard_seconds','decision_seconds','assembly_seconds','encoding_seconds'):
            self.stats.pop(key,None)
        self.stats.update(batches=0,books=0,candidate_rows=0)
        if self.request_plan is not None:
            self.stats.update(planned_lookup_slots=list(self.request_plan.slots), price_queries=0)

    def select_reports(self,entries):
        inputs = self.inputs
        results = []
        for pool in ('cached','legacy'):
            selected = np.full((len(entries),len(inputs.symbols)),-1,dtype=np.int32)
            offsets,ids = inputs.pool_offsets[pool],inputs.pool_report_ids[pool]
            known,fiscal = inputs.pool_known[pool],inputs.pool_fiscal[pool]
            for book,entry in enumerate(entries):
                for symbol in range(len(inputs.symbols)):
                    begin,end = int(offsets[symbol]),int(offsets[symbol+1])
                    position = bisect_left(known,int(entry),begin,end)-1
                    if position>=begin and int(entry)-int(fiscal[position])<=inputs.s.financial_books.run.MAX_AGE.days:
                        selected[book,symbol] = ids[position]
            results.append(selected)
        return tuple(results)

    def resolve(self,symbols,days,columns,forwards):
        actual = np.zeros(len(days),dtype=np.int32)
        values = np.full(len(days),np.nan,dtype=np.float64)
        inputs = self.inputs
        for index,(symbol,target,column,forward) in enumerate(zip(symbols,days,columns,forwards,strict=True)):
            if symbol<0:continue
            offsets,history,prices = ((inputs.raw_offsets,inputs.raw_days,inputs.raw_values)
                if column==0 else (inputs.adjusted_offsets,inputs.adjusted_days,inputs.adjusted_values))
            begin,end = int(offsets[symbol]),int(offsets[symbol+1])
            position = (bisect_left(history,int(target),begin,end) if forward
                        else bisect_right(history,int(target),begin,end)-1)
            if begin<=position<end:actual[index],values[index] = history[position],prices[position]
        return actual,values

    def calculate(self,matrix):
        return self.policy.evaluate(matrix)

    def _time(self,key,started):
        self.stats[key] = self.stats.get(key,0.)+time.perf_counter()-started

    def evaluate(self,book_batch,options=None):
        options = self.options if options is None else options
        require_supported(options)
        books = [(date.fromisoformat(str(a)),date.fromisoformat(str(b)),pool) for a,b,pool in book_batch]
        if any(pool not in ('cached','legacy') for a,b,pool in books):raise ValueError('Unknown candidate pool.')
        entries = np.asarray([a.toordinal() for a,b,pool in books],dtype=np.int32)
        exits = np.asarray([b.toordinal() for a,b,pool in books],dtype=np.int32)
        inputs,policy = self.inputs,self.policy
        backtest_control.checkpoint()
        workspace_limit = self.limits.get('workspace_bytes',64*1024**2)
        if 4096 + len(books)*len(inputs.symbols)*64 > workspace_limit:
            raise ValueError('Complete-book report workspace exceeds its bound.')
        started = time.perf_counter()
        broad,legacy = self.select_reports(entries)
        self._time('report_seconds',started)
        shape = (len(books),len(inputs.symbols))
        if broad.shape!=shape or legacy.shape!=shape:raise ValueError('Backend report shape differs.')
        ranks = np.zeros(shape,dtype=np.int32)
        for book in range(len(books)):
            available = np.flatnonzero(legacy[book]>=0)
            ordered = sorted(available,key=lambda symbol:inputs.report_yield[legacy[book,symbol]],reverse=True)
            for rank,symbol in enumerate(ordered[:inputs.s.financial_books.run.BUFFER],1):ranks[book,symbol]=rank
        plan = self.request_plan
        if plan is not None and plan.options != options:
            raise ValueError('Request plan differs from candidate options.')
        if plan is not None:
            selected = np.where(np.asarray([pool == 'legacy' for _, _, pool in books])[:, None], legacy, broad)
            allowed = (selected >= 0) & inputs.cached_mask[None, :]
            for book, (_, _, pool) in enumerate(books):
                if pool == 'legacy':
                    allowed[book] &= ranks[book] > 0
            row_books, row_symbols = np.nonzero(allowed)
            row_books = row_books.astype(np.int32)
            row_symbols = row_symbols.astype(np.int32)
            row_reports = selected[row_books, row_symbols].astype(np.int32)
            rows = list(zip(row_books.tolist(), row_symbols.tolist(), row_reports.tolist(), strict=True))
        else:
            rows = [(book,symbol,int(report)) for book,unused in enumerate(books)
                    for symbol,report in enumerate((legacy if books[book][2]=='legacy' else broad)[book])
                    if report>=0 and inputs.cached_mask[symbol] and (books[book][2]!='legacy' or ranks[book,symbol]>0)]
        row_books = np.asarray([row[0] for row in rows],dtype=np.int32)
        row_symbols = np.asarray([row[1] for row in rows],dtype=np.int32)
        row_reports = np.asarray([row[2] for row in rows],dtype=np.int32)
        row_limit = int(self.limits.get('max_candidate_rows',250000))
        if len(rows)>row_limit:raise ValueError('Candidate batch exceeds its declared row bound.')
        workspace = 4096 + len(books)*len(inputs.symbols)*64 + len(rows)*(8192+32*(len(policy.input_names)+len(policy.output_names)))
        if workspace > workspace_limit: raise ValueError('Complete-book workspace exceeds its bound.')
        self.stats['peak_workspace_bound'] = max(self.stats.get('peak_workspace_bound',0),workspace)
        backtest_control.checkpoint()
        lookup_days = np.zeros((len(rows),7),dtype=np.int32)
        lookup_values = np.full((len(rows),7),np.nan,dtype=np.float64)
        needed = plan.needed if plan is not None else {condition['field'] for condition in options.get('filters',[]) or []}
        # All temporal endpoints are planned together. Filter arithmetic remains
        # available for proof; unused threshold rows are not exposed to SQL.
        queries,locations = [],[]
        targets = []
        for book,(entry,exit_day,pool) in enumerate(books):
            targets.append(plan.calendar(entry) if plan is not None else (entry,*(entry.replace(year=entry.year-years,
                day=min(entry.day,monthrange(entry.year-years,entry.month)[1])) for years in (1,3))))
        for row,(book,symbol,report) in enumerate(rows):
            if row % 128 == 0: backtest_control.checkpoint()
            entry,exit_day,pool = books[book]
            desired = ((0,int(inputs.report_fiscal[report]),0,False),
                       (1,entry.toordinal(),0,True),(3,exit_day.toordinal(),1,False),
                       (4,entry.toordinal(),1,False),(5,targets[book][1].toordinal(),1,False),
                       (6,targets[book][2].toordinal(),1,False))
            for slot,target,column,forward in desired:
                if plan is not None and slot not in plan.slots:
                    continue
                queries.append((symbol,target,column,forward));locations.append((row,slot))
        started = time.perf_counter()
        def execute(planned,where):
            if not planned:return
            if plan is not None:
                self.stats['price_queries'] += len(planned)
            symbol,day,column,forward = zip(*planned,strict=True)
            actual,values = self.resolve(np.asarray(symbol,dtype=np.int32),np.asarray(day,dtype=np.int32),
                              np.asarray(column,dtype=np.int8),np.asarray(forward,dtype=np.bool_))
            if len(actual)!=len(planned) or len(values)!=len(planned):raise ValueError('Backend lookup length differs.')
            for (row,slot),resolved,value in zip(where,actual,values,strict=True):
                lookup_days[row,slot],lookup_values[row,slot] = resolved,value
        execute(queries,locations)
        second,locations = [],[]
        for row,(book,symbol,report) in enumerate(rows):
            if row % 128 == 0: backtest_control.checkpoint()
            if lookup_days[row,1]:
                second.append((symbol,int(lookup_days[row,1]),1,True));locations.append((row,2))
        execute(second,locations)
        self._time('lookup_seconds',started)
        started = time.perf_counter()
        matrix = np.full((len(rows),len(policy.input_names)),np.nan,dtype=np.float64)
        ii = policy.input_index
        treasuries, treasury10 = [], []
        for entry,exit_day,pool in books:
            index = bisect_right(inputs.treasury_days,str(entry))-1
            treasuries.append(float(inputs.treasury_values[index]) if index>=0 else 0.)
            value = inputs.ten_year_yield(entry)
            treasury10.append(np.nan if value is None else value)
        if plan is not None:
            for key, values in (('report_cap', inputs.report_cap),
                    ('report_enterprise', inputs.report_enterprise),
                    ('report_yield', inputs.report_yield), ('average_3y', inputs.average_3y)):
                matrix[:, ii[key]] = values[row_reports]
            matrix[:, ii['treasury']] = np.asarray(treasuries)[row_books]
            matrix[:, ii['treasury10']] = np.asarray(treasury10)[row_books]
            matrix[:, ii['bankruptcy']] = [float((books[book][0].year, inputs.symbols[symbol])
                                                   in inputs.bankrupt) for book, symbol, _ in rows]
            for slot, key in enumerate(LOOKUP_FIELDS):
                matrix[:, ii[key]] = lookup_values[:, slot]
            for slot, years in ((4, 0), (5, 1), (6, 2)):
                target_days = np.asarray([target[years].toordinal() for target in targets])[row_books]
                invalid = (lookup_days[:, slot] == 0) | (np.abs(lookup_days[:, slot] - target_days) > 7)
                matrix[invalid, ii[LOOKUP_FIELDS[slot]]] = np.nan
            matrix[:, len(policy.input_names)-len(policy.parameter_names):] = inputs.financial_parameters[row_reports]
        else:
            for row,(book,symbol,report) in enumerate(rows):
                if row % 128 == 0: backtest_control.checkpoint()
                entry,exit_day,pool = books[book]
                for key,value in (('report_cap',inputs.report_cap[report]),
                        ('report_enterprise',inputs.report_enterprise[report]),('report_yield',inputs.report_yield[report]),
                        ('bankruptcy',float((entry.year,inputs.symbols[symbol]) in inputs.bankrupt)),
                        ('average_3y',inputs.average_3y[report]),('treasury',treasuries[book]),
                        ('treasury10',treasury10[book])):
                    matrix[row,ii[key]] = value
                for slot,key in enumerate(LOOKUP_FIELDS):matrix[row,ii[key]]=lookup_values[row,slot]
                for slot,target in ((4,entry.toordinal()),(5,targets[book][1].toordinal()),(6,targets[book][2].toordinal())):
                    if not lookup_days[row,slot] or abs(int(lookup_days[row,slot])-target)>7:
                        matrix[row,ii[LOOKUP_FIELDS[slot]]] = np.nan
                matrix[row,len(policy.input_names)-len(policy.parameter_names):] = inputs.financial_parameters[report]
        self._time('planning_seconds',started)
        started = time.perf_counter()
        numeric = self.calculate(matrix)
        if numeric.shape!=(len(rows),len(policy.output_names)):raise ValueError('Backend numeric shape differs.')
        self._time('numeric_seconds',started)
        started = time.perf_counter()
        results = []
        for book,(entry,exit_day,pool) in enumerate(books):
            spy = policy.spy_return(inputs.sessions[str(entry)],inputs.sessions[str(exit_day)])
            results.append(dict(entry=str(entry),exit=str(exit_day),pool=pool,
                period=(str(entry),str(exit_day),spy,treasuries[book],int(np.count_nonzero(ranks[book])),
                        int(np.count_nonzero(broad[book]>=0))),snapshots=[],metrics=[],filters=[]))
        backtest_control.checkpoint()
        accepted = self.assemble_candidates(books, rows, targets, lookup_days,
            lookup_values, matrix, numeric, ranks, needed, results)
        self._time('source_guard_seconds' if self.candidate_assembly == 'source'
                   else 'assembly_seconds',started)
        self.stats['batches'] += 1;self.stats['books'] += len(books);self.stats['candidate_rows'] += len(rows)
        self.trace = dict(entries=entries,exits=exits,broad_reports=broad,legacy_reports=legacy,
            ranks=ranks,row_books=row_books,row_symbols=row_symbols,row_reports=row_reports,
            lookup_days=lookup_days,lookup_values=lookup_values,numeric_inputs=matrix,
            numeric_outputs=numeric,accepted=accepted) if self.limits.get('capture') else {}
        return results

    def assemble_candidates(self, books, rows, targets, lookup_days, lookup_values,
                            matrix, numeric, ranks, needed, results):
        return self._source_candidates(books, rows, targets, lookup_days, lookup_values,
                                       numeric, ranks, needed, results)

    def _encode_candidate(self, output, symbol, rank, observation, current_pair,
                          three_pair, values, needed):
        """Encode accepted candidate decisions into the existing complete book
        format, preserving row order, ranking-pair missingness and requested
        threshold values.
        """
        fiscal,buy,sell,cap,ev,ebitda,yield_value,multiple,ret,status = observation
        oi = self.policy.output_index
        output['snapshots'].append((symbol,rank,fiscal,buy,sell,cap,ev,ebitda,
            yield_value,multiple,values[oi['excess_yield']],ret,status))
        if current_pair is not None:output['metrics'].append((symbol,'ev_ebitda',*current_pair))
        if three_pair is not None:output['metrics'].append((symbol,'ev_ebitda_3y',*three_pair))
        for field in self.policy.filter_order:
            value = values[oi['filter_'+field]]
            if field in needed and math.isfinite(value):output['filters'].append((symbol,field,value))

    def _source_candidates(self, books, rows, targets, lookup_days, lookup_values,
                           numeric, ranks, needed, results):
        inputs,policy = self.inputs,self.policy
        plan = self.request_plan
        accepted = np.zeros(len(rows),dtype=np.bool_)
        for row,(book,symbol_id,report) in enumerate(rows):
            if row % 128 == 0: backtest_control.checkpoint()
            entry,exit_day,pool = books[book]
            symbol = inputs.symbols[symbol_id]
            statement = inputs.report_rows[report]
            values = numeric[row].tolist() if plan is not None else [float(value) for value in numeric[row]]
            def lookup(day,column,forward=False,slack=None):
                if column=='price':slot=1 if forward else 0
                elif forward:slot=2
                elif day==exit_day:slot=3
                elif day==entry:slot=4
                elif day==targets[book][1]:slot=5
                elif day==targets[book][2]:slot=6
                else:raise ValueError('Source guard requested an unplanned lookup.')
                resolved = int(lookup_days[row,slot])
                if not resolved or (slack is not None and abs(resolved-day.toordinal())>slack):return None
                return date.fromordinal(resolved),float(lookup_values[row,slot])
            observation = policy._snapshot(statement,entry,exit_day,lookup,
                (entry.year,symbol) in inputs.bankrupt,values)
            if observation is None:continue
            fiscal,buy,sell,cap,ev,ebitda,yield_value,multiple,ret,status = observation
            if not inputs.s.financial_books.eligible(pool,cap,ev):continue
            accepted[row] = True
            metric_observation = dict(symbol=symbol,fiscal=fiscal,market_cap=cap,
                enterprise_value=ev,ev_ebitda=multiple,ebitda_yield=yield_value)
            pair = policy._current(metric_observation)
            current_pair = pair
            average = inputs.average_3y[report]
            pair = policy._three(metric_observation,values,
                                  None if np.isnan(average) else float(average))
            self._encode_candidate(results[book], symbol, int(ranks[book,symbol_id]) or None,
                                   observation, current_pair, pair, values, needed)
        return accepted

    def close(self):
        self.trace = {}
        self.request_plan = None
        self.options = {}


def attach(inputs,policy=None,limits=None):
    return PythonExecutor(inputs,policy,limits)
