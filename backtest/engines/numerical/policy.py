"""Source-derived financial policy without numerical-backend import effects.

Construction uses only the standard library and actual application functions.
NumPy is loaded only by matrix evaluation and financial specialization.
"""
from backtest.financial import rules, books as financial_books, metrics
from backtest.inputs import research
from backtest import screening, selection
import ast
import copy
from datetime import date
from functools import cached_property
import hashlib
import inspect
import json
import math
from pathlib import Path
import textwrap
import types

ROOT = Path(__file__).resolve().parents[3]

FINANCIAL_FIELDS = ('pe', 'pb', 'fcf', 'fcf_yield', 'price_fcf',
                    'profit_margin', 'roe', 'current_ratio', 'interest_coverage',
                    'debt_equity', 'peg', 'operating_yield_spread_3y')
FACTOR_VERSION = 1

# Keep capability admission separate from request validation. All current
# threshold fields have source-derived implementations; unknown catalogs fail.
UNSUPPORTED_THRESHOLDS = frozenset()


def require_supported(options):
    """Reject formula intent before readiness, inputs or numerical execution.

    Presence is intent even for an empty/null payload. This guard defines no
    accepted custom application format and never substitutes a built-in metric.
    """
    formula_fields={'strategy_version','variables','ranking','conditions',
                    'selection','scalar_selection','selection_plan','program',
                    'definition','formula','bundle'}
    formula_formats={'scalar-selection-plan','scalar-selection','formula-program',
                     'variable-definition','variable-bundle','formula-evaluation'}
    if (formula_fields.intersection(options) or isinstance(options.get('format'),str) and options['format'] in formula_formats
            or any(isinstance(item,dict) and 'variable_id' in item
                   for item in options.get('filters',[]) or [])):
        raise ValueError('UNSUPPORTED_CAPABILITY: New engine — experimental does not support custom formula selection.')
    for condition in options.get('filters', []) or []:
        if isinstance(condition, dict) and condition.get('field') in UNSUPPORTED_THRESHOLDS:
            raise ValueError('New engine — experimental does not support filter '
                             + condition['field'] + '. Submit a new run with Original.')


def _tree(function):
    return ast.parse(textwrap.dedent(inspect.getsource(function))).body[0]


def _signature(tree, names):
    if not isinstance(tree,ast.FunctionDef):
        raise ValueError('Unsupported source financial function kind.')
    args=tree.args
    if (tree.decorator_list or getattr(tree,'type_params',[]) or tree.returns
            or [a.arg for a in args.args]!=names or any(a.annotation for a in args.args)
            or args.posonlyargs or args.kwonlyargs or args.defaults or args.vararg or args.kwarg):
        raise ValueError('Unsupported source financial interface.')


def _body(tree):
    body=tree.body
    return body[1:] if body and isinstance(body[0],ast.Expr) and isinstance(body[0].value,ast.Constant) and isinstance(body[0].value.value,str) else body


