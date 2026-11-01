"""Typed compiled candidate materialization and mechanical complete-book encoding.

One row corresponds to one planned input row. Validity column zero is acceptance;
other columns describe emitted ranking pairs and requested finite thresholds.
The encoder interprets representation only. Financial decisions belong to the
source-derived compiled program. Inputs and output buffers remain caller-owned.
"""
from backtest.runtime import backtest_control
from dataclasses import dataclass
from datetime import date
import hashlib
import json

import numpy as np
from backtest.runtime import backtest_control as backtest_control

VERSION = 1
SNAPSHOT = ('cap', 'ev', 'ebitda', 'yield_value', 'multiple', 'excess_yield', 'return_value')
PAIRS = ('multiple', 'yield_value', 'metric3_multiple', 'metric3_yield')


def layout(policy):
    return dict(version=VERSION, identity='int64 row index', dates='int32 fiscal/buy/sell/status',
        values=list(SNAPSHOT+PAIRS)+['filter_'+field for field in policy.filter_order],
        validity=['accepted','current_pair','three_year_pair',*policy.filter_order],
        value_dtype='float64', validity_dtype='uint8', ordering='original candidate rows')


def signature(policy):
    return hashlib.sha256(json.dumps(layout(policy),sort_keys=True,separators=(',',':')).encode()).hexdigest()


def array(value, dtype, shape, name, *, writable=False):
    if (not isinstance(value,np.ndarray) or value.dtype != np.dtype(dtype) or not value.dtype.isnative
            or value.shape != tuple(shape) or not value.flags.c_contiguous or not value.flags.aligned
            or writable and not value.flags.writeable):
        raise ValueError('Invalid native '+name+' buffer.')
    return value


def disjoint(inputs, outputs):
    """Reject any writable alias before native slices are constructed."""
    for index, output in enumerate(outputs):
        for other in (*inputs,*outputs[:index]):
            if np.shares_memory(output,other): raise ValueError('Native writable buffers overlap.')


def metadata(inputs, books, rows):
    result=np.empty((len(rows),6),dtype=np.int32)
    for row,(book,_,report) in enumerate(rows):
        entry,exit_day,pool=books[book]
        result[row]=(inputs.report_fiscal[report],entry.toordinal(),exit_day.toordinal(),
                     entry.year,exit_day.year,int(pool=='legacy'))
    return result


@dataclass
class CandidateBatch:
    identities: object
    dates: object
    values: object
    validity: object
    count: int

    @classmethod
    def empty(cls, rows, policy):
        return cls(np.empty(rows,dtype=np.int64),np.zeros((rows,4),dtype=np.int32),
            np.full((rows,11+len(policy.filter_order)),np.nan,dtype=np.float64),
            np.zeros((rows,3+len(policy.filter_order)),dtype=np.uint8),0)

    def validate(self, rows, policy):
        array(self.identities,np.int64,(rows,),'candidate identities')
        array(self.dates,np.int32,(rows,4),'candidate dates')
        array(self.values,np.float64,(rows,11+len(policy.filter_order)),'candidate values')
        array(self.validity,np.uint8,(rows,3+len(policy.filter_order)),'candidate validity')
        if (type(self.count) is not int or self.count != int(np.count_nonzero(self.validity[:,0]))
                or np.any(self.validity>1) or not np.array_equal(self.identities,np.arange(rows,dtype=np.int64))):
            raise ValueError('Invalid compiled candidate count, validity or row order.')
        accepted=self.validity[:,0]!=0
        if np.any(self.validity[~accepted]):raise ValueError('Rejected candidates emit values.')
        dates=self.dates[accepted]
        if (np.any(dates[:,:3]<1) or np.any(dates[:,:3]>date.max.toordinal())
                or np.any(dates[:,3]<1) or np.any(dates[:,3]>len(policy.decisions.statuses))):
            raise ValueError('Invalid compiled candidate date or status.')
        # Validate the representation promised by the producer; do not decide
        # whether a missing value should instead have been emitted.
        for column in range(len(policy.filter_order)):
            valid=self.validity[:,3+column]!=0
            if np.any(~np.isfinite(self.values[valid,11+column])):
                raise ValueError('Compiled threshold validity disagrees with its value.')
        return accepted


def encode(batch, inputs, policy, rows, ranks, results):
    """Map already decided typed output to the unchanged book tuple contract."""
    accepted=batch.validate(len(rows),policy)
    for index in np.flatnonzero(accepted):
        if index % 128 == 0:backtest_control.checkpoint()
        book,symbol_id,_=rows[int(batch.identities[index])]
        symbol=inputs.symbols[symbol_id]
        fiscal,buy,sell,status=batch.dates[index]
        values=batch.values[index]
        dates=[str(date.fromordinal(int(day))) for day in (fiscal,buy,sell)]
        results[book]['snapshots'].append((symbol,int(ranks[book,symbol_id]) or None,*dates,
            *(float(value) for value in values[:7]),policy.decisions.statuses[int(status)-1]))
        for valid,metric,first in ((1,'ev_ebitda',7),(2,'ev_ebitda_3y',9)):
            if batch.validity[index,valid]:
                results[book]['metrics'].append((symbol,metric,float(values[first]),float(values[first+1])))
        for column,field in enumerate(policy.filter_order):
            if batch.validity[index,3+column]:
                results[book]['filters'].append((symbol,field,float(values[11+column])))
    return accepted
