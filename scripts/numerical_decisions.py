"""Bounded AST lowering for source-derived candidate decisions.

Lookup values use validity flags, ordinal days and prices. No Python optional
objects cross the compiled boundary. Source policy remains authoritative.
"""
import ast


class CandidateDecisionProgram:
    """Execute snapshot and metric availability policy from the current source
    over resolved candidate inputs. Preserve rejection, actual dates, exit status
    and missing ranking pairs. Unsupported policy structure fails attachment.
    """
    def __init__(self, policy, tree):
        self.policy = policy
        self.statuses = []
        self.functions = {}
        sources = (
            ('snapshot', policy.s.financial_books.snapshot,
             ['statement', 'entry_day', 'exit_day', 'lookup', 'bankruptcy']),
            ('eligible', policy.s.financial_books.eligible, ['pool', 'cap', 'ev']),
            ('current', policy.s.metrics.current_multiple, ['observation', 'history']),
            ('three', policy.s.metrics.three_year_multiple, ['observation', 'history']))
        for kind, function, arguments in sources:
            node = tree(function)
            if (node.decorator_list or node.args.defaults or node.args.kwonlyargs
                    or node.args.posonlyargs or node.args.vararg or node.args.kwarg
                    or [arg.arg for arg in node.args.args] != arguments):
                self.fail('function signature')
            self.kind = kind
            self.locals = set()
            self.lookups = set()
            self.optional_average = False
            body = self.statements(node.body, 1)
            if not body or not isinstance(node.body[-1], ast.Return):
                self.fail('terminal return')
            args = ('days, prices, numeric, fiscal_day, entry_day, exit_day, entry_year, exit_year, bankruptcy'
                    if kind == 'snapshot' else 'numeric, pool' if kind == 'eligible'
                    else 'numeric, average, average_valid')
            self.functions[kind] = f'def _decision_{kind}({args}):\n' + '\n'.join(body) + '\n'
        self.source = '\n'.join(self.functions.values())

    @staticmethod
    def fail(detail):
        raise ValueError('Unsupported candidate policy structure: ' + detail)

    @staticmethod
    def dump(node):
        return ast.dump(node, include_attributes=False)

    def numeric(self, name):
        return f'numeric[{self.policy.output_index[name]}]'

    def value_kind(self, node):
        """Check operations whose meaning depends on the representation type."""
        if isinstance(node, ast.Constant):
            if isinstance(node.value,str):return 'status' if self.kind == 'snapshot' else 'pool'
            return 'none' if node.value is None else 'number'
        if isinstance(node, ast.Name):
            if node.id in ('entry_day','exit_day'):return 'date'
            if node.id == 'status':return 'status'
            if node.id == 'pool':return 'pool'
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and isinstance(node.slice, ast.Constant):
            if node.value.id in self.lookups and node.slice.value == 0:return 'date'
            if node.value.id == 'statement' and node.slice.value == 'fiscal':return 'date'
        if isinstance(node, ast.IfExp):
            left,right = self.value_kind(node.body),self.value_kind(node.orelse)
            if left != right:self.fail('mixed conditional representations')
            return left
        return 'number'

    def expression(self, node):
        if isinstance(node, ast.Constant):
            if isinstance(node.value, str):
                if self.kind == 'snapshot':
                    if node.value not in self.statuses:self.statuses.append(node.value)
                    return str(self.statuses.index(node.value) + 1)
                if node.value == 'legacy':return '1'
                self.fail('string literal')
            if isinstance(node.value, (int, float, bool)) or node.value is None:
                return repr(node.value)
        if isinstance(node, ast.Name):
            if node.id in self.locals:return node.id
            if self.kind == 'snapshot' and node.id in ('entry_day', 'exit_day', 'bankruptcy'):
                return node.id
            if self.kind == 'eligible':
                if node.id in ('cap', 'ev'):return self.numeric(node.id)
                if node.id == 'pool':return 'pool'
        if isinstance(node, ast.Attribute):
            if (isinstance(node.value, ast.Name) and node.value.id in ('entry_day', 'exit_day')
                    and node.attr == 'year' and self.kind == 'snapshot'):
                return node.value.id.replace('_day', '_year')
            if (self.kind == 'eligible' and isinstance(node.value, ast.Name)
                    and node.value.id == 'run' and node.attr in ('MIN_MARKET_CAP', 'MIN_EV')):
                return repr(getattr(self.policy.s.financial_books.run, node.attr))
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and isinstance(node.slice, ast.Constant):
            owner, key = node.value.id, node.slice.value
            if owner in self.lookups and key in (0, 1):
                return owner + ('_day' if key == 0 else '_price')
            if owner == 'statement' and key == 'fiscal' and self.kind == 'snapshot':return 'fiscal_day'
            if owner == 'observation':
                fields = {'ev_ebitda':'multiple', 'ebitda_yield':'yield_value',
                          'enterprise_value':'ev'}
                if key in fields:return self.numeric(fields[key])
        if isinstance(node, ast.Compare):
            # Missing optional lookup/annual-average state is represented by a flag.
            if (len(node.ops) == 1 and isinstance(node.ops[0], (ast.Is, ast.IsNot))
                    and isinstance(node.left, ast.Name) and isinstance(node.comparators[0], ast.Constant)
                    and node.comparators[0].value is None):
                name = node.left.id
                if name in self.lookups:valid = name + '_valid'
                elif name == 'average' and self.optional_average:valid = 'average_valid'
                else:self.fail('optional comparison')
                return f'(not {valid})' if isinstance(node.ops[0], ast.Is) else valid
            operators = {ast.Lt:'<', ast.LtE:'<=', ast.Gt:'>', ast.GtE:'>=', ast.Eq:'==', ast.NotEq:'!='}
            if any(type(op) not in operators for op in node.ops):self.fail('comparison')
            operands = [node.left,*node.comparators]
            kinds = [self.value_kind(value) for value in operands]
            if len(set(kinds)) != 1 or kinds[0] == 'none':self.fail('mixed comparison representations')
            if kinds[0] in ('status','pool') and any(not isinstance(op,(ast.Eq,ast.NotEq)) for op in node.ops):
                self.fail('ordered string comparison')
            result = self.expression(node.left)
            for op, right in zip(node.ops, node.comparators, strict=True):
                result += ' ' + operators[type(op)] + ' ' + self.expression(right)
            return '(' + result + ')'
        if isinstance(node, ast.BoolOp) and isinstance(node.op, (ast.And, ast.Or)):
            if any(self.value_kind(value) != 'number' for value in node.values):self.fail('boolean representation')
            return '(' + (' and ' if isinstance(node.op, ast.And) else ' or ').join(self.expression(value) for value in node.values) + ')'
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.Not, ast.USub, ast.UAdd)):
            if self.value_kind(node.operand) != 'number':self.fail('unary representation')
            return '(' + {ast.Not:'not ', ast.USub:'-', ast.UAdd:'+'}[type(node.op)] + self.expression(node.operand) + ')'
        if isinstance(node, ast.BinOp) and type(node.op) in (ast.Add, ast.Sub, ast.Mult, ast.Div):
            if self.value_kind(node.left) != 'number' or self.value_kind(node.right) != 'number':self.fail('arithmetic representation')
            return '(' + self.expression(node.left) + {ast.Add:'+', ast.Sub:'-', ast.Mult:'*', ast.Div:'/'}[type(node.op)] + self.expression(node.right) + ')'
        if isinstance(node, ast.IfExp):
            if self.value_kind(node.test) != 'number':self.fail('conditional representation')
            self.value_kind(node)
            return '(' + self.expression(node.body) + ' if ' + self.expression(node.test) + ' else ' + self.expression(node.orelse) + ')'
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'str'
                and len(node.args) == 1 and not node.keywords and self.kind == 'snapshot'):
            # Only known date-valued expressions can cross this representation.
            argument = node.args[0]
            is_date = (isinstance(argument, ast.Name) and argument.id in ('entry_day', 'exit_day'))
            if isinstance(argument, ast.Subscript) and isinstance(argument.value, ast.Name) and isinstance(argument.slice, ast.Constant):
                is_date = ((argument.value.id == 'statement' and argument.slice.value == 'fiscal')
                           or (argument.value.id in self.lookups and argument.slice.value == 0))
            if not is_date:self.fail('date encoding')
            return self.expression(argument)
        self.fail('expression ' + self.dump(node))

    def lookup(self, name, call, indent):
        if call.keywords or len(call.args) != 4:self.fail('lookup signature')
        target, column, forward, slack = call.args
        if not isinstance(column, ast.Constant) or not isinstance(forward, ast.Constant):self.fail('lookup binding')
        bindings = {
            ("Subscript(value=Name(id='statement', ctx=Load()), slice=Constant(value='fiscal'), ctx=Load())", 'price', False):0,
            ("Name(id='entry_day', ctx=Load())", 'price', True):1,
            ("Subscript(value=Name(id='entry_px', ctx=Load()), slice=Constant(value=0), ctx=Load())", 'adjusted', True):2,
            ("Name(id='exit_day', ctx=Load())", 'adjusted', False):3}
        key = (self.dump(target), column.value, forward.value)
        if key not in bindings:self.fail('unplanned lookup')
        if bindings[key] != {'fiscal_px':0, 'entry_px':1, 'start':2, 'end':3}[name]:
            self.fail('changed lookup slot')
        target_text = self.expression(target)
        slack_text = self.expression(slack)
        slot = bindings[key]
        self.lookups.add(name)
        prefix = '    ' * indent
        # Slot resolution is unchanged. The source call supplies its tolerance.
        return [prefix + f'{name}_day = days[{slot}]',
                prefix + f'{name}_price = prices[{slot}]',
                prefix + f'{name}_valid = {name}_day != 0 and abs({name}_day - {target_text}) <= {slack_text}']

    def numeric_dependencies(self, node):
        allowed = self.locals | self.lookups | {'statement','observation','bankruptcy'}
        if any(isinstance(value,ast.Name) and isinstance(value.ctx,ast.Load) and value.id not in allowed
               for value in ast.walk(node)):
            self.fail('numeric dependency')

    def statements(self, nodes, indent):
        result = []
        prefix = '    ' * indent
        for node in nodes:
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                if indent != 1 or result:self.fail('non-docstring expression')
                continue
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                name = node.targets[0].id
                value = node.value
                if self.kind == 'snapshot' and isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id == 'lookup':
                    if name not in ('fiscal_px', 'entry_px', 'start', 'end'):self.fail('lookup local')
                    result.extend(self.lookup(name, value, indent));continue
                if self.kind == 'snapshot' and name in ('cap', 'ev', 'ebitda', 'ret'):
                    # Arithmetic was extracted from precisely these source ASTs.
                    self.numeric_dependencies(value)
                    lowered = self.policy._lower(value)
                    output = 'return_value' if name == 'ret' else name
                    if lowered != self.policy.expression_map[output]:self.fail('changed arithmetic assignment')
                    expression = self.numeric(output)
                elif self.kind == 'three' and name == 'average':
                    expected = ast.parse("annual_average(history, observation['fiscal'], 3)", mode='eval').body
                    if self.dump(value) != self.dump(expected):self.fail('annual average binding')
                    self.optional_average = True
                    expression = 'average'
                elif self.kind == 'three' and name == 'multiple':
                    self.numeric_dependencies(value)
                    if self.policy._lower(value, names={'average':('input','average_3y')}) != self.policy.expression_map['metric3_multiple']:
                        self.fail('three-year arithmetic')
                    expression = self.numeric('metric3_multiple')
                else:
                    if name not in ('status',):self.fail('assignment target ' + name)
                    if self.value_kind(value) != 'status':self.fail('status representation')
                    expression = self.expression(value)
                self.locals.add(name)
                result.append(prefix + name + ' = ' + expression)
            elif isinstance(node, ast.If):
                if self.value_kind(node.test) != 'number':self.fail('guard representation')
                result.append(prefix + 'if ' + self.expression(node.test) + ':')
                result.extend(self.statements(node.body, indent + 1))
                if node.orelse:
                    result.append(prefix + 'else:')
                    result.extend(self.statements(node.orelse, indent + 1))
            elif isinstance(node, ast.Return):
                value = node.value
                if self.kind == 'eligible':
                    if self.value_kind(value) != 'number':self.fail('eligibility result')
                    expression = self.expression(value)
                elif isinstance(value, ast.Constant) and value.value is None:
                    expression = '(0, 0, 0, 0, 0)' if self.kind == 'snapshot' else 'False'
                elif self.kind == 'snapshot' and isinstance(value, ast.List) and len(value.elts) == 10:
                    expected = ['cap','ev','ebitda',None,None,'ret','status']
                    for offset, name in enumerate(expected, 3):
                        if name is not None and self.dump(value.elts[offset]) != self.dump(ast.Name(name, ast.Load())):
                            self.fail('snapshot encoding field')
                    for offset, name in ((6,'yield_value'),(7,'multiple')):
                        self.numeric_dependencies(value.elts[offset])
                        if self.policy._lower(value.elts[offset]) != self.policy.expression_map[name]:self.fail('snapshot pair')
                    expression = '(1, ' + ', '.join(self.expression(value.elts[index]) for index in (0,1,2,9)) + ')'
                elif self.kind in ('current', 'three') and isinstance(value, ast.Tuple) and len(value.elts) == 2:
                    if self.kind == 'current':
                        expected = [self.numeric('multiple'), self.numeric('yield_value')]
                        if [self.expression(item) for item in value.elts] != expected:self.fail('current pair encoding')
                    else:
                        if self.dump(value.elts[0]) != self.dump(ast.Name('multiple', ast.Load())):self.fail('three-year pair encoding')
                        if self.policy._lower(value.elts[1], names={'multiple':('var','metric3_multiple')}) != self.policy.expression_map['metric3_yield']:self.fail('three-year pair yield')
                    expression = 'True'
                else:self.fail('return ' + self.dump(value))
                result.append(prefix + 'return ' + expression)
            else:
                self.fail('statement ' + self.dump(node))
        return result
