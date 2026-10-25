"""Source-bound candidate/factor batches for experimental backtest executors.

The prepared database remains caller-owned. Executors borrow immutable inputs;
they never download, publish trials or interpret independently written financial
formulas. Numeric arithmetic is extracted from the current source functions.
The original snapshot function supplies temporal, missing-price and exit guards.
"""
from array import array
import ast
from bisect import bisect_left, bisect_right
from calendar import monthrange
import copy
from datetime import date
import hashlib
import inspect
import json
import math
from pathlib import Path
import textwrap
import time
import types

import numpy as np

from bench_methods_arrays import ArrayPrices
from bench_candidates_policy import CandidateDecisionProgram


FINANCIAL_FIELDS = ('pe', 'pb', 'fcf', 'fcf_yield', 'price_fcf',
                    'profit_margin', 'roe', 'current_ratio', 'interest_coverage',
                    'debt_equity', 'peg')
LOOKUP_FIELDS = ('fiscal_raw', 'raw_entry', 'adjusted_entry', 'adjusted_exit',
                 'screen_adjusted', 'trailing_1y', 'trailing_3y')


def _tree(function):
    return ast.parse(textwrap.dedent(inspect.getsource(function))).body[0]


class _Symbol:
    """Trace market-cap arithmetic while source code chooses annual inputs."""
    def __init__(self, node):
        self.node = node

    def _binary(self, other, op, reverse=False):
        left = other.node if isinstance(other, _Symbol) else ('const', float(other))
        right = self.node
        return _Symbol((op, left, right) if reverse else (op, right, left))

    def __add__(self, other): return self._binary(other, 'add')
    def __radd__(self, other): return self._binary(other, 'add', True)
    def __sub__(self, other): return self._binary(other, 'sub')
    def __rsub__(self, other): return self._binary(other, 'sub', True)
    def __mul__(self, other): return self._binary(other, 'mul')
    def __rmul__(self, other): return self._binary(other, 'mul', True)
    def __truediv__(self, other): return self._binary(other, 'div')
    def __rtruediv__(self, other): return self._binary(other, 'div', True)
    def __neg__(self): return _Symbol(('neg', self.node))

    def __gt__(self, other):
        # financial_values uses positive market cap as a denominator. Snapshot
        # and source eligibility establish this assumption before row exposure.
        if self.node == ('input', 'cap') and other == 0:
            return True
        raise ValueError('Unsupported symbolic financial-policy comparison.')


class _Math:
    def __getattr__(self, name):
        return getattr(math, name)

    def isfinite(self, value):
        # Each symbolic ratio is checked for finiteness after batch execution.
        return True if isinstance(value, _Symbol) else math.isfinite(value)


def _template(value, field):
    """Replace annual literal leaves with stable per-field parameter slots."""
    parameters = []
    def walk(node):
        if node[0] == 'const':
            name = f'financial_{field}_{len(parameters)}'
            parameters.append(float(node[1]))
            return ('input', name)
        if node[0] == 'input':
            return ('var', 'cap') if node[1] == 'cap' else node
        return (node[0], *(walk(child) for child in node[1:]))
    node = value.node if isinstance(value, _Symbol) else ('const', float(value))
    return walk(node), parameters


