"""Typed formulas are a text view of the stored expression tree. Unchanged text
keeps the stored formula; changed text is read in the current form. Text never
reaches storage; only the tree is stored and hashed. Growth/CAGR text counts
years; the tree counts yearly values (years + 1).

+ and - bind looser than * and /; all four are left-associative and unary minus
binds tightest. A sign belongs to a number only when it is attached to the
digits where a value starts. Where a name can start, the longest whole known
name wins, whatever characters it holds: P/E * 2 is P/E times 2. Otherwise a
word directly followed by "(" is a function; positive( ) is only a divisor.
Brackets are optional, [P/E] with ]] for ], and needed only for a name that
does not start with a letter. Names match ignoring case and repeated spaces.
"""
import difflib
import re

from backtest.application import vocabulary

FUNCTIONS = (
    dict(name='average', text='average(', hint='Average of yearly values: average(Revenue, 3 years)'),
    dict(name='min', text='min(', hint='Lowest yearly value: min(Revenue, 3 years)'),
    dict(name='max', text='max(', hint='Highest yearly value: max(Revenue, 3 years)'),
    dict(name='growth', text='growth(', hint='Change across years: growth(Revenue, 3 years)'),
    dict(name='cagr', text='cagr(', hint='Yearly growth rate across years: cagr(Revenue, 3 years)'),
    dict(name='ago', text='ago(', hint='Value some months earlier: ago(Revenue, 12 months)'),
    dict(name='at', text='at(', hint='Value on one date: at(Revenue, 2024-12-31)'),
    dict(name='positive', text='positive(', hint='Divide only by a value above zero: Total debt / positive(Shareholders equity)'),
)
_STATS = {'average': 'mean', 'min': 'min', 'max': 'max', 'growth': 'growth', 'cagr': 'cagr'}
_WORDS = {stat: word for word, stat in _STATS.items()}
_HINTS = {'mean': 'average of', 'min': 'lowest of', 'max': 'highest of',
          'growth': 'change across', 'cagr': 'yearly growth rate across'}
_UNITS = {'USD': 'USD', 'USD/share': 'USD per share', 'share': 'shares'}
_UNIT_NAMES = {word.casefold(): unit for unit, word in _UNITS.items()}
_PRECEDENCE = {'add': 1, 'sub': 1, 'mul': 2, 'div': 2, 'positive_div': 2}
# A negated sum, product or number is printed in parentheses: -(5).
_NEGATED_IN_PARENS = {*_PRECEDENCE, 'constant'}
_SYMBOLS = {'add': '+', 'sub': '-', 'mul': '*', 'div': '/', 'positive_div': '/'}
_BARE = re.compile(r"[^\W\d_][\w '.&]*")
_NUMBER = re.compile(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?')
_UNIT_WORD = re.compile(r" *(usd +per +share|usd|shares)(?![\w'.&])", re.I)
_PERIOD = re.compile(r"([0-9]+) *(years?|months?)(?![\w'.&])", re.I)
_DATE = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}(?![\w-])')


class TextError(ValueError):
    """Formula errors as [{start?, end?, code, message, suggestions:[{text, label}]}].

    Reader codes are SYNTAX, UNKNOWN_NAME, STEP_ONLY and BAD_ARGUMENT, with
    [start, end) offsets into the text.
    """
    def __init__(self, errors):
        self.errors = errors
        super().__init__(errors[0]['message'])


def _fail(code, start, end, message, suggestions=()):
    raise TextError([dict(start=start, end=end, code=code, message=message, suggestions=list(suggestions))])


def _key(name):
    return ' '.join(name.split()).casefold()


def spelling(name):
    """How a name is typed in a formula: bare when it starts with a letter, else in brackets."""
    return name if _BARE.match(name) else '[' + name.replace(']', ']]') + ']'


def _namer(names):
    named = vocabulary.names()
    labelled = {(item['variable_id'], item['revision']): item['name'] for item in names}
    def name(node):
        if node['op'] == 'ref':
            return named.get(node['variable_id']) or labelled[node['variable_id'], node['revision']]
        return named[node['id'] if node['op'] == 'parameter' else node['parameter']]
    return name


def _count(number, word):
    return str(number) + ' ' + word + ('' if number == 1 else 's')


def _years(node):
    return node['count'] - (1 if node['stat'] in ('growth', 'cagr') else 0)


def _grouped(child, op, side):
    precedence = _PRECEDENCE.get(child['op'], 3)
    return precedence < _PRECEDENCE[op] if side == 'left' else precedence <= _PRECEDENCE[op]


def _write(node, name):
    op = node['op']
    if op in ('parameter', 'ref'):
        return spelling(name(node))
    if op == 'constant':
        return node['value'] + (' ' + _UNITS[node['unit']] if node['unit'] in _UNITS else '')
    if op == 'neg':
        inner = _write(node['arg'], name)
        return '-(' + inner + ')' if node['arg']['op'] in _NEGATED_IN_PARENS else '-' + inner
    if op == 'annual':
        return _WORDS[node['stat']] + '(' + spelling(name(node)) + ', ' + _count(_years(node), 'year') + ')'
    if op == 'lookback':
        return 'ago(' + _write(node['arg'], name) + ', ' + _count(node['months'], 'month') + ')'
    if op == 'at':
        return 'at(' + _write(node['arg'], name) + ', ' + node['date'] + ')'
    left, right = _write(node['left'], name), _write(node['right'], name)
    left = '(' + left + ')' if _grouped(node['left'], op, 'left') else left
    right = ('positive(' + right + ')' if op == 'positive_div' else
             '(' + right + ')' if _grouped(node['right'], op, 'right') else right)
    return left + ' ' + _SYMBOLS[op] + ' ' + right


