"""Restricted factor expression DSL compiled to native Polars expressions."""
from __future__ import annotations

import ast
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import pandas as pd
import polars as pl


class FactorDslError(ValueError):
    """Raised when a factor expression leaves the supported safe subset."""


_DTYPES = {
    "float64": pl.Float64,
    "float32": pl.Float32,
    "int64": pl.Int64,
    "int32": pl.Int32,
    "boolean": pl.Boolean,
    "bool": pl.Boolean,
}


class _ExpressionCompiler:
    def __init__(
        self,
        input_columns: Dict[str, str],
        window_by: Optional[Sequence[str]] = None,
    ):
        self.input_columns = input_columns
        self.window_by = tuple(window_by or ())

    def compile(self, expression: str) -> pl.Expr:
        try:
            tree = ast.parse(expression, mode="eval")
        except SyntaxError as exc:
            raise FactorDslError(f"表达式语法错误: {exc.msg}") from exc
        result = self._visit(tree.body)
        if not isinstance(result, pl.Expr):
            result = pl.lit(result)
        return result

    def _visit(self, node):
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (str, int, float, bool)) or node.value is None:
                return pl.lit(node.value)
            raise FactorDslError(f"不支持的常量: {node.value!r}")

        if isinstance(node, ast.BinOp):
            left = self._visit(node.left)
            right = self._visit(node.right)
            operations = {
                ast.Add: lambda: left + right,
                ast.Sub: lambda: left - right,
                ast.Mult: lambda: left * right,
                ast.Div: lambda: left / right,
                ast.Mod: lambda: left % right,
                ast.Pow: lambda: left.pow(right),
            }
            operation = operations.get(type(node.op))
            if operation is None:
                raise FactorDslError(f"不支持的二元运算: {type(node.op).__name__}")
            return operation()

        if isinstance(node, ast.UnaryOp):
            operand = self._visit(node.operand)
            if isinstance(node.op, ast.USub):
                return -operand
            if isinstance(node.op, ast.UAdd):
                return operand
            if isinstance(node.op, ast.Not):
                return ~operand
            raise FactorDslError(f"不支持的一元运算: {type(node.op).__name__}")

        if isinstance(node, ast.BoolOp):
            values = [self._visit(value) for value in node.values]
            result = values[0]
            for value in values[1:]:
                if isinstance(node.op, ast.And):
                    result = result & value
                elif isinstance(node.op, ast.Or):
                    result = result | value
                else:
                    raise FactorDslError(f"不支持的布尔运算: {type(node.op).__name__}")
            return result

        if isinstance(node, ast.Compare):
            left = self._visit(node.left)
            result = None
            for operator, comparator in zip(node.ops, node.comparators):
                right = self._visit(comparator)
                comparisons = {
                    ast.Eq: lambda: left == right,
                    ast.NotEq: lambda: left != right,
                    ast.Gt: lambda: left > right,
                    ast.GtE: lambda: left >= right,
                    ast.Lt: lambda: left < right,
                    ast.LtE: lambda: left <= right,
                }
                comparison = comparisons.get(type(operator))
                if comparison is None:
                    raise FactorDslError(f"不支持的比较运算: {type(operator).__name__}")
                current = comparison()
                result = current if result is None else result & current
                left = right
            return result

        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.keywords:
                raise FactorDslError("只允许调用白名单函数，且不支持关键字参数")
            return self._call(node.func.id, node.args)

        raise FactorDslError(f"不支持的表达式节点: {type(node).__name__}")

    @staticmethod
    def _constant(node, expected_type=None):
        if not isinstance(node, ast.Constant):
            raise FactorDslError("该参数必须是常量")
        value = node.value
        if expected_type is not None and not isinstance(value, expected_type):
            expected_name = (
                "/".join(value_type.__name__ for value_type in expected_type)
                if isinstance(expected_type, tuple)
                else expected_type.__name__
            )
            raise FactorDslError(f"参数类型必须是 {expected_name}")
        return value

    def _call(self, name: str, args: List[ast.AST]) -> pl.Expr:
        if name == "col":
            if len(args) != 1:
                raise FactorDslError("col() 需要一个输入别名")
            alias = self._constant(args[0], str)
            if alias not in self.input_columns:
                raise FactorDslError(f"表达式引用了未声明输入: {alias}")
            return pl.col(self.input_columns[alias])

        if name == "lit":
            if len(args) != 1:
                raise FactorDslError("lit() 需要一个参数")
            return self._visit(args[0])

        if name == "safe_div":
            if len(args) != 2:
                raise FactorDslError("safe_div() 需要分子和分母")
            numerator, denominator = (self._visit(arg) for arg in args)
            return pl.when(denominator.is_not_null() & (denominator != 0)).then(
                numerator / denominator
            ).otherwise(None)

        if name == "round":
            if len(args) not in {1, 2}:
                raise FactorDslError("round() 接受表达式和可选小数位")
            decimals = int(self._constant(args[1], (int, float))) if len(args) == 2 else 0
            return self._visit(args[0]).round(decimals)

        if name in {"abs", "sqrt", "exp", "log1p"}:
            if len(args) != 1:
                raise FactorDslError(f"{name}() 需要一个参数")
            expression = self._visit(args[0])
            return {
                "abs": expression.abs,
                "sqrt": expression.sqrt,
                "exp": expression.exp,
                "log1p": expression.log1p,
            }[name]()

        if name == "log":
            if len(args) not in {1, 2}:
                raise FactorDslError("log() 接受表达式和可选底数")
            expression = self._visit(args[0])
            base = self._constant(args[1], (int, float)) if len(args) == 2 else None
            return expression.log(base)

        if name == "clip":
            if len(args) != 3:
                raise FactorDslError("clip() 需要表达式、下界和上界")
            return self._visit(args[0]).clip(self._visit(args[1]), self._visit(args[2]))

        if name == "fill_null":
            if len(args) != 2:
                raise FactorDslError("fill_null() 需要表达式和填充值")
            return self._visit(args[0]).fill_null(self._visit(args[1]))

        if name == "coalesce":
            if len(args) < 2:
                raise FactorDslError("coalesce() 至少需要两个参数")
            return pl.coalesce([self._visit(arg) for arg in args])

        if name == "lag":
            if len(args) != 2:
                raise FactorDslError("lag() requires an expression and a period count")
            self._require_window_context(name)
            periods = int(self._constant(args[1], (int, float)))
            if periods < 1:
                raise FactorDslError("lag() period count must be positive")
            return self._visit(args[0]).shift(periods).over(self.window_by)

        if name in {"rolling_mean", "rolling_sum", "rolling_std"}:
            if len(args) not in {2, 3}:
                raise FactorDslError(
                    f"{name}() requires an expression, window and optional minimum periods"
                )
            self._require_window_context(name)
            window = int(self._constant(args[1], (int, float)))
            min_periods = (
                int(self._constant(args[2], (int, float))) if len(args) == 3 else window
            )
            if window < 1 or min_periods < 1 or min_periods > window:
                raise FactorDslError(f"{name}() has invalid window arguments")
            expression = self._visit(args[0])
            method = {
                "rolling_mean": expression.rolling_mean,
                "rolling_sum": expression.rolling_sum,
                "rolling_std": expression.rolling_std,
            }[name]
            return method(window_size=window, min_samples=min_periods).over(self.window_by)

        if name == "cagr":
            if len(args) != 2:
                raise FactorDslError("cagr() requires an expression and a period count")
            self._require_window_context(name)
            periods = int(self._constant(args[1], (int, float)))
            if periods < 1:
                raise FactorDslError("cagr() period count must be positive")
            current = self._visit(args[0])
            previous = current.shift(periods).over(self.window_by)
            return pl.when(
                current.is_not_null()
                & previous.is_not_null()
                & (current > 0)
                & (previous > 0)
            ).then((current / previous).pow(1.0 / periods) - 1.0).otherwise(None)

        if name == "positive_streak":
            if len(args) != 1:
                raise FactorDslError("positive_streak() requires one expression")
            self._require_window_context(name)

            def streak(series: pl.Series) -> pl.Series:
                count = 0
                previous_year = None
                values = []
                for item in series:
                    value = item.get("value") if item is not None else None
                    period = item.get("period") if item is not None else None
                    try:
                        year = int(str(period)[:4])
                    except (TypeError, ValueError):
                        year = None
                    if value is not None and value > 0:
                        count = count + 1 if previous_year is not None and year == previous_year + 1 else 1
                    else:
                        count = 0
                    values.append(count)
                    previous_year = year
                return pl.Series(values, dtype=pl.Int64)

            return pl.struct(
                self._visit(args[0]).alias("value"),
                pl.col("end_date").alias("period"),
            ).map_batches(
                streak,
                return_dtype=pl.Int64,
                returns_scalar=False,
            ).over(self.window_by)

        if name == "when":
            if len(args) != 3:
                raise FactorDslError("when() 需要条件、真值和假值")
            return pl.when(self._visit(args[0])).then(self._visit(args[1])).otherwise(
                self._visit(args[2])
            )

        raise FactorDslError(f"不允许的函数: {name}")

    def _require_window_context(self, name: str) -> None:
        if not self.window_by:
            raise FactorDslError(f"{name}() is only valid for point-in-time report factors")