class PolicyProgram:
    """One source-derived float64 expression program and source control adapter.

    Expressions use the small tuple IR documented by ``expanded``. Annual
    specialization executes the authoritative calculator; only market-cap
    dependent operations become traced expressions. Unsupported numeric syntax,
    catalog changes or a changed expression shape fail rather than fall back.
    """
    def __init__(self, schedules, *, bankrupt=None):
        self.s = schedules
        m = schedules.metrics
        if tuple(m.METRICS) != ('ev_ebitda', 'ev_ebitda_3y'):
            raise ValueError('Unsupported ranking catalog for candidate experiment.')
        if set(m.FILTERS) != set(FINANCIAL_FIELDS) | {
                'return_1y', 'return_3y', 'market_cap', 'enterprise_value',
                'ev_ebitda', 'ev_ebitda_3y', 'ebitda_yield'}:
            raise ValueError('Unsupported threshold catalog for candidate experiment.')
        self._financial = types.FunctionType(m.financial_values.__code__,
            dict(m.financial_values.__globals__, math=_Math()),
            m.financial_values.__name__, m.financial_values.__defaults__)
        annual = {f'{year}-06-30': dict(netIncome=120., totalStockholdersEquity=400.,
                  freeCashFlow=30., revenue=900., totalCurrentAssets=150.,
                  totalCurrentLiabilities=60., ebit=160., interestExpense=10.,
                  totalDebt=90., epsDiluted=float(2 ** (year-2011)))
                  for year in range(2011, 2015)}
        probe = self._financial(dict(fiscal='2014-06-30', market_cap=_Symbol(('input', 'cap'))), annual)
        if set(probe) != set(FINANCIAL_FIELDS):
            raise ValueError('Financial-policy specialization did not cover its catalog.')
        self.financial_templates = {}
        parameter_names = []
        for field in FINANCIAL_FIELDS:
            template, parameters = _template(probe[field], field)
            self.financial_templates[field] = template
            parameter_names.extend(f'financial_{field}_{i}' for i in range(len(parameters)))
        self.parameter_names = tuple(parameter_names)
        self.parameter_index = {name:i for i,name in enumerate(self.parameter_names)}
        self.input_names = ('report_cap', 'report_enterprise', 'report_yield',
            'fiscal_raw', 'raw_entry', 'adjusted_entry', 'adjusted_exit',
            'bankruptcy', 'average_3y', 'screen_adjusted', 'trailing_1y',
            'trailing_3y', 'treasury') + self.parameter_names
        self.input_index = {name:i for i,name in enumerate(self.input_names)}
        snapshot = _tree(schedules.financial_books.snapshot)
        assignments = {node.targets[0].id:node.value for node in snapshot.body
                       if isinstance(node,ast.Assign) and len(node.targets)==1
                       and isinstance(node.targets[0],ast.Name)}
        if not {'cap','ev','ebitda','ret'} <= assignments.keys():
            raise ValueError('Unsupported source snapshot structure.')
        returns = [node for node in snapshot.body if isinstance(node,ast.Return)]
        if len(returns)!=1 or not isinstance(returns[0].value,ast.List) or len(returns[0].value.elts)!=10:
            raise ValueError('Unsupported source snapshot result structure.')
        result = returns[0].value.elts
        expressions = [(name,self._lower(assignments[source])) for name,source in
                       (('cap','cap'),('ev','ev'),('ebitda','ebitda'),('return_value','ret'))]
        expressions += [('yield_value',self._lower(result[6])),('multiple',self._lower(result[7]))]
        three = _tree(m.three_year_multiple)
        three_assignment = next(node for node in three.body if isinstance(node,ast.Assign)
                                and isinstance(node.targets[0],ast.Name) and node.targets[0].id=='multiple')
        expressions.append(('metric3_multiple',self._lower(three_assignment.value,
                           names={'average':('input','average_3y')})))
        three_return = next(node for node in three.body if isinstance(node,ast.Return))
        expressions.append(('metric3_yield',self._lower(three_return.value.elts[1],
                           names={'multiple':('var','metric3_multiple')})))
        compute = _tree(schedules.compute_period)
        spy_assignment = next(node for node in ast.walk(compute) if isinstance(node,ast.Assign)
            and isinstance(node.targets[0],ast.Name) and node.targets[0].id=='spy_return')
        class BindSpy(ast.NodeTransformer):
            def visit_Subscript(self,node):
                if (isinstance(node.value,ast.Name) and node.value.id=='spy'
                        and isinstance(node.slice,ast.Call) and isinstance(node.slice.func,ast.Name)
                        and node.slice.func.id=='str' and len(node.slice.args)==1
                        and isinstance(node.slice.args[0],ast.Name)):
                    field = node.slice.args[0].id
                    if field in ('entry','exit_day'):
                        return ast.Name('entry_price' if field=='entry' else 'exit_price',ast.Load())
                raise ValueError('Unsupported source SPY-return expression.')
        spy_expression = BindSpy().visit(copy.deepcopy(spy_assignment.value))
        if any(isinstance(node,ast.Name) and node.id not in ('entry_price','exit_price')
               for node in ast.walk(spy_expression)):
            raise ValueError('Unsupported source SPY-return dependency.')
        self._spy_code = compile(ast.fix_missing_locations(ast.Expression(spy_expression)),
                                 '<source-derived SPY return>','eval')
        self.spy_expression = ast.dump(spy_expression,include_attributes=False)
        snapshot_append = next(node for node in ast.walk(compute) if isinstance(node,ast.Call)
            and isinstance(node.func,ast.Attribute) and isinstance(node.func.value,ast.Name)
            and node.func.value.id=='snapshots' and node.func.attr=='append')
        expressions.append(('excess_yield',self._lower(snapshot_append.args[0].elts[10],
                           names={'yield_value':('var','yield_value'),'treasury':('input','treasury')})))
        filters = _tree(m.filter_values)
        units = next(node.value.value for node in filters.body if isinstance(node,ast.Assign)
                     and isinstance(node.value,ast.DictComp))
        yield_assignment = next(node.value for node in filters.body if isinstance(node,ast.Assign)
            and isinstance(node.targets[0],ast.Subscript)
            and isinstance(node.targets[0].slice,ast.Constant)
            and node.targets[0].slice.value=='ebitda_yield')
        trailing = next(node.value for node in ast.walk(filters) if isinstance(node,ast.Assign)
            and isinstance(node.targets[0],ast.Subscript)
            and isinstance(node.targets[0].slice,ast.JoinedStr))
        field_expressions = dict(self.financial_templates)
        for field in ('market_cap','enterprise_value'):
            expression = copy.deepcopy(units)
            for node in ast.walk(expression):
                if isinstance(node,ast.Subscript) and isinstance(node.slice,ast.Name) and node.slice.id=='k':
                    node.slice=ast.Constant(field)
            field_expressions[field] = self._lower(expression)
        field_expressions['ebitda_yield'] = self._lower(yield_assignment)
        field_expressions['ev_ebitda'] = ('var','multiple')
        field_expressions['ev_ebitda_3y'] = ('var','metric3_multiple')
        for years in (1,3):
            field_expressions[f'return_{years}y'] = self._lower(trailing,
                lookups={'end':'screen_adjusted','start':f'trailing_{years}y'})
        expressions.extend(('filter_'+field,field_expressions[field]) for field in m.FILTERS)
        self.expressions = tuple(expressions)
        self.expression_map = dict(expressions)
        self.output_names = tuple(name for name,unused in expressions)
        self.output_index = {name:i for i,name in enumerate(self.output_names)}
        self.decisions = CandidateDecisionProgram(self, _tree)
        source_files = {Path(function.__code__.co_filename).resolve()
                        for function in (schedules.financial_books.snapshot,schedules.financial_books.eligible,
                                         m.current_multiple,m.financial_values,
                                         schedules.compute_period,m.three_year_multiple)}
        source_files.update(Path(module.__file__).resolve() for module in
            (schedules.financial_books.run,schedules.r,schedules.r.revalue))
        self.source_hashes = {path.name:hashlib.sha256(path.read_bytes()).hexdigest()
                              for path in sorted(source_files)}
        self.source_paths = tuple(sorted(source_files))
        identity = dict(sources=self.source_hashes, inputs=self.input_names,
                        max_age=schedules.financial_books.run.MAX_AGE.days,
                        buffer=schedules.financial_books.run.BUFFER,
                        minimum_cap=schedules.financial_books.run.MIN_MARKET_CAP,
                        minimum_ev=schedules.financial_books.run.MIN_EV,
                        bankruptcy=sorted(schedules.r.revalue.BANKRUPT if bankrupt is None else bankrupt),
                        candidate_decisions=self.decisions.source,
                        candidate_statuses=self.decisions.statuses,
                        spy_expression=self.spy_expression,
                        expressions=self.expressions)
        self.signature = hashlib.sha256(json.dumps(identity,sort_keys=True,
                            separators=(',',':'),allow_nan=False).encode()).hexdigest()
        self._row_namespace = {}
        exec(self.python_source('_policy_row'), self._row_namespace)
        self._row = self._row_namespace['_policy_row']
        self._snapshot = self._snapshot_adapter(snapshot,schedules.financial_books.snapshot)
        self._three = self._three_adapter(three,m.three_year_multiple)
        numeric_observation = dict(fiscal='2014-06-30',market_cap=150.,enterprise_value=200.,
                                   ev_ebitda=4.,ebitda_yield=.25)
        history = [dict(fiscal=f'{year}-06-30',ebitda=20.) for year in range(2011,2015)]
        evaluated = m.evaluate(numeric_observation,history)
        self.filter_order = tuple(m.filter_values(numeric_observation,evaluated,date(2015,1,2),
                                    lambda day,*args:(day,1.),annual))

    def _lower(self,node,*,names=None,lookups=None):
        names = names or {}
        lookups = lookups or {'fiscal_px':'fiscal_raw','entry_px':'raw_entry',
                              'start':'adjusted_entry','end':'adjusted_exit'}
        if isinstance(node,ast.Constant) and isinstance(node.value,(int,float)):
            return ('const',float(node.value))
        if isinstance(node,ast.Name):
            if node.id in names:return names[node.id]
            if node.id=='bankruptcy':return ('input','bankruptcy')
            if node.id in ('cap','ev','ebitda'):return ('var',node.id)
            if node.id=='ret':return ('var','return_value')
        if isinstance(node,ast.UnaryOp) and isinstance(node.op,ast.USub):
            return ('neg',self._lower(node.operand,names=names,lookups=lookups))
        if isinstance(node,ast.BinOp):
            operators = {ast.Add:'add',ast.Sub:'sub',ast.Mult:'mul',ast.Div:'div'}
            if type(node.op) in operators:
                return (operators[type(node.op)],self._lower(node.left,names=names,lookups=lookups),
                        self._lower(node.right,names=names,lookups=lookups))
        if isinstance(node,ast.IfExp):
            return ('if',self._lower(node.test,names=names,lookups=lookups),
                    self._lower(node.body,names=names,lookups=lookups),
                    self._lower(node.orelse,names=names,lookups=lookups))
        if isinstance(node,ast.Subscript) and isinstance(node.value,ast.Name) and isinstance(node.slice,ast.Constant):
            owner,key = node.value.id,node.slice.value
            if owner in lookups and key==1:return ('input',lookups[owner])
            fields = {'statement':{'market_cap':('input','report_cap'),
                        'enterprise':('input','report_enterprise'),'yield':('input','report_yield')},
                      'observation':{'market_cap':('var','cap'),'enterprise_value':('var','ev'),
                        'ebitda_yield':('var','yield_value'),'ev_ebitda':('var','multiple')}}
            if owner in fields and key in fields[owner]:return fields[owner][key]
        raise ValueError('Unsupported source numeric expression: '+ast.dump(node,include_attributes=False))

    def expanded(self,name):
        """Return IR with derived variables inlined, preserving every operation.

        Nodes are input/const leaves, add/sub/mul/div pairs, unary neg, and if
        (condition, true, false). The only condition is the bankruptcy input.
        """
        def walk(node):
            if node[0]=='var':return walk(self.expression_map[node[1]])
            if node[0] in ('input','const'):return node
            return (node[0],*(walk(child) for child in node[1:]))
        return walk(self.expression_map[name])

    def python_source(self,name='_policy_row'):
        def emit(node):
            op = node[0]
            if op=='input':return f'x[{self.input_index[node[1]]}]'
            if op=='const':return repr(node[1])
            if op=='var':return node[1]
            if op=='neg':return f'(-{emit(node[1])})'
            if op=='if':return f'({emit(node[2])} if {emit(node[1])} else {emit(node[3])})'
            operator = {'add':'+','sub':'-','mul':'*','div':'/'}[op]
            return f'({emit(node[1])} {operator} {emit(node[2])})'
        statements = [f'def {name}(x):']
        statements.extend(f'    {key} = {emit(value)}' for key,value in self.expressions)
        statements.append('    return ('+', '.join(self.output_names)+',)')
        return '\n'.join(statements)+'\n'

    def evaluate(self,matrix):
        matrix = np.asarray(matrix,dtype=np.float64)
        output = np.empty((len(matrix),len(self.output_names)),dtype=np.float64)
        with np.errstate(all='ignore'):
            for row,values in enumerate(matrix):output[row] = self._row(values)
        return output

    def spy_return(self,entry_price,exit_price):
        return eval(self._spy_code,{},dict(entry_price=entry_price,exit_price=exit_price))

    def specialize_financial(self,fiscal,reports):
        result = np.full(len(self.parameter_names),np.nan,dtype=np.float64)
        observation = dict(fiscal=fiscal,market_cap=_Symbol(('input','cap')))
        for field,value in self._financial(observation,reports).items():
            if field not in self.financial_templates:
                raise ValueError('Unsupported specialized financial field: '+field)
            template,parameters = _template(value,field)
            if template != self.financial_templates[field]:
                raise ValueError('Financial expression shape differs for '+field)
            for index,parameter in enumerate(parameters):
                result[self.parameter_index[f'financial_{field}_{index}']] = parameter
        return result

    def _snapshot_adapter(self,original_tree,function):
        tree = copy.deepcopy(original_tree)
        tree.name = '_source_snapshot'
        tree.args.args.append(ast.arg(arg='numeric_values'))
        replacements = dict(cap='cap',ev='ev',ebitda='ebitda',ret='return_value')
        for node in tree.body:
            if isinstance(node,ast.Assign) and isinstance(node.targets[0],ast.Name) and node.targets[0].id in replacements:
                key = replacements[node.targets[0].id]
                node.value = ast.Subscript(ast.Name('numeric_values',ast.Load()),
                                            ast.Constant(self.output_index[key]),ast.Load())
            if isinstance(node,ast.Return):
                for index,key in ((6,'yield_value'),(7,'multiple')):
                    node.value.elts[index] = ast.Subscript(ast.Name('numeric_values',ast.Load()),
                                              ast.Constant(self.output_index[key]),ast.Load())
        module = ast.fix_missing_locations(ast.Module(body=[tree],type_ignores=[]))
        namespace = dict(function.__globals__)
        exec(compile(module,'<source-derived snapshot>','exec'),namespace)
        return namespace[tree.name]

    def _three_adapter(self,original_tree,function):
        tree = copy.deepcopy(original_tree)
        tree.name = '_source_three_year'
        tree.args.args.extend([ast.arg(arg='numeric_values'),ast.arg(arg='supplied_average')])
        for node in tree.body:
            if isinstance(node,ast.Assign) and isinstance(node.targets[0],ast.Name):
                if node.targets[0].id=='average':node.value=ast.Name('supplied_average',ast.Load())
                if node.targets[0].id=='multiple':
                    node.value=ast.Subscript(ast.Name('numeric_values',ast.Load()),
                               ast.Constant(self.output_index['metric3_multiple']),ast.Load())
            if isinstance(node,ast.Return):
                node.value=ast.Tuple([ast.Subscript(ast.Name('numeric_values',ast.Load()),
                            ast.Constant(self.output_index[key]),ast.Load())
                            for key in ('metric3_multiple','metric3_yield')],ast.Load())
        module = ast.fix_missing_locations(ast.Module(body=[tree],type_ignores=[]))
        namespace = dict(function.__globals__)
        exec(compile(module,'<source-derived three-year metric>','exec'),namespace)
        return namespace[tree.name]