def to_text(definition, names):
    """Print any stored definition's expression (catalogs /1-/4, every operation).

    A parameter or built-in measure prints its vocabulary name. names
    [{variable_id, revision, name}], such as a capture presentation, name
    every other reference.
    """
    return _write(definition['expression'], _namer(names))


def picture(definition, names):
    """Lay out a definition's expression for drawing; names as for to_text.

    The layout tree is {name}, {number, unit}, {op: '+'|'-'|'*', left, right},
    {op: '/', top, bottom, positive}, {op: 'neg', arg} and {fn, args, hint},
    each with optional parens.
    """
    return _picture(definition['expression'], _namer(names))


def _picture(node, name, parens=False):
    op = node['op']
    if op in ('parameter', 'ref'):
        result = dict(name=name(node))
    elif op == 'constant':
        result = dict(number=node['value'], unit=_UNITS.get(node['unit']))
    elif op == 'neg':
        result = dict(op='neg', arg=_picture(node['arg'], name, node['arg']['op'] in _NEGATED_IN_PARENS))
    elif op == 'annual':
        years = _years(node)
        hint = _HINTS[node['stat']] + ' ' + (_count(years, 'yearly value') if node['stat'] in ('mean', 'min', 'max')
                                             else _count(years, 'year') + ' (' + _count(node['count'], 'yearly value') + ')')
        result = dict(fn=_WORDS[node['stat']], args=[dict(name=name(node)), dict(number=str(years), unit='year' + 's' * (years != 1))],
                      hint=hint)
    elif op == 'lookback':
        result = dict(fn='ago', args=[_picture(node['arg'], name), dict(number=str(node['months']), unit='month' + 's' * (node['months'] != 1))],
                      hint='value ' + _count(node['months'], 'month') + ' earlier')
    elif op == 'at':
        result = dict(fn='at', args=[_picture(node['arg'], name), dict(number=node['date'], unit=None)],
                      hint='value on ' + node['date'])
    elif op in ('div', 'positive_div'):
        result = dict(op='/', top=_picture(node['left'], name), bottom=_picture(node['right'], name),
                      positive=op == 'positive_div')
    else:
        result = dict(op=_SYMBOLS[op], left=_picture(node['left'], name, _grouped(node['left'], op, 'left')),
                      right=_picture(node['right'], name, _grouped(node['right'], op, 'right')))
    if parens:
        result['parens'] = True
    return result


