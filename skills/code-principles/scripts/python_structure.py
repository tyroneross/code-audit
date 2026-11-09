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


def patterns(tree, source_lines):
    """[(rule, line, detail)] for the whole module, in source order."""
    found = []

    def visit(node, parent, in_function):
        if isinstance(node, ast.Compare) and len(node.ops) == 1 and type(node.ops[0]) in COMPARISONS and same(node.left, node.comparators[0]):
            op = COMPARISONS[type(node.ops[0])]
            equality = op in ("==", "!=")
            line = source_lines[node.lineno - 1].lower() if node.lineno <= len(source_lines) else ""
            if not (equality and any(word in line for word in FLOAT_WORDS)):
                note = "; a deliberate NaN test is the one valid use" if equality else ""
                found.append(("identical_operands", node.lineno, f"both sides of `{op}` are `{ast.unparse(node.left)}`{note}"))
        elif isinstance(node, ast.BinOp) and type(node.op) in ARITHMETIC and same(node.left, node.right):
            found.append(("identical_operands", node.lineno, f"both sides of `{ARITHMETIC[type(node.op)]}` are `{ast.unparse(node.left)}`"))
        elif isinstance(node, ast.BoolOp):
            texts = [ast.unparse(v) for v in node.values if pure(v)]
            repeated = next((t for i, t in enumerate(texts) if t in texts[:i]), None)
            if repeated is not None:
                op = "and" if isinstance(node.op, ast.And) else "or"
                found.append(("identical_operands", node.lineno, f"both sides of `{op}` are `{repeated}`"))
        elif isinstance(node, ast.Assign) and in_function and len(node.targets) == 1 and same(node.targets[0], node.value):
            # Outside a function `NAME = NAME` rebinds an imported or enclosing name on purpose.
            found.append(("self_assignment", node.lineno, f"`{ast.unparse(node.value)}` is assigned to itself"))
        elif isinstance(node, ast.IfExp) and ast.dump(node.body) == ast.dump(node.orelse):
            found.append(("duplicate_branches", node.lineno, "both branches are the same code"))
        if isinstance(node, ast.If):
            chained_else = len(node.orelse) == 1 and continues_elif(node, node.orelse[0])
            trivial = all(isinstance(s, ast.Pass) for s in node.body)
            if node.orelse and not chained_else and not trivial and [ast.dump(s) for s in node.body] == [ast.dump(s) for s in node.orelse]:
                found.append(("duplicate_branches", node.lineno, "both branches are the same code"))
            if not continues_elif(parent, node):
                seen, link = [], node
                while link is not None:
                    if pure(link.test):
                        text = ast.unparse(link.test)
                        if text in seen:
                            found.append(("repeated_condition", link.lineno, "this condition repeats an earlier one in the same else-if chain"))
                        seen.append(text)
                    link = link.orelse[0] if len(link.orelse) == 1 and continues_elif(link, link.orelse[0]) else None
        inside = in_function or isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda))
        for child in ast.iter_child_nodes(node):
            visit(child, node, inside and not isinstance(node, ast.ClassDef))

    visit(tree, None, False)
    return sorted(found, key=lambda f: (f[1], f[0]))
