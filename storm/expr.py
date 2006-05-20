from copy import copy
import sys


# --------------------------------------------------------------------
# Basic compiler infrastructure

class CompileError(Exception):
    pass

class Compile(object):
    """Compiler based on the concept of generic functions."""

    def __init__(self):
        self._dispatch_table = {}
        self._precedence = {}

    def copy(self):
        copy = self.__class__()
        copy._dispatch_table = self._dispatch_table.copy()
        copy._precedence = self._precedence.copy()
        return copy

    def when(self, *types):
        def decorator(method):
            for type in types:
                self._dispatch_table[type] = method
            return method
        return decorator

    def get_precedence(self, type):
        return self._precedence.get(type, MAX_PRECEDENCE)

    def set_precedence(self, precedence, *types):
        for type in types:
            self._precedence[type] = precedence

    def _compile_single(self, state, expr, outer_precedence):
        cls = expr.__class__
        for class_ in cls.__mro__:
            handler = self._dispatch_table.get(class_)
            if handler is not None:
                inner_precedence = state.precedence = \
                                   self._precedence.get(cls, MAX_PRECEDENCE)
                statement = handler(self._compile, state, expr)
                if inner_precedence < outer_precedence:
                    statement = "(%s)" % statement
                return statement
        else:
            raise CompileError("Don't know how to compile %r"
                               % expr.__class__)

    def _compile(self, state, expr, join=", "):
        outer_precedence = state.precedence
        if type(expr) is str:
            return expr
        if type(expr) in (tuple, list):
            compiled = []
            for subexpr in expr:
                if type(subexpr) is str:
                    statement = subexpr
                elif type(subexpr) in (tuple, list):
                    state.precedence = outer_precedence
                    statement = self._compile(state, subexpr, join)
                else:
                    statement = self._compile_single(state, subexpr,
                                                     outer_precedence)
                compiled.append(statement)
            statement = join.join(compiled)
        else:
            statement = self._compile_single(state, expr, outer_precedence)
        state.precedence = outer_precedence
        return statement

    def __call__(self, expr):
        state = State()
        return self._compile(state, expr), state.parameters


Undef = object()

class State(object):

    def __init__(self):
        self._stack = []
        self.precedence = 0
        self.parameters = []
        self.auto_tables = []
        self.omit_column_tables = False

    def push(self, attr, new_value=Undef):
        old_value = getattr(self, attr, None)
        self._stack.append((attr, old_value))
        if new_value is Undef:
            new_value = copy(old_value)
        setattr(self, attr, new_value)

    def pop(self):
        setattr(self, *self._stack.pop(-1))


compile = Compile()


# --------------------------------------------------------------------
# Builtin type support

# Most common case. Optimized in Compile._compile.
#@compile.when(str)
#def compile_str(compile, state, expr):
#    return expr

@compile.when(type(None))
def compile_none(compile, state, expr):
    return "NULL"


# --------------------------------------------------------------------
# Base classes for expressions

MAX_PRECEDENCE = 1000

class Expr(object):
    pass

class Comparable(object):

    def __eq__(self, other):
        if not isinstance(other, Expr) and other is not None:
            other = Param(other)
        return Eq(self, other)

    def __ne__(self, other):
        if not isinstance(other, Expr) and other is not None:
            other = Param(other)
        return Ne(self, other)

    def __gt__(self, other):
        if not isinstance(other, Expr):
            other = Param(other)
        return Gt(self, other)

    def __ge__(self, other):
        if not isinstance(other, Expr):
            other = Param(other)
        return Ge(self, other)

    def __lt__(self, other):
        if not isinstance(other, Expr):
            other = Param(other)
        return Lt(self, other)

    def __le__(self, other):
        if not isinstance(other, Expr):
            other = Param(other)
        return Le(self, other)

    def __rshift__(self, other):
        if not isinstance(other, Expr):
            other = Param(other)
        return RShift(self, other)

    def __lshift__(self, other):
        if not isinstance(other, Expr):
            other = Param(other)
        return LShift(self, other)

    def __and__(self, other):
        if not isinstance(other, Expr):
            other = Param(other)
        return And(self, other)

    def __or__(self, other):
        if not isinstance(other, Expr):
            other = Param(other)
        return Or(self, other)

    def __add__(self, other):
        if not isinstance(other, Expr):
            other = Param(other)
        return Add(self, other)

    def __sub__(self, other):
        if not isinstance(other, Expr):
            other = Param(other)
        return Sub(self, other)

    def __mul__(self, other):
        if not isinstance(other, Expr):
            other = Param(other)
        return Mul(self, other)

    def __div__(self, other):
        if not isinstance(other, Expr):
            other = Param(other)
        return Div(self, other)
    
    def __mod__(self, other):
        if not isinstance(other, Expr):
            other = Param(other)
        return Mod(self, other)