class _Reader:
    def __init__(self, text, known, usable, names):
        self.text, self.at, self.known, self.usable, self.names = text, 0, known, usable, names

    def peek(self):
        while self.at < len(self.text) and self.text[self.at].isspace():
            self.at += 1
        return self.text[self.at:self.at + 1]

    def sum(self):
        node = self.product()
        while self.peek() in ('+', '-'):
            op = 'add' if self.text[self.at] == '+' else 'sub'
            self.at += 1
            node = dict(op=op, left=node, right=self.product())
        return node

    def product(self):
        node = self.unary()
        while self.peek() in ('*', '/'):
            symbol = self.text[self.at]
            self.at += 1
            right = self.unary(divisor=symbol == '/')
            if right['op'] == 'positive':
                node = dict(op='positive_div', left=node, right=right['arg'])
            else:
                node = dict(op='mul' if symbol == '*' else 'div', left=node, right=right)
        return node

    def unary(self, divisor=False):
        if self.peek() == '-' and not _NUMBER.match(self.text, self.at):
            self.at += 1
            return dict(op='neg', arg=self.unary())
        return self.primary(divisor)

    def primary(self, divisor):
        char = self.peek()
        start = self.at
        number = _NUMBER.match(self.text, start)
        if number:
            self.at, unit = number.end(), 'scalar'
            word = _UNIT_WORD.match(self.text, self.at)
            if word:
                self.at, unit = word.end(), _UNIT_NAMES[' '.join(word.group(1).split()).casefold()]
            return dict(op='constant', value=number.group(), unit=unit)
        if char == '(':
            self.at += 1
            node = self.sum()
            self.close(start)
            return node
        if char == '[':
            name = self.bracketed()
            return self.resolve(name, start, self.at)
        whole = self.names.match(self.text, start)
        if whole:
            self.at = whole.end()
            return self.resolve(whole.group(), start, self.at)
        bare = _BARE.match(self.text, start)
        if bare:
            word = bare.group().rstrip()
            self.at = start + len(word)
            if word == bare.group() and self.text.startswith('(', self.at):
                return self.call(word, start, divisor)
            return self.resolve(word, start, self.at)
        if not char:
            _fail('SYNTAX', start, start, 'A value is missing at the end.')
        _fail('SYNTAX', start, start + 1, 'A value is missing before “' + char + '”.' if char in ')+*/,'
              else '“' + char + '” cannot start a value.')

    def close(self, opening):
        if self.peek() != ')':
            _fail('SYNTAX', opening, opening + 1, 'This ( has no matching ).')
        self.at += 1

    def bracketed(self):
        start, parts, at = self.at, [], self.at + 1
        while True:
            end = self.text.find(']', at)
            if end < 0:
                _fail('SYNTAX', start, len(self.text), 'This [ has no matching ].')
            parts.append(self.text[at:end])
            if not self.text.startswith(']]', end):
                break
            parts.append(']')
            at = end + 2
        self.at = end + 1
        if not ''.join(parts).strip():
            _fail('SYNTAX', start, self.at, 'Put a name between [ and ].')
        return ''.join(parts)

    def suggest(self, key, choices, suffix=''):
        return [dict(text=spelling(choices[match]) + suffix, label=choices[match])
                for match in difflib.get_close_matches(key, list(choices), n=3)]

    def resolve(self, name, start, end):
        key = _key(name)
        if key not in self.known:
            _fail('UNKNOWN_NAME', start, end, '“' + name + '” is not an input or a saved variable.',
                  self.suggest(key, self.usable))
        label, node = self.known[key]
        if node is None:
            _fail('STEP_ONLY', start, end, label + ' can be a step on its own, not part of a formula.')
        return dict(node)

    def call(self, word, start, divisor):
        function, opening = word.casefold(), self.at
        if function not in _FUNCTION_NAMES:
            _fail('UNKNOWN_NAME', start, opening, 'There is no function called “' + word + '”.',
                  self.suggest(function, _FUNCTION_NAMES, '('))
        self.at += 1
        if function == 'positive':
            if not divisor:
                _fail('BAD_ARGUMENT', start, opening, 'positive( ) can only be the bottom of a division, '
                      'as in Total debt / positive(Shareholders equity).')
            node = self.sum()
            self.close(opening)
            return dict(op='positive', arg=node)
        self.peek()
        first = self.at
        node = self.sum()
        if function in _STATS and node['op'] != 'parameter':
            _fail('BAD_ARGUMENT', first, self.at, function + ' works on one yearly input, such as Revenue.')
        if function == 'at':
            date = self.argument(_DATE, 'Give a date as year-month-day, as in at(Revenue, 2024-12-31).')
            node = dict(op='at', date=date.group(), arg=node)
        elif function == 'ago':
            period = self.argument(_PERIOD, 'Give a number of months, as in ago(Revenue, 12 months).', 'month')
            node = dict(op='lookback', months=int(period.group(1)), arg=node)
        else:
            period = self.argument(_PERIOD, 'Give a number of years, as in ' + function + '(Revenue, 3 years).', 'year')
            stat = _STATS[function]
            node = dict(op='annual', stat=stat, count=int(period.group(1)) + (stat in ('growth', 'cagr')),
                        parameter=node['id'])
        self.close(opening)
        return node

    def argument(self, pattern, message, unit=None):
        start = self.at
        if self.peek() == ',':
            self.at += 1
            self.peek()
            found = pattern.match(self.text, self.at)
            if found and (unit is None or found.group(2).casefold().rstrip('s') == unit):
                self.at = found.end()
                return found
        stop = self.text.find(')', start)
        _fail('BAD_ARGUMENT', start, len(self.text) if stop < 0 else stop, message)


_FUNCTION_NAMES = {item['name']: item['name'] for item in FUNCTIONS}


def from_text(text, library):
    """Read text in the current form into (expression, picture), or raise TextError.

    library holds the active saved entries [{variable_id, revision, name}].
    Vocabulary names come first; when two saved variables share a name, the
    later (newest) wins. A vocabulary entry without a term is a step only.
    Terms use catalog /4; a saved variable reference names its current
    revision. The picture is as picture() draws it. Error offsets count
    characters of the text as typed; they equal JavaScript string offsets for
    every character the names use.
    """
    known = {}
    for item in library:
        known[_key(item['name'])] = item['name'], dict(op='ref', variable_id=item['variable_id'], revision=item['revision'])
    for item in vocabulary.entries():
        known[_key(item['name'])] = item['name'], item['term']
    usable = {key: name for key, (name, term) in known.items() if term is not None}
    # Longest first, so a regular expression alternation finds the longest whole name.
    names = re.compile('(?:' + '|'.join(r'\s+'.join(map(re.escape, known[key][0].split()))
                                        for key in sorted(known, key=len, reverse=True)) + r')(?![\w(])', re.I)
    if not text.strip():
        _fail('SYNTAX', 0, len(text), 'Type a formula.')
    reader = _Reader(text, known, usable, names)
    expression = reader.sum()
    if reader.peek():
        char = reader.text[reader.at]
        _fail('SYNTAX', reader.at, reader.at + 1, 'This ) has no matching (.' if char == ')'
              else 'Put +, -, * or / between two values.')
    return expression, _picture(expression, _namer(library))