class NumericInputs:
    """Load immutable source rows and contiguous sparse numeric histories once."""
    def __init__(self,source,schedules):
        began = time.perf_counter()
        self.s = schedules
        self.books = schedules.histories(source)
        self.cached = schedules.cached_symbols(source)
        self.histories = {symbol:[dict(row,fiscal=str(row['fiscal']),known=str(row['known']))
                                 for row in rows] for symbol,rows in self.books[0].items()}
        self.financials = {}
        for symbol,fiscal,values in source.execute('SELECT symbol,fiscal,values_json FROM financial_inputs'):
            self.financials.setdefault(symbol,{})[fiscal] = json.loads(values)
        self.companies = tuple(tuple(row) for row in source.execute('SELECT * FROM companies'))
        self.sessions = dict(source.execute('SELECT day,price FROM sessions ORDER BY day'))
        treasuries = list(source.execute('SELECT day,yield_value FROM treasuries ORDER BY day'))
        self.treasury_days = [row[0] for row in treasuries]
        self.treasury_values = [row[1] for row in treasuries]
        self.bankrupt = frozenset(schedules.r.revalue.BANKRUPT)
        self.policy = PolicyProgram(schedules,bankrupt=self.bankrupt)
        prices = ArrayPrices(source)
        symbols = list(self.books[0])
        symbols.extend(symbol for symbol in prices._series if symbol not in self.books[0])
        self.symbols = tuple(symbols)
        self.symbol_ids = {symbol:i for i,symbol in enumerate(symbols)}
        self.cached_mask = np.array([symbol in self.cached for symbol in symbols],dtype=np.bool_)
        buffers = [array('q'),array('i'),array('d'),array('q'),array('i'),array('d')]
        for symbol in symbols:
            buffers[0].append(len(buffers[1]));buffers[3].append(len(buffers[4]))
            parts = prices._series.pop(symbol,None)
            if parts is not None:
                for target,part in zip((1,2,4,5),parts,strict=True):buffers[target].extend(part)
        buffers[0].append(len(buffers[1]));buffers[3].append(len(buffers[4]))
        price_stats = dict(prices.stats)
        prices.close()
        for name,buffer,dtype in zip(('raw_offsets','raw_days','raw_values',
                'adjusted_offsets','adjusted_days','adjusted_values'),buffers,
                (np.int64,np.int32,np.float64,np.int64,np.int32,np.float64),strict=True):
            setattr(self,name,np.frombuffer(buffer,dtype=dtype))
        if np.any(self.raw_values<=0) or np.any(self.adjusted_values<=0):
            raise ValueError('Prepared price inputs must be strictly positive.')
        rows = []
        report_symbol = []
        row_ids = {}
        for symbol,history in self.books[0].items():
            for row in history:
                row_ids[id(row)] = len(rows)
                rows.append(row);report_symbol.append(self.symbol_ids[symbol])
        self.report_rows = tuple(rows)
        self.report_symbol = np.asarray(report_symbol,dtype=np.int32)
        self.report_fiscal = np.asarray([row['fiscal'].toordinal() for row in rows],dtype=np.int32)
        self.report_known = np.asarray([row['known'].toordinal() for row in rows],dtype=np.int32)
        self.report_cap = np.asarray([row['market_cap'] for row in rows],dtype=np.float64)
        self.report_enterprise = np.asarray([row['enterprise'] for row in rows],dtype=np.float64)
        self.report_yield = np.asarray([row['yield'] for row in rows],dtype=np.float64)
        self.pool_offsets,self.pool_report_ids,self.pool_known,self.pool_fiscal = {},{},{},{}
        for pool,book in zip(('cached','legacy'),self.books,strict=True):
            offsets,identities = [0],[]
            for symbol in symbols:
                history = book.get(symbol,[])
                known = [row['known'].toordinal() for row in history]
                fiscal = [row['fiscal'].toordinal() for row in history]
                if known!=sorted(known) or fiscal!=sorted(fiscal):
                    raise ValueError('Prepared report histories must be temporally ordered.')
                identities.extend(row_ids[id(row)] for row in history)
                offsets.append(len(identities))
            self.pool_offsets[pool] = np.asarray(offsets,dtype=np.int64)
            self.pool_report_ids[pool] = np.asarray(identities,dtype=np.int32)
            self.pool_known[pool] = self.report_known[self.pool_report_ids[pool]]
            self.pool_fiscal[pool] = self.report_fiscal[self.pool_report_ids[pool]]
        report_setup = time.perf_counter()
        self.average_3y = np.full(len(rows),np.nan,dtype=np.float64)
        self.financial_parameters = np.full((len(rows),len(self.policy.parameter_names)),np.nan,dtype=np.float64)
        for index,row in enumerate(rows):
            symbol = symbols[int(self.report_symbol[index])]
            average = schedules.metrics.annual_average(self.histories[symbol],str(row['fiscal']),3)
            if average is not None:self.average_3y[index] = average
            self.financial_parameters[index] = self.policy.specialize_financial(
                str(row['fiscal']),self.financials.get(symbol,{}))
        generation = source.execute("SELECT value FROM metadata WHERE key='daily_inputs'").fetchone()
        self.generation = generation[0] if generation else None
        database = next((row[2] for row in source.execute('PRAGMA database_list') if row[1]=='main'),'')
        self.database_path = database
        signature = hashlib.sha256(json.dumps(dict(generation=self.generation,
            policy=self.policy.signature, symbols=symbols, companies=self.companies,
            sessions=self.sessions,treasury=list(zip(self.treasury_days,self.treasury_values)),
            bankruptcy=sorted(self.bankrupt)),
            sort_keys=True,separators=(',',':'),allow_nan=False).encode())
        numeric_bytes = 0
        for key,value in sorted(vars(self).items()):
            arrays = [(key,value)] if isinstance(value,np.ndarray) else (
                [(key+'.'+name,item) for name,item in sorted(value.items()) if isinstance(item,np.ndarray)]
                if isinstance(value,dict) else [])
            for name,item in arrays:
                signature.update(name.encode());signature.update(str(item.dtype).encode())
                signature.update(str(item.shape).encode())
                if item.size:signature.update(memoryview(item).cast('B'))
                numeric_bytes += item.nbytes
        self.signature = signature.hexdigest()
        self.stats = dict(load_seconds=time.perf_counter()-began,
            report_specialization_seconds=time.perf_counter()-report_setup,
            price_loading=price_stats, symbols=len(symbols),reports=len(rows),
            policy_sha256=self.policy.signature, input_identity=self.signature,
            numeric_payload_bytes=numeric_bytes)
        self._freeze()

    def _freeze(self):
        for value in vars(self).values():
            if isinstance(value,np.ndarray):value.flags.writeable=False
            if isinstance(value,dict):
                for item in value.values():
                    if isinstance(item,np.ndarray):item.flags.writeable=False

    def close(self):
        """Release owned numeric arrays; leave the caller's connection open."""
        for key,value in list(vars(self).items()):
            if isinstance(value,np.ndarray):setattr(self,key,np.empty(0))
        self.pool_offsets.clear();self.pool_report_ids.clear()
        self.pool_known.clear();self.pool_fiscal.clear()