def _normalized_snapshot():
    """Expand only the agreed entry helper and its unavailable/unpack wrapper.

    Every policy projection consumes this tree. This is deliberately not a
    general inliner. Unknown calls, signatures and result bindings fail closed.
    """
    helper=_tree(financial_books.entry_valuation)
    wrapper=_tree(financial_books.snapshot)
    _signature(helper,['statement','entry_day','lookup'])
    _signature(wrapper,['statement','entry_day','exit_day','lookup','bankruptcy'])
    body=_body(helper); wrapped=_body(wrapper)
    expected=ast.parse("valuation=entry_valuation(statement,entry_day,lookup)\nif valuation is None:\n    return None\nfiscal_px,entry_px,cap,ev,ebitda=valuation").body
    if (len(wrapped)<4 or [ast.dump(n) for n in wrapped[:3]]!=[ast.dump(n) for n in expected]
            or financial_books.snapshot.__globals__.get('entry_valuation') is not financial_books.entry_valuation
            or not isinstance(body[-1],ast.Return)
            or ast.dump(body[-1].value)!=ast.dump(ast.parse('fiscal_px,entry_px,cap,ev,ebitda',mode='eval').body)):
        raise ValueError('Unsupported source entry valuation wrapper.')
    assigned=[node.targets[0].id for node in body if isinstance(node,ast.Assign)
              and len(node.targets)==1 and isinstance(node.targets[0],ast.Name)]
    if assigned!=['fiscal_px','entry_px','cap','ev','ebitda']:
        raise ValueError('Unsupported source entry valuation bindings.')
    assignments=[node for node in ast.walk(ast.Module(body=body,type_ignores=[])) if isinstance(node,ast.Assign)]
    if len(assignments)!=5 or any(node not in body for node in assignments):
        raise ValueError('Unsupported source entry valuation rebinding.')
    expected_lookups=ast.parse("fiscal_px=lookup(statement['fiscal'],'price',False,7)\nentry_px=lookup(entry_day,'price',True,4)").body
    if [ast.dump(node) for node in body[:2]]!=[ast.dump(node) for node in expected_lookups]:
        raise ValueError('Unsupported source entry valuation lookup.')

    for node in ast.walk(ast.Module(body=wrapped[3:],type_ignores=[])):
        if isinstance(node,ast.Assign) and (len(node.targets)!=1 or not isinstance(node.targets[0],ast.Name)
                or node.targets[0].id not in {'start','end','status','ret'}):
            raise ValueError('Unsupported source snapshot wrapper binding.')
        if isinstance(node,ast.Call) and not (isinstance(node.func,ast.Name)
                and ((node.func.id=='lookup' and len(node.args)==4)
                     or (node.func.id=='str' and len(node.args)==1)) and not node.keywords):
            raise ValueError('Unsupported source snapshot wrapper call.')
    allowed=(ast.FunctionDef,ast.arguments,ast.arg,ast.Assign,ast.If,ast.Return,
             ast.Constant,ast.Name,ast.Load,ast.Store,ast.Subscript,ast.Tuple,
             ast.BinOp,ast.UnaryOp,ast.BoolOp,ast.Compare,ast.Call,
             ast.Add,ast.Sub,ast.Mult,ast.Div,ast.USub,ast.UAdd,ast.And,ast.Or,
             ast.Not,ast.Eq,ast.NotEq,ast.Lt,ast.LtE,ast.Gt,ast.GtE,ast.Is,ast.IsNot)
    names={'statement','entry_day','lookup','fiscal_px','entry_px','cap','ev','ebitda'}
    for node in ast.walk(ast.Module(body=body,type_ignores=[])):
        if isinstance(node,ast.Module):continue
        if not isinstance(node,allowed):raise ValueError('Unsupported source entry valuation structure.')
        if isinstance(node,ast.Name) and node.id not in names:raise ValueError('Unsupported source entry valuation dependency.')
        if isinstance(node,ast.Call) and not (isinstance(node.func,ast.Name) and node.func.id=='lookup' and not node.keywords):raise ValueError('Unsupported source entry valuation call.')
        if isinstance(node,ast.Return) and node is not body[-1] and not (isinstance(node.value,ast.Constant) and node.value.value is None):raise ValueError('Unsupported source entry valuation return.')
    wrapper.body=copy.deepcopy(body[:-1]+wrapped[3:])
    return ast.fix_missing_locations(wrapper)


def _financial_expression(function, names):
    tree=_tree(function);_signature(tree,names);body=_body(tree)
    if len(body)!=1 or not isinstance(body[0],ast.Return):
        raise ValueError('Unsupported source financial expression.')
    expression=body[0].value
    allowed=(ast.BinOp,ast.Name,ast.Load,ast.Constant,ast.Add,ast.Sub,ast.Mult,ast.Div,ast.USub,ast.UAdd,ast.UnaryOp)
    if any(not isinstance(node,allowed) or isinstance(node,ast.Name) and node.id not in names for node in ast.walk(expression)):
        raise ValueError('Unsupported source financial expression.')
    return copy.deepcopy(expression)


