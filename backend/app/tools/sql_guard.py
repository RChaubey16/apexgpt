"""Validation of LLM-written SQL for the stats tool (F3.5).

The SQL is parsed with Postgres's own parser (pglast / libpg_query, Postgres 18
grammar), then the whole tree is checked against allowlists:

- exactly one statement, a SELECT (UNION/INTERSECT/EXCEPT and WITH allowed);
- every node is of a known-safe type: anything else is rejected, including
  INTO (creates a table), FOR UPDATE/SHARE, data-modifying CTEs, parameters
  ($1), functions in FROM and table samples;
- every table is one of the stats views (or a CTE defined in the query);
- every function, cast type and SQL value function is on an allowlist, which
  keeps out set_config, pg_sleep, query_to_xml, file readers and catalog casts
  such as ::regclass.

The query that runs is then *regenerated from the validated tree* (deparsed),
with its row limit set in the tree, so what executes is exactly what was
checked. The read-only role and transaction settings are the second line of
defence, not the first (docs/PROGRESS.md, F1.5 Known Issue).

Messages are written for the LLM, so it can fix its query; they never contain
anything but the query's own text.
"""

from dataclasses import dataclass

from pglast import ast, enums, parse_sql
from pglast.parser import ParseError
from pglast.stream import RawStream
from pglast.visitors import Visitor

STATS_VIEWS = (
    "v_race_winners",
    "v_driver_career",
    "v_season_summary",
    "v_head_to_head_teammates",
)
MAX_SQL_CHARS = 4000

# Node types a stats query may contain (everything else is rejected).
_ALLOWED_NODES = frozenset(
    {
        "RawStmt", "SelectStmt", "ResTarget", "ColumnRef", "A_Star", "A_Const",
        "Integer", "Float", "String", "Boolean", "BitString", "A_Expr", "BoolExpr",
        "NullTest", "BooleanTest", "FuncCall", "SortBy", "WindowDef", "RangeVar",
        "Alias", "JoinExpr", "RangeSubselect", "WithClause", "CommonTableExpr",
        "SubLink", "CaseExpr", "CaseWhen", "CoalesceExpr", "MinMaxExpr", "TypeCast",
        "TypeName", "A_ArrayExpr", "A_Indirection", "A_Indices", "RowExpr",
        "SQLValueFunction", "GroupingSet", "CollateClause",
    }
)  # fmt: skip

_ALLOWED_FUNCTIONS = frozenset(
    [
        "count",
        "sum",
        "avg",
        "min",
        "max",
        "string_agg",
        "array_agg",
        "bool_and",
        "bool_or",
        "every",
        "stddev",
        "stddev_pop",
        "stddev_samp",
        "variance",
        "var_pop",
        "var_samp",
        "percentile_cont",
        "percentile_disc",
        "mode",
        "row_number",
        "rank",
        "dense_rank",
        "percent_rank",
        "cume_dist",
        "ntile",
        "lag",
        "lead",
        "first_value",
        "last_value",
        "nth_value",
        "round",
        "floor",
        "ceil",
        "ceiling",
        "abs",
        "trunc",
        "mod",
        "power",
        "sqrt",
        "sign",
        "lower",
        "upper",
        "initcap",
        "length",
        "char_length",
        "trim",
        "btrim",
        "ltrim",
        "rtrim",
        "substring",
        "substr",
        "left",
        "right",
        "concat",
        "concat_ws",
        "replace",
        "split_part",
        "position",
        "strpos",
        "starts_with",
        "to_char",
        "to_number",
        "extract",
        "date_part",
        "date_trunc",
        "age",
        "make_date",
        "array_length",
        "cardinality",
        "array_to_string",
        "unnest",
    ]
)
# Cast targets (Postgres internal names, as the parser reports them).
_ALLOWED_TYPES = frozenset(
    [
        "int2",
        "int4",
        "int8",
        "numeric",
        "float4",
        "float8",
        "text",
        "varchar",
        "bpchar",
        "date",
        "interval",
        "bool",
        "timestamp",
        "timestamptz",
        "time",
    ]
)
_ALLOWED_VALUE_FUNCTIONS = frozenset(
    {
        enums.SQLValueFunctionOp.SVFOP_CURRENT_DATE,
        enums.SQLValueFunctionOp.SVFOP_CURRENT_TIMESTAMP,
        enums.SQLValueFunctionOp.SVFOP_CURRENT_TIMESTAMP_N,
        enums.SQLValueFunctionOp.SVFOP_LOCALTIMESTAMP,
        enums.SQLValueFunctionOp.SVFOP_LOCALTIMESTAMP_N,
    }
)
_SCHEMAS = (None, "public")


class UnsafeQueryError(ValueError):
    """The SQL is not a query the stats tool will run. The message is for the LLM."""