class ComparableExpr(Expr, Comparable):
    pass

#class UnaryExpr(ComparableExpr):
#
#    def __init__(self, expr):
#        self.expr = expr

class BinaryExpr(ComparableExpr):

    def __init__(self, expr1, expr2):
        self.expr1 = expr1
        self.expr2 = expr2

class CompoundExpr(ComparableExpr):

    def __init__(self, *exprs):
        self.exprs = exprs


# --------------------------------------------------------------------
# Statement expressions

def has_tables(state, expr):
    return (expr.tables is not Undef or
            expr.default_tables is not Undef or
            state.auto_tables)

def build_tables(compile, state, expr):
    if expr.tables is not Undef:
        return compile(state, expr.tables)
    elif state.auto_tables:
        tables = []
        for expr in state.auto_tables:
            table = compile(state, expr)
            if table not in tables:
                tables.append(table)
        return ", ".join(tables)
    elif expr.default_tables is not Undef:
        return compile(state, expr.default_tables)
    raise CompileError("Couldn't find any tables")

def build_table(compile, state, expr):
    if expr.table is not Undef:
        return compile(state, expr.table)
    elif state.auto_tables:
        tables = []
        for expr in state.auto_tables:
            table = compile(state, expr)
            if table not in tables:
                tables.append(table)
        return ", ".join(tables)
    elif expr.default_table is not Undef:
        return compile(state, expr.default_table)
    raise CompileError("Couldn't find any table")


class Select(Expr):

    def __init__(self, columns, where=Undef, tables=Undef,
                 default_tables=Undef, order_by=Undef, group_by=Undef,
                 limit=Undef, offset=Undef, distinct=False):
        self.columns = columns
        self.where = where
        self.tables = tables
        self.default_tables = default_tables
        self.order_by = order_by
        self.group_by = group_by
        self.limit = limit
        self.offset = offset
        self.distinct = distinct

@compile.when(Select)
def compile_select(compile, state, select):
    state.push("auto_tables", [])
    tokens = ["SELECT "]
    if select.distinct:
        tokens.append("DISTINCT ")
    tokens.append(compile(state, select.columns))
    if has_tables(state, select):
        tokens.append(" FROM ")
        # Add a placeholder and compile later to support auto_tables.
        tables_pos = len(tokens)
        tokens.append(None)
    else:
        tables_pos = None
    if select.where is not Undef:
        tokens.append(" WHERE ")
        tokens.append(compile(state, select.where))
    if select.order_by is not Undef:
        tokens.append(" ORDER BY ")
        tokens.append(compile(state, select.order_by))
    if select.group_by is not Undef:
        tokens.append(" GROUP BY ")
        tokens.append(compile(state, select.group_by))
    if select.limit is not Undef:
        tokens.append(" LIMIT %d" % select.limit)
    if select.offset is not Undef:
        tokens.append(" OFFSET %d" % select.offset)
    if tables_pos is not None:
        tokens[tables_pos] = build_tables(compile, state, select)
    state.pop()
    return "".join(tokens)


class Insert(Expr):

    def __init__(self, columns, values, table=Undef, default_table=Undef):
        self.columns = columns
        self.values = values
        self.table = table
        self.default_table = default_table

@compile.when(Insert)
def compile_insert(compile, state, insert):
    state.push("omit_column_tables", True)
    columns = compile(state, insert.columns)
    state.pop()
    tokens = ["INSERT INTO ", build_table(compile, state, insert),
              " (", columns, ") VALUES (", compile(state, insert.values), ")"]
    return "".join(tokens)


class Update(Expr):

    def __init__(self, set, where=Undef, table=Undef, default_table=Undef):
        self.set = set
        self.where = where
        self.table = table
        self.default_table = default_table

@compile.when(Update)
def compile_update(compile, state, update):
    state.push("omit_column_tables", True)
    set = update.set
    sets = ["%s=%s" % (compile(state, col), compile(state, set[col]))
            for col in set]
    state.pop()
    tokens = ["UPDATE ", build_table(compile, state, update),
              " SET ", ", ".join(sets)]
    if update.where is not Undef:
        tokens.append(" WHERE ")
        tokens.append(compile(state, update.where))
    return "".join(tokens)


class Delete(Expr):

    def __init__(self, where=Undef, table=Undef, default_table=Undef):
        self.where = where
        self.table = table
        self.default_table = default_table

@compile.when(Delete)
def compile_delete(compile, state, delete):
    tokens = ["DELETE FROM ", None]
    if delete.where is not Undef:
        tokens.append(" WHERE ")
        tokens.append(compile(state, delete.where))
    # Compile later for auto_tables support.
    tokens[1] = build_table(compile, state, delete)
    return "".join(tokens)


# --------------------------------------------------------------------
# Columns and parameters