def _metric_tree(function):
    """Accept only explicit, local metric expressions before removing inputs.

    Namespace inspection, calls into arbitrary code and additional scopes can
    hide parameter use. They are outside this adapter's supported source forms.
    Ordinary calculators keep their full Python interfaces.
    """
    tree = _tree(function)
    args = tree.args
    if (tree.decorator_list or getattr(tree, 'type_params', [])
            or [a.arg for a in args.args] != ['observation', 'history']
            or args.posonlyargs or args.kwonlyargs or args.defaults
            or args.vararg or args.kwarg or tree.returns
            or any(a.annotation for a in args.args)):
        raise ValueError('Unsupported source metric interface.')
    allowed = (ast.FunctionDef, ast.arguments, ast.arg, ast.Assign, ast.If,
               ast.Return, ast.Expr, ast.Constant, ast.Name, ast.Load, ast.Store,
               ast.Subscript, ast.Tuple, ast.BinOp, ast.UnaryOp, ast.BoolOp,
               ast.Compare, ast.IfExp, ast.Call, ast.Attribute,
               ast.Add, ast.Sub, ast.Mult, ast.Div, ast.USub, ast.UAdd,
               ast.And, ast.Or, ast.Not, ast.Eq, ast.NotEq, ast.Lt, ast.LtE,
               ast.Gt, ast.GtE, ast.Is, ast.IsNot)
    names = {'observation', 'history', 'math', 'annual_average'}
    for node in ast.walk(tree):
        if not isinstance(node, allowed) or isinstance(node, ast.FunctionDef) and node is not tree:
            raise ValueError('Unsupported source metric structure.')
        if isinstance(node, ast.Assign):
            if (len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name)
                    or node.targets[0].id in names
                    or node.targets[0].id in ('numeric_values', 'supplied_average')):
                raise ValueError('Unsupported source metric binding.')
    names.update(node.targets[0].id for node in ast.walk(tree) if isinstance(node, ast.Assign))
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and not (isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)):
            raise ValueError('Unsupported source metric expression statement.')
        if isinstance(node, ast.Name) and node.id not in names:
            raise ValueError('Unsupported source metric dependency.')
        if isinstance(node, ast.Attribute) and not (isinstance(node.value, ast.Name)
                and node.value.id == 'math' and node.attr == 'isfinite'
                and function.__globals__.get('math') is math):
            raise ValueError('Unsupported source metric attribute.')
        if isinstance(node, ast.Call) and not (
                isinstance(node.func, ast.Name) and node.func.id == 'annual_average'
                or isinstance(node.func, ast.Attribute) and node.func.attr == 'isfinite'):
            raise ValueError('Unsupported source metric call.')
    return tree


def _compile_metric(tree, function):
    if any(isinstance(node, ast.Name) and node.id in ('history', 'annual_average')
           for node in ast.walk(tree)):
        raise ValueError('Source metric requires unsupported annual history.')
    tree.args.args = [arg for arg in tree.args.args if arg.arg != 'history']
    module = ast.fix_missing_locations(ast.Module(body=[tree], type_ignores=[]))
    namespace = dict(function.__globals__)
    exec(compile(module, '<source-derived ranking metric>', 'exec'), namespace)
    return namespace[tree.name]


def _schema_tree(node):
    """Canonical semantic AST, including Python 3.11/3.12 function nodes.

    Python 3.12 adds empty type_params metadata to ordinary functions. It does
    not change this policy. Retain nonempty fields and ignore source locations.
    """
    def walk(value):
        if isinstance(value, ast.AST):
            return [type(value).__name__, {name: walk(item) for name, item in ast.iter_fields(value)
                    if not (name == 'type_params' and not item)}]
        if isinstance(value, list): return [walk(item) for item in value]
        return value
    return json.dumps(walk(node), sort_keys=True, separators=(',', ':'), allow_nan=False)


