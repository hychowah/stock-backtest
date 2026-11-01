"""Rust lowering of the shared arithmetic IR and validated candidate trees."""
import ast
import math
from pathlib import Path

from numerical_candidates import SNAPSHOT, PAIRS, VERSION

RESOURCE = Path(__file__).with_name('numerical_rust_kernel.rs')
ABI = 1


def literal(value):
    value=float(value)
    if math.isnan(value):return 'f64::NAN'
    if math.isinf(value):return 'f64::INFINITY' if value>0 else 'f64::NEG_INFINITY'
    return repr(value)+'_f64'


def factors(policy):
    derived={}
    def lower(node):
        op=node[0]
        if op=='input' and len(node)==2:return 'input['+str(policy.input_index[node[1]])+']'
        if op=='const' and len(node)==2:return literal(node[1])
        if op=='var' and len(node)==2:
            if node[1] not in derived:raise ValueError('Unordered Rust policy dependency.')
            return derived[node[1]]
        if op=='neg' and len(node)==2:return '(-'+lower(node[1])+')'
        if op in ('add','sub','mul','div') and len(node)==3:
            return '('+lower(node[1])+dict(add='+',sub='-',mul='*',div='/')[op]+lower(node[2])+')'
        if op=='if' and len(node)==4:return '(if '+lower(node[1])+' != 0.0 {'+lower(node[2])+'} else {'+lower(node[3])+'})'
        raise ValueError('Unsupported shared Rust arithmetic: '+str(op))
    lines=[]
    for name,expression in policy.expressions:
        if name in derived:raise ValueError('Duplicate Rust policy output.')
        variable='v'+str(len(derived));lines.append('let '+variable+':f64='+lower(expression)+';');derived[name]=variable
    lines.extend('output['+str(index)+']='+derived[name]+';' for index,name in enumerate(policy.output_names))
    return '\n'.join(lines)


class DecisionLowering:
    """Consume only CandidateDecisionProgram's already validated lowered AST.

    Ordinals, years and enum tags are exactly representable as float64. The
    extractor has already rejected mixed date/string/numeric comparisons.
    Boolean values retain Boolean types and short-circuit operations.
    """
    def __init__(self, program):self.program=program

    def kind(self,node):
        if isinstance(node,ast.Constant) and isinstance(node.value,bool):return 'bool'
        if isinstance(node,ast.Name) and node.id.endswith('_valid'):return 'bool'
        if isinstance(node,(ast.Compare,ast.BoolOp)):return 'bool'
        if isinstance(node,ast.UnaryOp) and isinstance(node.op,ast.Not):return 'bool'
        return 'number'

    def truth(self,node):
        value=self.expr(node)
        return value if self.kind(node)=='bool' else '('+value+' != 0.0)'

    def expr(self,node):
        if isinstance(node,ast.Constant):
            if isinstance(node.value,bool):return str(node.value).lower()
            if type(node.value) in (int,float):return literal(node.value)
        if isinstance(node,ast.Name):return node.id
        if isinstance(node,ast.Subscript) and isinstance(node.value,ast.Name) and isinstance(node.slice,ast.Constant):
            return '('+node.value.id+'['+str(node.slice.value)+'] as f64)'
        if isinstance(node,ast.BoolOp):
            return '('+(' && ' if isinstance(node.op,ast.And) else ' || ').join(self.truth(v) for v in node.values)+')'
        if isinstance(node,ast.Compare):
            operators={ast.Lt:'<',ast.LtE:'<=',ast.Gt:'>',ast.GtE:'>=',ast.Eq:'==',ast.NotEq:'!='}
            parts=[node.left,*node.comparators]
            return '('+' && '.join('('+self.expr(a)+' '+operators[type(op)]+' '+self.expr(b)+')'
                for a,op,b in zip(parts,node.ops,parts[1:]))+')'
        if isinstance(node,ast.UnaryOp):
            if isinstance(node.op,ast.Not):return '(!'+self.truth(node.operand)+')'
            return self.expr(node.operand) if isinstance(node.op,ast.UAdd) else '(-'+self.expr(node.operand)+')'
        if isinstance(node,ast.BinOp):
            return '('+self.expr(node.left)+{ast.Add:'+',ast.Sub:'-',ast.Mult:'*',ast.Div:'/'}[type(node.op)]+self.expr(node.right)+')'
        if isinstance(node,ast.IfExp):return '(if '+self.truth(node.test)+' {'+self.expr(node.body)+'} else {'+self.expr(node.orelse)+'})'
        if (isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id=='abs'
                and len(node.args)==1 and not node.keywords):return '('+self.expr(node.args[0])+').abs()'
        if isinstance(node,ast.Tuple):return '['+','.join(self.expr(v) for v in node.elts)+']'
        raise ValueError('Unsupported validated Rust decision expression: '+ast.dump(node,include_attributes=False))

    def statements(self,nodes,level=1,declared=None):
        declared=set() if declared is None else declared
        result=[];prefix='    '*level
        for node in nodes:
            if isinstance(node,ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name):
                name=node.targets[0].id
                lead='' if name in declared else 'let mut '
                declared.add(name);result.append(prefix+lead+name+'='+self.expr(node.value)+';')
            elif isinstance(node,ast.If):
                result.append(prefix+'if '+self.truth(node.test)+' {')
                result.extend(self.statements(node.body,level+1,set(declared)));result.append(prefix+'}')
                if node.orelse:
                    result[-1]+=' else {';result.extend(self.statements(node.orelse,level+1,set(declared)));result.append(prefix+'}')
            elif isinstance(node,ast.Return):
                result.append(prefix+'return '+self.expr(node.value)+';')
            else:raise ValueError('Unsupported validated Rust decision statement: '+ast.dump(node,include_attributes=False))
        return result

    def source(self):
        signatures=dict(snapshot='days:&[i32],prices:&[f64],numeric:&[f64],fiscal_day:f64,entry_day:f64,exit_day:f64,entry_year:f64,exit_year:f64,bankruptcy:f64',
            eligible='numeric:&[f64],pool:f64',current='numeric:&[f64],average:f64,average_valid:bool',three='numeric:&[f64],average:f64,average_valid:bool')
        return '\n'.join('fn decision_'+name+'('+signatures[name]+')->'+('[f64;5]' if name=='snapshot' else 'bool')+' {\n'+
            '\n'.join(self.statements(tree.body))+'\n}' for name,tree in self.program.trees.items())


def source(policy):
    value_columns=[policy.output_index[name] for name in SNAPSHOT+PAIRS+tuple('filter_'+f for f in policy.filter_order)]
    bindings=dict(ABI=ABI,LAYOUT=VERSION,NINPUTS=len(policy.input_names),NOUTPUTS=len(policy.output_names),
        NFIELDS=len(policy.filter_order),AVERAGE=policy.input_index['average_3y'],BANKRUPTCY=policy.input_index['bankruptcy'],
        COLUMNS=','.join(map(str,value_columns)),FACTORS=factors(policy),DECISIONS=DecisionLowering(policy.decisions).source())
    result=RESOURCE.read_text(encoding='utf-8')
    for name,value in bindings.items():result=result.replace('__'+name+'__',str(value))
    if '__' in result:raise ValueError('Unresolved Rust source template binding.')
    return result