@dataclass(frozen=True)
class ValidatedQuery:
    sql: str  # deparsed from the validated tree, with the row limit applied
    views: tuple[str, ...]  # the stats views it reads


class _Checker(Visitor):
    def __init__(self) -> None:
        super().__init__()
        self.views: set[str] = set()
        self.ctes: set[str] = set()
        self.relations: list[ast.RangeVar] = []

    def visit(self, ancestors, node) -> None:  # noqa: ANN001 (pglast's API)
        kind = type(node).__name__
        if kind not in _ALLOWED_NODES:
            raise UnsafeQueryError(_node_message(kind))
        if isinstance(node, ast.CommonTableExpr):
            self.ctes.add(node.ctename)
        elif isinstance(node, ast.RangeVar):
            self.relations.append(node)
        elif isinstance(node, ast.SelectStmt):
            if node.intoClause is not None:
                raise UnsafeQueryError("SELECT ... INTO is not allowed; just SELECT")
            if node.lockingClause:
                raise UnsafeQueryError("FOR UPDATE/SHARE is not allowed")
        elif isinstance(node, ast.FuncCall):
            schema, name = _split(node.funcname)
            if schema not in (None, "pg_catalog") or name not in _ALLOWED_FUNCTIONS:
                raise UnsafeQueryError(
                    f"function {name}() is not allowed; use standard aggregates, "
                    "window, math, string and date functions"
                )
        elif isinstance(node, ast.TypeName):
            _, name = _split(node.names)
            if name not in _ALLOWED_TYPES:
                raise UnsafeQueryError(f"casting to {name} is not allowed")
        elif (
            isinstance(node, ast.SQLValueFunction)
            and node.op not in _ALLOWED_VALUE_FUNCTIONS
        ):
            raise UnsafeQueryError("only CURRENT_DATE / CURRENT_TIMESTAMP are allowed")


def _node_message(kind: str) -> str:
    if kind.endswith("Stmt"):
        return "only a single SELECT query is allowed (no INSERT/UPDATE/DELETE/DDL)"
    if kind == "ParamRef":
        return "parameters ($1) are not allowed; write the values into the query"
    if kind == "RangeFunction":
        return "functions in FROM are not allowed; select from the stats views"
    return f"{kind} is not allowed in a stats query"


def _split(names) -> tuple[str | None, str]:  # noqa: ANN001
    parts = [n.sval for n in names]
    return (parts[-2] if len(parts) > 1 else None), parts[-1]


def validate_stats_sql(sql: str, *, max_rows: int) -> ValidatedQuery:
    """Check the SQL and return the query to run, limited to `max_rows` + 1 rows
    (one extra, so the caller can tell the result was cut off)."""
    if not isinstance(sql, str) or not sql.strip():
        raise UnsafeQueryError("the query is empty")
    if len(sql) > MAX_SQL_CHARS:
        raise UnsafeQueryError(f"the query is longer than {MAX_SQL_CHARS} characters")
    try:
        statements = parse_sql(sql)
    except ParseError as exc:
        raise UnsafeQueryError(f"SQL syntax error: {exc}") from None
    if len(statements) != 1:
        raise UnsafeQueryError("send exactly one SELECT statement")
    (raw,) = statements
    if not isinstance(raw.stmt, ast.SelectStmt):
        raise UnsafeQueryError(_node_message(type(raw.stmt).__name__))

    checker = _Checker()
    checker(raw)
    for relation in checker.relations:
        name = relation.relname
        if relation.catalogname or relation.schemaname not in _SCHEMAS:
            raise UnsafeQueryError(f"only the stats views can be queried, not {name}")
        if name in STATS_VIEWS:
            checker.views.add(name)
        elif not (relation.schemaname is None and name in checker.ctes):
            raise UnsafeQueryError(
                f"unknown table {name}; query only {', '.join(STATS_VIEWS)}"
            )
    if not checker.views:
        raise UnsafeQueryError(f"the query must read from {', '.join(STATS_VIEWS)}")

    _apply_limit(raw.stmt, max_rows + 1)
    return ValidatedQuery(RawStream()(raw), tuple(sorted(checker.views)))


def _apply_limit(stmt: ast.SelectStmt, limit: int) -> None:
    """Set LIMIT to at most `limit`. A non-constant LIMIT is rejected."""
    current = stmt.limitCount
    if current is not None:
        value = getattr(getattr(current, "val", None), "ival", None)
        if not isinstance(current, ast.A_Const) or not isinstance(value, int):
            raise UnsafeQueryError("LIMIT must be a plain number")
        if value <= limit:
            return
    stmt.limitCount = ast.A_Const(val=ast.Integer(ival=limit))
    stmt.limitOption = enums.LimitOption.LIMIT_OPTION_COUNT