class _Symbol:
    """Trace dated valuation inputs while source code chooses annual inputs."""
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

    def __le__(self, other):
        # Snapshot eligibility requires positive EV before a row is exposed.
        # No other symbolic comparison is an assumed financial guard.
        if self.node == ('input', 'ev') and other == 0:
            return False
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
            return ('var', node[1]) if node[1] in ('cap', 'ev') else node
        return (node[0], *(walk(child) for child in node[1:]))
    node = value.node if isinstance(value, _Symbol) else ('const', float(value))
    return walk(node), parameters


class PolicyProgram:
    """One source-derived float64 expression program and source control adapter.

    Expressions use the small tuple IR documented by ``expanded``. Annual
    specialization executes the authoritative calculators; dated valuation
    and Treasury operations become traced expressions. Unsupported numeric syntax,
    catalog changes or a changed expression shape fail rather than fall back.
    Compiled guards are an optional capability, requested through ``decisions``.
    Their translator and identity are not prerequisites for source execution.
    """
    def __init__(self, *, bankrupt=None):
        m = metrics
        if tuple(m.METRICS) != ('ev_ebitda', 'ev_ebitda_3y'):
            raise ValueError('Unsupported ranking catalog for candidate experiment.')
        if set(m.FILTERS) != set(FINANCIAL_FIELDS) | UNSUPPORTED_THRESHOLDS | {
                'return_1y', 'return_3y', 'market_cap', 'enterprise_value',
                'ev_ebitda', 'ev_ebitda_3y', 'ebitda_yield'}:
            raise ValueError('Unsupported threshold catalog for candidate experiment.')
        self._financial = types.FunctionType(m.financial_values.__code__,
            dict(m.financial_values.__globals__, math=_Math()),
            m.financial_values.__name__, m.financial_values.__defaults__)
        self._operating_spread = types.FunctionType(m.operating_yield_spread.__code__,
            dict(m.operating_yield_spread.__globals__, math=_Math()),
            m.operating_yield_spread.__name__, m.operating_yield_spread.__defaults__)
        annual = {f'{year}-06-30': dict(netIncome=120., totalStockholdersEquity=400.,
                  freeCashFlow=30., revenue=900., operatingIncome=160., totalCurrentAssets=150.,
                  totalCurrentLiabilities=60., ebit=160., interestExpense=10.,
                  totalDebt=90., epsDiluted=float(2 ** (year-2011)))
                  for year in range(2011, 2015)}
        probe = self._annual_values('2014-06-30', annual)
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
            'trailing_3y', 'treasury', 'treasury10') + self.parameter_names
        self.input_index = {name:i for i,name in enumerate(self.input_names)}
        snapshot = _normalized_snapshot()
        self.snapshot_tree = copy.deepcopy(snapshot)
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
        spy_expression = _financial_expression(financial_books.benchmark_return,['entry_price','exit_price'])
        self._spy_code = compile(ast.fix_missing_locations(ast.Expression(spy_expression)),
                                 '<source-derived SPY return>','eval')
        self.spy_expression = ast.dump(spy_expression,include_attributes=False)
        spread = _financial_expression(financial_books.yield_spread,['earnings_yield','treasury_yield'])
        expressions.append(('excess_yield',self._lower(spread,
                           names={'earnings_yield':('var','yield_value'),'treasury_yield':('input','treasury')})))
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
        supported = {field: descriptor for field, descriptor in m.FILTERS.items()
                     if field not in UNSUPPORTED_THRESHOLDS}
        expressions.extend(('filter_'+field,field_expressions[field]) for field in supported)
        self.expressions = tuple(expressions)
        self.expression_map = dict(expressions)
        self.output_names = tuple(name for name,unused in expressions)
        self.output_index = {name:i for i,name in enumerate(self.output_names)}
        source_files = {Path(function.__code__.co_filename).resolve()
                        for function in (financial_books.snapshot,financial_books.eligible,
                                         m.current_multiple,m.financial_values,m.operating_yield_spread,
                                         financial_books.entry_valuation,financial_books.benchmark_return,financial_books.yield_spread,m.three_year_multiple)}
        source_files.update(Path(module.__file__).resolve() for module in
            (rules,research.market,research,research.revalue,research.legacy,screening,selection))
        source_files.update(ROOT/name for name in ("backtest/engines/original/schedules.py","backtest/engines/original/book_batch.py","backtest/inputs/daily.py"))
        self.source_hashes = {path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else path.as_posix():hashlib.sha256(path.read_bytes()).hexdigest()
                              for path in sorted(source_files)}
        self.source_paths = tuple(sorted(source_files))
        identity = dict(sources=self.source_hashes, inputs=self.input_names,
                        max_age=rules.MAX_AGE.days,
                        buffer=rules.BUFFER,
                        minimum_cap=rules.MIN_MARKET_CAP,
                        minimum_ev=rules.MIN_EV,
                        bankruptcy=sorted(rules.BANKRUPT if bankrupt is None else bankrupt),
                        spy_expression=self.spy_expression,
                        expressions=self.expressions)
        self.signature = hashlib.sha256(json.dumps(identity,sort_keys=True,
                            separators=(',',':'),allow_nan=False).encode()).hexdigest()
        self._row_namespace = {}
        exec(self.python_source('_policy_row'), self._row_namespace)
        self._row = self._row_namespace['_policy_row']
        self._snapshot = self._snapshot_adapter(snapshot,financial_books.snapshot)
        self._current = self._current_adapter(m.current_multiple)
        self._three = self._three_adapter(m.three_year_multiple)
        numeric_observation = dict(fiscal='2014-06-30',market_cap=150.,enterprise_value=200.,
                                   ev_ebitda=4.,ebitda_yield=.25)
        history = [dict(fiscal=f'{year}-06-30',ebitda=20.) for year in range(2011,2015)]
        evaluated = m.evaluate(numeric_observation,history)
        self.filter_order = tuple(m.filter_values(numeric_observation,evaluated,date(2015,1,2),
                                    lambda day,*args:(day,1.),annual,0.))
        self.ranking_outputs = {'ev_ebitda': ('multiple', 'yield_value'),
                                'ev_ebitda_3y': ('metric3_multiple', 'metric3_yield')}
        # This is a binding to the source catalog, not a formula registry.
        self.fields = {
            'metrics': {key: dict(descriptor=dict(value), outputs=self.ranking_outputs[key],
                                 validity='average_3y' if key == 'ev_ebitda_3y' else 'entry')
                        for key, value in m.METRICS.items()},
            'thresholds': {key: dict(descriptor=dict(value), outputs=('filter_' + key,),
                validity='finite' if key in FINANCIAL_FIELDS else 'pair' if key in m.METRICS
                else 'trailing' if key in ('return_1y', 'return_3y') else 'entry')
                           for key, value in supported.items()}}
        self._entry, entry_source = self._entry_adapter(snapshot)
        self.trailing, trailing_source = self._trailing_adapter(filters)
        self.field_schema = hashlib.sha256(json.dumps(dict(version=FACTOR_VERSION,
            fields=self.fields, entry=entry_source, trailing=trailing_source),
            sort_keys=True, separators=(',', ':')).encode()).hexdigest()

    @cached_property
    def decisions(self):
        """Translate and bind optional compiled guards on explicit request.

        Unsupported guard syntax fails this capability, not source execution.
        The base policy signature remains independent of generated guard code.
        """
        from backtest.engines.numerical.decisions import CandidateDecisionProgram
        return CandidateDecisionProgram(self, lambda function: copy.deepcopy(self.snapshot_tree)
                                        if function is financial_books.snapshot else _tree(function))

    def dependencies(self, outputs):
        """Return required numeric inputs without changing expression order."""
        result = set()
        def walk(node):
            if node[0] == 'input': result.add(node[1])
            elif node[0] != 'const':
                for child in node[1:]: walk(child)
        for name in outputs: walk(self.expanded(name))
        return frozenset(result)

    def projection(self, outputs):
        """Select outputs and their derived prerequisites in original order."""
        required = set()
        def add(name):
            if name in required: return
            required.add(name)
            def walk(node):
                if node[0] == 'var': add(node[1])
                elif node[0] not in ('input', 'const'):
                    for child in node[1:]: walk(child)
            walk(self.expression_map[name])
        for name in outputs: add(name)
        return tuple(name for name in self.output_names if name in required)

    def _entry_adapter(self, snapshot):
        """Project the source prefix before adjusted holding-entry decisions."""
        tree = copy.deepcopy(snapshot)
        boundary = next((i for i, node in enumerate(tree.body) if isinstance(node, ast.Assign)
                        and isinstance(node.targets[0], ast.Name) and node.targets[0].id == 'start'), None)
        if boundary is None: raise ValueError('Unsupported entry policy boundary.')
        tree.body = tree.body[:boundary]
        allowed = {'statement', 'entry_day', 'lookup', 'cap', 'ev', 'ebitda', 'fiscal_px', 'entry_px'}
        if any(isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and n.id not in allowed
               for node in tree.body for n in ast.walk(node)):
            raise ValueError('Unsupported entry policy dependency.')
        tree.name = '_entry'
        tree.args.args = [ast.arg(arg=n) for n in ('statement', 'entry_day', 'lookup', 'numeric_values')]
        for node in tree.body:
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
                name = node.targets[0].id
                if name in ('cap', 'ev', 'ebitda'):
                    node.value = ast.Subscript(ast.Name('numeric_values', ast.Load()), ast.Constant(name), ast.Load())
        tree.body.append(ast.Return(ast.Constant(True)))
        module = ast.fix_missing_locations(ast.Module(body=[tree], type_ignores=[]))
        namespace = {}
        exec(compile(module, '<source-derived entry>', 'exec'), namespace)
        return namespace['_entry'], _schema_tree(module)

    def _trailing_adapter(self, filters):
        """Project source target dates, lookup tolerances and endpoint guards."""
        tree = copy.deepcopy(filters)
        loop = next(node for node in tree.body if isinstance(node, ast.For))
        guard = next(node for node in loop.body if isinstance(node, ast.If))
        if guard.orelse or len(guard.body) != 1 or not isinstance(guard.body[0], ast.Assign):
            raise ValueError('Unsupported trailing field guard.')
        guard.body[0].value = ast.Constant(True)
        end = next(node for node in tree.body if isinstance(node, ast.Assign)
                   and isinstance(node.targets[0], ast.Name) and node.targets[0].id == 'end')
        tree.name = '_trailing'
        tree.args.args = [ast.arg(arg=n) for n in ('day', 'lookup')]
        tree.args.defaults = []
        tree.body = [*(node for node in tree.body if isinstance(node, ast.ImportFrom)),
                     ast.Assign([ast.Name('values', ast.Store())], ast.Dict([], [])),
                     end, loop, ast.Return(ast.Name('values', ast.Load()))]
        module = ast.fix_missing_locations(ast.Module(body=[tree], type_ignores=[]))
        namespace = dict(metrics.filter_values.__globals__)
        exec(compile(module, '<source-derived trailing availability>', 'exec'), namespace)
        return namespace['_trailing'], _schema_tree(module)

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

    def python_source(self,name='_policy_row', outputs=None):
        def emit(node):
            op = node[0]
            if op=='input':return f'x[{self.input_index[node[1]]}]'
            if op=='const':return repr(node[1])
            if op=='var':return node[1]
            if op=='neg':return f'(-{emit(node[1])})'
            if op=='if':return f'({emit(node[2])} if {emit(node[1])} else {emit(node[3])})'
            operator = {'add':'+','sub':'-','mul':'*','div':'/'}[op]
            return f'({emit(node[1])} {operator} {emit(node[2])})'
        selected = self.output_names if outputs is None else tuple(outputs)
        required = set(self.projection(selected))
        statements = [f'def {name}(x):']
        statements.extend(f'    {key} = {emit(value)}' for key,value in self.expressions if key in required)
        statements.append('    return ('+', '.join(selected)+',)')
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

    def _annual_values(self, fiscal, reports):
        """Execute annual policy with only validated dated inputs symbolic."""
        observation = dict(fiscal=fiscal, market_cap=_Symbol(('input', 'cap')),
                           enterprise_value=_Symbol(('input', 'ev')))
        values = self._financial(observation, reports)
        spread = self._operating_spread(observation, reports, _Symbol(('input', 'treasury10')))
        if spread is not None:
            values['operating_yield_spread_3y'] = spread
        return values

    def specialize_financial(self,fiscal,reports):
        """Bind source-selected annual constants without dated market inputs.

        Missing annual inputs leave only the affected threshold unavailable.
        Unsupported operations or a changed expression shape fail export.
        """
        import numpy as np
        result = np.full(len(self.parameter_names),np.nan,dtype=np.float64)
        for field,value in self._annual_values(fiscal,reports).items():
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

    def _current_adapter(self, function):
        """Execute the authoritative current-metric body without unused history.

        Construction rejects source whose remaining behavior requires history.
        """
        tree = _metric_tree(function)
        tree.name = '_source_current'
        return _compile_metric(tree, function)

    def _three_adapter(self,function):
        """Execute source guards with prepared average and numeric outputs.

        Validate substituted expressions and reject remaining history use.
        """
        tree = _metric_tree(function)
        assignments = {name: [node for node in ast.walk(tree)
                       if isinstance(node, ast.Assign) and node.targets[0].id == name]
                       for name in ('average', 'multiple')}
        if any(len(nodes) != 1 or nodes[0] not in tree.body for nodes in assignments.values()):
            raise ValueError('Ambiguous source metric substitution.')
        average, multiple = (assignments[name][0] for name in ('average', 'multiple'))
        expected = ast.parse("annual_average(history, observation['fiscal'], 3)", mode='eval').body
        if (ast.dump(average.value) != ast.dump(expected)
                or function.__globals__.get('annual_average') is not metrics.annual_average
                or self._lower(multiple.value, names={'average': ('input', 'average_3y')}) != self.expression_map['metric3_multiple']):
            raise ValueError('Unsupported prepared source metric substitution.')
        returns = [node for node in ast.walk(tree) if isinstance(node, ast.Return)
                   and not (isinstance(node.value, ast.Constant) and node.value.value is None)]
        for node in returns:
            value = node.value
            if (not isinstance(value, ast.Tuple) or len(value.elts) != 2
                    or not isinstance(value.elts[0], ast.Name) or value.elts[0].id != 'multiple'
                    or self._lower(value.elts[1], names={'multiple': ('var', 'metric3_multiple')}) != self.expression_map['metric3_yield']):
                raise ValueError('Unsupported source metric result substitution.')
        tree.name = '_source_three_year'
        tree.args.args.extend([ast.arg(arg='numeric_values'),ast.arg(arg='supplied_average')])
        average.value = ast.Name('supplied_average', ast.Load())
        multiple.value = ast.Subscript(ast.Name('numeric_values',ast.Load()),
                           ast.Constant(self.output_index['metric3_multiple']),ast.Load())
        for node in returns:
            node.value=ast.Tuple([ast.Subscript(ast.Name('numeric_values',ast.Load()),
                            ast.Constant(self.output_index[key]),ast.Load())
                            for key in ('metric3_multiple','metric3_yield')],ast.Load())
        return _compile_metric(tree, function)