class RequestPlan:
    """Request work requirements, without retained factors or selected results.

    Preserve every dated-book occurrence and its order. Resolve calendar targets
    and requested lookup dependencies once. Mandatory snapshot and exit inputs
    remain present even when no threshold consumes the trailing-price inputs.
    """
    def __init__(self, request, inputs):
        self.options = dict(request.get('options', request))
        self.needed = frozenset(condition['field'] for condition in
                                self.options.get('filters', []) or [])
        dependencies = set()
        def collect(node):
            if node[0] == 'input':
                dependencies.add(node[1])
            else:
                for child in node[1:]:
                    if isinstance(child, tuple): collect(child)
        # Both ranking pairs remain exposed to the unchanged SQL selector. The
        # mandatory slots also support source guards before numeric use.
        outputs = ('cap', 'ev', 'ebitda', 'return_value', 'multiple', 'yield_value',
                   'metric3_multiple', 'metric3_yield')
        outputs += tuple('filter_' + field for field in self.needed)
        for name in outputs:
            collect(inputs.policy.expanded(name))
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
        books = [(date.fromisoformat(str(a)),date.fromisoformat(str(b)),pool) for a,b,pool in book_batch]
        if any(pool not in ('cached','legacy') for a,b,pool in books):raise ValueError('Unknown candidate pool.')
        entries = np.asarray([a.toordinal() for a,b,pool in books],dtype=np.int32)
        exits = np.asarray([b.toordinal() for a,b,pool in books],dtype=np.int32)
        inputs,policy = self.inputs,self.policy
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
            if lookup_days[row,1]:
                second.append((symbol,int(lookup_days[row,1]),1,True));locations.append((row,2))
        execute(second,locations)
        self._time('lookup_seconds',started)
        started = time.perf_counter()
        matrix = np.full((len(rows),len(policy.input_names)),np.nan,dtype=np.float64)
        ii = policy.input_index
        treasuries = []
        for entry,exit_day,pool in books:
            index = bisect_right(inputs.treasury_days,str(entry))-1
            treasuries.append(float(inputs.treasury_values[index]) if index>=0 else 0.)
        if plan is not None:
            for key, values in (('report_cap', inputs.report_cap),
                    ('report_enterprise', inputs.report_enterprise),
                    ('report_yield', inputs.report_yield), ('average_3y', inputs.average_3y)):
                matrix[:, ii[key]] = values[row_reports]
            matrix[:, ii['treasury']] = np.asarray(treasuries)[row_books]
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
                entry,exit_day,pool = books[book]
                for key,value in (('report_cap',inputs.report_cap[report]),
                        ('report_enterprise',inputs.report_enterprise[report]),('report_yield',inputs.report_yield[report]),
                        ('bankruptcy',float((entry.year,inputs.symbols[symbol]) in inputs.bankrupt)),
                        ('average_3y',inputs.average_3y[report]),('treasury',treasuries[book])):
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
            pair = inputs.s.metrics.current_multiple(metric_observation,inputs.histories[symbol])
            current_pair = pair
            average = inputs.average_3y[report]
            pair = policy._three(metric_observation,inputs.histories[symbol],values,
                                  None if np.isnan(average) else float(average))
            self._encode_candidate(results[book], symbol, int(ranks[book,symbol_id]) or None,
                                   observation, current_pair, pair, values, needed)
        return accepted

    def close(self):
        self.trace = {}


def attach(inputs,policy=None,limits=None):
    return PythonExecutor(inputs,policy,limits)
