"""Source-derived financial policy without numerical-backend import effects.

Construction uses only the standard library and actual application functions.
NumPy is loaded only by matrix evaluation and financial specialization.
"""
import ast
import copy
from datetime import date
import hashlib
import inspect
import json
import math
from pathlib import Path
import textwrap
import types

from numerical_decisions import CandidateDecisionProgram

FINANCIAL_FIELDS = ('pe', 'pb', 'fcf', 'fcf_yield', 'price_fcf',
                    'profit_margin', 'roe', 'current_ratio', 'interest_coverage',
                    'debt_equity', 'peg')


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
        import numpy as np
        matrix = np.asarray(matrix,dtype=np.float64)
        output = np.empty((len(matrix),len(self.output_names)),dtype=np.float64)
        with np.errstate(all='ignore'):
            for row,values in enumerate(matrix):output[row] = self._row(values)
        return output

    def spy_return(self,entry_price,exit_price):
        return eval(self._spy_code,{},dict(entry_price=entry_price,exit_price=exit_price))

    def specialize_financial(self,fiscal,reports):
        import numpy as np
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