class Column(ComparableExpr):

    def __init__(self, name=Undef, table=Undef):
        self.name = name
        self.table = table

@compile.when(Column)
def compile_column(compile, state, column):
    if column.table is not Undef:
        state.auto_tables.append(column.table)
    if column.table is Undef or state.omit_column_tables:
        return column.name
    return "%s.%s" % (compile(state, column.table), column.name)


class Param(ComparableExpr):

    def __init__(self, value):
        self.value = value

@compile.when(Param)
def compile_param(compile, state, param):
    state.parameters.append(param.value)
    return "?"


# --------------------------------------------------------------------
# Operators

#class UnaryOper(UnaryExpr):
#    oper = " (unknown) "


class BinaryOper(BinaryExpr):
    oper = " (unknown) "

@compile.when(BinaryOper)
def compile_binary_oper(compile, state, oper):
    return "%s%s%s" % (compile(state, oper.expr1), oper.oper,
                       compile(state, oper.expr2))


class NonAssocBinaryOper(BinaryOper):
    oper = " (unknown) "

@compile.when(NonAssocBinaryOper)
def compile_non_assoc_binary_oper(compile, state, oper):
    expr1 = compile(state, oper.expr1)
    state.precedence += 0.5
    expr2 = compile(state, oper.expr2)
    return "%s%s%s" % (expr1, oper.oper, expr2)


class CompoundOper(CompoundExpr):
    oper = " (unknown) "

@compile.when(CompoundOper)
def compile_compound_oper(compile, state, oper):
    return "%s" % compile(state, oper.exprs, oper.oper)


class Eq(BinaryOper):
    oper = " = "

@compile.when(Eq)
def compile_eq(compile, state, eq):
    if eq.expr2 is None:
        return "%s IS NULL" % compile(state, eq.expr1)
    return "%s = %s" % (compile(state, eq.expr1), compile(state, eq.expr2))


class Ne(BinaryOper):
    oper = " != "

@compile.when(Ne)
def compile_ne(compile, state, ne):
    if ne.expr2 is None:
        return "%s IS NOT NULL" % compile(state, ne.expr1)
    return "%s != %s" % (compile(state, ne.expr1), compile(state, ne.expr2))


class Gt(BinaryOper):
    oper = " > "

class Ge(BinaryOper):
    oper = " >= "

class Lt(BinaryOper):
    oper = " < "

class Le(BinaryOper):
    oper = " <= "

class RShift(BinaryOper):
    oper = ">>"

class LShift(BinaryOper):
    oper = "<<"

class Like(BinaryOper):
    oper = " LIKE "


class In(BinaryOper):
    oper = " IN "

@compile.when(In)
def compile_in(compile, state, expr):
    expr1 = compile(state, expr.expr1)
    state.precedence = 0 # We're forcing parenthesis here.
    return "%s IN (%s)" % (expr1, compile(state, expr.expr2))


class And(CompoundOper):
    oper = " AND "

class Or(CompoundOper):
    oper = " OR "


class Add(CompoundOper):
    oper = "+"

class Sub(NonAssocBinaryOper):
    oper = "-"

class Mul(CompoundOper):
    oper = "*"

class Div(NonAssocBinaryOper):
    oper = "/"

class Mod(NonAssocBinaryOper):
    oper = "%"


# --------------------------------------------------------------------
# Functions

class Func(ComparableExpr):
    name = "(unknown)"

    def __init__(self, *args):
        self.args = args

@compile.when(Func)
def compile_func(compile, state, func):
    return "%s(%s)" % (func.name, compile(state, func.args))


class Count(Func):
    name = "COUNT"

@compile.when(Count)
def compile_count(compile, state, count):
    if count.args:
        return "COUNT(%s)" % compile(state, count.args)
    return "COUNT(*)"


class Max(Func):
    name = "MAX"

class Min(Func):
    name = "MIN"

class Avg(Func):
    name = "AVG"

class Sum(Func):
    name = "SUM"


# --------------------------------------------------------------------
# Suffix expressions

class SuffixExpr(Expr):
    suffix = "(unknown)"

    def __init__(self, expr):
        self.expr = expr

@compile.when(SuffixExpr)
def compile_suffix_expr(compile, state, expr):
    return "%s %s" % (compile(state, expr.expr), expr.suffix)


class Asc(SuffixExpr):
    suffix = "ASC"

class Desc(SuffixExpr):
    suffix = "DESC"


# --------------------------------------------------------------------
# Set operator precedences and commutativity.

compile.set_precedence(10, Select, Insert, Update, Delete)
compile.set_precedence(20, Or)
compile.set_precedence(30, And)
compile.set_precedence(40, Eq, Ne, Gt, Ge, Lt, Le, Like, In)
compile.set_precedence(50, LShift, RShift)
compile.set_precedence(60, Add, Sub)
compile.set_precedence(70, Mul, Div, Mod)