def compile_expression(
    expression: str,
    input_columns: Dict[str, str],
    output_name: Optional[str] = None,
    output_dtype: str = "float64",
    window_by: Optional[Sequence[str]] = None,
) -> pl.Expr:
    """Compile the restricted expression into a native Polars expression."""
    compiled = _ExpressionCompiler(input_columns, window_by=window_by).compile(expression)
    dtype = _DTYPES.get(output_dtype)
    if dtype is None:
        raise FactorDslError(f"不支持的输出类型: {output_dtype}")
    compiled = compiled.cast(dtype, strict=False)
    return compiled.alias(output_name) if output_name else compiled


def validate_expression(expression: str, input_columns: Dict[str, str]) -> None:
    compile_expression(expression, input_columns)


def execute_factor_batch(
    frame: pd.DataFrame,
    factors: Iterable[object],
) -> Tuple[Dict[str, pd.Series], Dict[str, str]]:
    """Evaluate compatible DSL factors together in a single lazy Polars plan."""
    expressions = []
    selected = []
    errors: Dict[str, str] = {}
    columns = set(frame.columns)
    missing_optional_columns = set()
    for factor in factors:
        input_columns = dict(getattr(factor, "input_columns", {}) or {})
        optional_columns = set(getattr(factor, "optional_input_columns", []) or [])
        missing = sorted(set(input_columns.values()) - columns - optional_columns)
        if missing:
            errors[factor.id] = f"缺少输入字段: {', '.join(missing)}"
            continue
        missing_optional_columns.update(optional_columns - columns)
        try:
            expressions.append(
                compile_expression(
                    factor.dsl_expression,
                    input_columns,
                    output_name=factor.id,
                    output_dtype=getattr(factor, "output_dtype", "float64"),
                )
            )
            selected.append(factor)
        except FactorDslError as exc:
            errors[factor.id] = str(exc)

    if not expressions:
        return {}, errors

    polars_frame = pl.from_pandas(frame.reset_index(drop=True), include_index=False)
    if missing_optional_columns:
        polars_frame = polars_frame.with_columns(
            [pl.lit(None).alias(column) for column in sorted(missing_optional_columns)]
        )
    result = polars_frame.lazy().select(expressions).collect()
    outputs = {
        factor.id: pd.Series(result.get_column(factor.id).to_numpy(), index=frame.index)
        for factor in selected
    }
    return outputs, errors
