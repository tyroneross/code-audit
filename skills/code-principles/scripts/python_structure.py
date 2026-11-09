"""Structural signals and pattern leads for Python, matching runtime/complexity for the other languages.

Signals describe one function body; nested functions, classes and lambdas are measured separately or skipped, as in
the CC count. Pattern leads compare expressions as unparsed source and are reported only when no operand calls a
function, awaits, yields or binds a name, so evaluating it twice cannot differ. See measurement.md for definitions.
"""
import ast

NESTS = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler, ast.Match, ast.IfExp)
SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
# Where a new statement, block or argument list starts, so a combined condition ends.
CONDITION_BOUNDARIES = (ast.stmt, ast.ExceptHandler, ast.match_case, ast.Call)
IMPURE = (ast.Call, ast.Await, ast.Yield, ast.YieldFrom, ast.NamedExpr, ast.Lambda)
COMPARISONS = {ast.Eq: "==", ast.NotEq: "!=", ast.Lt: "<", ast.Gt: ">", ast.LtE: "<=", ast.GtE: ">=", ast.Is: "is", ast.IsNot: "is not"}
ARITHMETIC = {ast.Sub: "-", ast.Div: "/", ast.FloorDiv: "//", ast.Mod: "%"}  # & | ^ are set operations here
FLOAT_WORDS = ("nan", "float", "inf")  # a line naming these makes `x != x` the usual NaN test
NAN_NOTE = "; a deliberate NaN test is the one valid use"
SAME_BRANCHES = "both branches are the same code"


def continues_elif(parent, child):
    """True when child is the `elif` of parent: the only statement in its else, written at the same column."""
    return (isinstance(parent, ast.If) and isinstance(child, ast.If) and len(parent.orelse) == 1
            and parent.orelse[0] is child and child.col_offset == parent.col_offset)


class Shape:
    """max_nesting, bumps and condition_operators of one function body."""

    def __init__(self, body):
        self.max_nesting = self.bumps = self.condition_operators = self.chunk_depth = 0
        for statement in body:
            self.walk(statement, 0, None, False)

    def walk(self, node, depth, combined, chained):
        if isinstance(node, SCOPES):
            return
        nests = isinstance(node, NESTS) and not chained
        if nests or isinstance(node, CONDITION_BOUNDARIES):
            combined = None
        if isinstance(node, ast.BoolOp):
            combined = combined if combined is not None else [0]
            combined[0] += len(node.values) - 1
            self.condition_operators = max(self.condition_operators, combined[0])
        if nests:
            depth += 1
            self.max_nesting = max(self.max_nesting, depth)
            self.chunk_depth = 1 if depth == 1 else max(self.chunk_depth, depth)
        for child in ast.iter_child_nodes(node):
            self.walk(child, depth, combined, continues_elif(node, child))
        if nests and depth == 1 and self.chunk_depth >= 2:
            self.bumps += 1


def param_count(arguments, method):
    """Declared parameters; a method's leading self or cls is the receiver and is not counted."""
    positional = [a.arg for a in [*arguments.posonlyargs, *arguments.args]]
    receiver = method and positional[:1] in (["self"], ["cls"])
    return len(positional) - receiver + len(arguments.kwonlyargs) + (arguments.vararg is not None) + (arguments.kwarg is not None)


def pure(node):
    return not any(isinstance(n, IMPURE) for n in ast.walk(node))


def same(first, second):
    return pure(first) and pure(second) and ast.unparse(first) == ast.unparse(second)


def comparison_lead(node, source_lines):
    """`a == a` and the other single comparisons whose two sides are the same pure expression."""
    if not (isinstance(node, ast.Compare) and len(node.ops) == 1 and type(node.ops[0]) in COMPARISONS and same(node.left, node.comparators[0])):
        return None
    op = COMPARISONS[type(node.ops[0])]
    equality = op in ("==", "!=")
    line = source_lines[node.lineno - 1].lower() if node.lineno <= len(source_lines) else ""
    if equality and any(word in line for word in FLOAT_WORDS):
        return None
    return "identical_operands", f"both sides of `{op}` are `{ast.unparse(node.left)}`" + (NAN_NOTE if equality else "")


def arithmetic_lead(node):
    if isinstance(node, ast.BinOp) and type(node.op) in ARITHMETIC and same(node.left, node.right):
        return "identical_operands", f"both sides of `{ARITHMETIC[type(node.op)]}` are `{ast.unparse(node.left)}`"
    return None


def boolean_lead(node):
    """`a and a`: a pure operand that repeats inside one and/or."""
    if not isinstance(node, ast.BoolOp):
        return None
    texts = [ast.unparse(value) for value in node.values if pure(value)]
    repeated = next((text for index, text in enumerate(texts) if text in texts[:index]), None)
    if repeated is None:
        return None
    return "identical_operands", f"both sides of `{'and' if isinstance(node.op, ast.And) else 'or'}` are `{repeated}`"


def assignment_lead(node, in_function):
    # Outside a function `NAME = NAME` rebinds an imported or enclosing name on purpose.
    if isinstance(node, ast.Assign) and in_function and len(node.targets) == 1 and same(node.targets[0], node.value):
        return "self_assignment", f"`{ast.unparse(node.value)}` is assigned to itself"
    return None


def conditional_expression_lead(node):
    if isinstance(node, ast.IfExp) and ast.dump(node.body) == ast.dump(node.orelse):
        return "duplicate_branches", SAME_BRANCHES
    return None


def elif_of(node):
    """The `elif` that continues this `if`, or None."""
    return node.orelse[0] if len(node.orelse) == 1 and continues_elif(node, node.orelse[0]) else None


def duplicate_if_lead(node):
    """An if/else (not an elif chain, not `pass`) whose two bodies are the same statements."""
    if not node.orelse or elif_of(node) is not None or all(isinstance(statement, ast.Pass) for statement in node.body):
        return None
    if [ast.dump(statement) for statement in node.body] != [ast.dump(statement) for statement in node.orelse]:
        return None
    return "duplicate_branches", node.lineno, SAME_BRANCHES


def repeated_condition_leads(head):
    """Conditions in the chain starting at head that repeat an earlier pure condition."""
    seen, leads, link = [], [], head
    while link is not None:
        if pure(link.test):
            text = ast.unparse(link.test)
            if text in seen:
                leads.append(("repeated_condition", link.lineno, "this condition repeats an earlier one in the same else-if chain"))
            seen.append(text)
        link = elif_of(link)
    return leads


def patterns(tree, source_lines):
    """[(rule, line, detail)] for the whole module, in source order."""
    found = []

    def visit(node, parent, in_function):
        expression_leads = (comparison_lead(node, source_lines), arithmetic_lead(node), boolean_lead(node),
                            assignment_lead(node, in_function), conditional_expression_lead(node))
        found.extend((rule, node.lineno, detail) for rule, detail in filter(None, expression_leads))
        if isinstance(node, ast.If):
            found.extend(filter(None, [duplicate_if_lead(node)]))
            if not continues_elif(parent, node):
                found.extend(repeated_condition_leads(node))
        inside = (in_function or isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda))) and not isinstance(node, ast.ClassDef)
        for child in ast.iter_child_nodes(node):
            visit(child, node, inside)

    visit(tree, None, False)
    return sorted(found, key=lambda lead: (lead[1], lead[0]))
