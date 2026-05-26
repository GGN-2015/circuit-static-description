"""Circuit load/save/evaluate implementation for boolean gate circuits."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence, Tuple


class CircuitError(Exception):
    """Base exception raised by circuit_static_description."""


class CircuitFormatError(CircuitError):
    """Raised when a circuit description file cannot be parsed."""


@dataclass(frozen=True)
class _ExprNode:
    op: str
    args: Tuple["_ExprNode", ...] = ()
    input_index: int | None = None
    variable_name: str | None = None


class Circuit:
    """A boolean logic circuit with optional intermediate variable definitions."""

    SUPPORTED_OPS = {
        "AND": 2,
        "OR": 2,
        "NOT": 1,
        "XOR": 2,
        "NAND": 2,
        "NOR": 2,
    }

    def __init__(
        self,
        input_count: int,
        output_count: int,
        outputs: List[str] | None = None,
        variables: Mapping[str, str] | Sequence[Tuple[str, str]] | None = None,
    ) -> None:
        if input_count < 1:
            raise CircuitError("input_count must be at least 1")
        if output_count < 1:
            raise CircuitError("output_count must be at least 1")
        self.input_count = input_count
        self.output_count = output_count
        self.variables = _normalize_variables(variables)
        self.outputs = outputs or ["" for _ in range(output_count)]
        if len(self.outputs) != self.output_count:
            raise CircuitError("outputs length must match output_count")
        self._parsed_variables: Dict[str, _ExprNode] | None = None
        self._parsed_outputs: List[_ExprNode] | None = None

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.write_text(self.to_text(), encoding="utf-8")

    def to_text(self) -> str:
        lines: List[str] = [f"INPUTS {self.input_count}", f"OUTPUTS {self.output_count}"]
        for name, expression in self.variables:
            lines.append(f"{name} = {expression}")
        for index, expression in enumerate(self.outputs):
            lines.append(f"OUT{index} = {expression}")
        return "\n".join(lines) + "\n"

    @classmethod
    def load(cls, path: str | Path) -> "Circuit":
        path = Path(path)
        return cls.from_text(path.read_text(encoding="utf-8"))

    @classmethod
    def from_text(cls, text: str) -> "Circuit":
        lines = [line.split("#", 1)[0].strip() for line in text.splitlines()]
        lines = [line for line in lines if line]
        if len(lines) < 2:
            raise CircuitFormatError("Circuit description must include INPUTS and OUTPUTS")

        def parse_header(prefix: str, line: str) -> int:
            parts = line.split(None, 1)
            if len(parts) != 2 or parts[0].upper() != prefix:
                raise CircuitFormatError(f"Expected '{prefix}' header, got: {line}")
            if len(parts) != 2 or not parts[1].isdigit():
                raise CircuitFormatError(f"Invalid {prefix} header: {line}")
            return int(parts[1])

        input_count = parse_header("INPUTS", lines[0])
        output_count = parse_header("OUTPUTS", lines[1])
        variables: List[Tuple[str, str]] = []
        seen_variables: set[str] = set()
        outputs: List[str | None] = [None for _ in range(output_count)]
        seen_outputs: set[int] = set()
        for line_number, line in enumerate(lines[2:], start=3):
            if "=" not in line:
                raise CircuitFormatError(f"Missing '=' on line {line_number}: {line}")
            name, expr = [part.strip() for part in line.split("=", 1)]
            normalized_name = name.upper()
            if not expr:
                raise CircuitFormatError(f"Empty expression for {normalized_name}")

            if _is_variable_name(normalized_name):
                if normalized_name in seen_variables:
                    raise CircuitFormatError(f"Duplicate variable definition: {normalized_name}")
                variables.append((normalized_name, expr))
                seen_variables.add(normalized_name)
                continue

            output_index = _parse_output_name(normalized_name)
            if output_index is None:
                raise CircuitFormatError(
                    f"Expected variable name V<number> or output name OUT<number>, got '{name}'"
                )
            if output_index >= output_count:
                raise CircuitFormatError(
                    f"Output name OUT{output_index} is outside OUTPUTS {output_count}"
                )
            if output_index in seen_outputs:
                raise CircuitFormatError(f"Duplicate output definition: OUT{output_index}")
            outputs[output_index] = expr
            seen_outputs.add(output_index)

        missing_outputs = [f"OUT{index}" for index, expr in enumerate(outputs) if expr is None]
        if missing_outputs:
            raise CircuitFormatError(f"Missing output definitions: {', '.join(missing_outputs)}")

        circuit = cls(
            input_count=input_count,
            output_count=output_count,
            outputs=[expr for expr in outputs if expr is not None],
            variables=variables,
        )
        circuit._ensure_parsed_graph()
        return circuit

    def evaluate(self, inputs: Sequence[Any]) -> List[int]:
        if len(inputs) != self.input_count:
            raise CircuitError(
                f"Expected {self.input_count} input values, got {len(inputs)}"
            )
        parsed_variables, parsed_outputs = self._ensure_parsed_graph()
        variable_cache: Dict[str, bool] = {}
        return [
            int(bool(_evaluate_tree(node, inputs, parsed_variables, variable_cache)))
            for node in parsed_outputs
        ]

    def _ensure_parsed_outputs(self) -> List[_ExprNode]:
        _, parsed_outputs = self._ensure_parsed_graph()
        return parsed_outputs

    def _ensure_parsed_graph(self) -> Tuple[Dict[str, _ExprNode], List[_ExprNode]]:
        if self._parsed_variables is None or self._parsed_outputs is None:
            parsed_variables = {
                name: self._parse_expression(expression) for name, expression in self.variables
            }
            parsed_outputs = [self._parse_expression(expression) for expression in self.outputs]
            self._validate_graph(parsed_variables, parsed_outputs)
            self._parsed_variables = parsed_variables
            self._parsed_outputs = parsed_outputs
        return self._parsed_variables, self._parsed_outputs

    def _parse_expression(self, text: str) -> _ExprNode:
        text = text.strip()
        if not text:
            raise CircuitFormatError("Expression cannot be empty")
        parser = _ExpressionParser(text)
        node = parser.parse()
        if not parser.is_done():
            raise CircuitFormatError(f"Unexpected text after expression: {parser.remaining_text()}")
        return node

    def _evaluate_node(self, node: _ExprNode, inputs: Sequence[Any]) -> bool:
        parsed_variables, _ = self._ensure_parsed_graph()
        return _evaluate_tree(node, inputs, parsed_variables, {})

    def _validate_graph(
        self,
        parsed_variables: Dict[str, _ExprNode],
        parsed_outputs: List[_ExprNode],
    ) -> None:
        for name, node in parsed_variables.items():
            self._validate_expression_references(node, parsed_variables, f"variable {name}")
        for index, node in enumerate(parsed_outputs):
            self._validate_expression_references(node, parsed_variables, f"OUT{index}")

        visit_state: Dict[str, str] = {}
        path: List[str] = []

        def visit_variable(name: str) -> None:
            state = visit_state.get(name)
            if state == "done":
                return
            if state == "visiting":
                cycle_start = path.index(name) if name in path else 0
                cycle = path[cycle_start:] + [name]
                raise CircuitFormatError(
                    f"Circular variable dependency: {' -> '.join(cycle)}"
                )

            visit_state[name] = "visiting"
            path.append(name)
            for reference in _iter_variable_references(parsed_variables[name]):
                visit_variable(reference)
            path.pop()
            visit_state[name] = "done"

        for name in parsed_variables:
            visit_variable(name)

    def _validate_expression_references(
        self,
        node: _ExprNode,
        parsed_variables: Dict[str, _ExprNode],
        owner: str,
    ) -> None:
        for child in _walk_tree(node):
            if child.op == "INPUT":
                assert child.input_index is not None
                if child.input_index < 0 or child.input_index >= self.input_count:
                    raise CircuitFormatError(
                        f"{owner} references input I{child.input_index}, "
                        f"but INPUTS is {self.input_count}"
                    )
            if child.op == "VARIABLE":
                assert child.variable_name is not None
                if child.variable_name not in parsed_variables:
                    raise CircuitFormatError(
                        f"{owner} references undefined variable {child.variable_name}"
                    )


def _normalize_variables(
    variables: Mapping[str, str] | Sequence[Tuple[str, str]] | None,
) -> List[Tuple[str, str]]:
    if variables is None:
        return []
    items = variables.items() if isinstance(variables, Mapping) else variables
    normalized_variables: List[Tuple[str, str]] = []
    seen: set[str] = set()
    for name, expression in items:
        normalized_name = str(name).upper()
        if not _is_variable_name(normalized_name):
            raise CircuitError(f"Invalid variable name '{name}'; expected V<number>")
        if normalized_name in seen:
            raise CircuitError(f"Duplicate variable definition: {normalized_name}")
        if not isinstance(expression, str) or not expression.strip():
            raise CircuitError(f"Expression for {normalized_name} cannot be empty")
        normalized_variables.append((normalized_name, expression.strip()))
        seen.add(normalized_name)
    return normalized_variables


def _is_variable_name(name: str) -> bool:
    return len(name) > 1 and name.startswith("V") and name[1:].isdigit()


def _parse_output_name(name: str) -> int | None:
    if len(name) <= 3 or not name.startswith("OUT") or not name[3:].isdigit():
        return None
    return int(name[3:])


def _walk_tree(node: _ExprNode) -> List[_ExprNode]:
    nodes = [node]
    for child in node.args:
        nodes.extend(_walk_tree(child))
    return nodes


def _iter_variable_references(node: _ExprNode) -> List[str]:
    references: List[str] = []
    for child in _walk_tree(node):
        if child.op == "VARIABLE":
            assert child.variable_name is not None
            references.append(child.variable_name)
    return references


def _evaluate_tree(
    node: _ExprNode,
    inputs: Sequence[Any],
    variables: Dict[str, _ExprNode],
    variable_cache: Dict[str, bool],
) -> bool:
    if node.op == "INPUT":
        assert node.input_index is not None
        if node.input_index < 0 or node.input_index >= len(inputs):
            raise CircuitError(f"Input reference I{node.input_index} is out of range")
        return bool(inputs[node.input_index])
    if node.op == "VARIABLE":
        assert node.variable_name is not None
        if node.variable_name in variable_cache:
            return variable_cache[node.variable_name]
        if node.variable_name not in variables:
            raise CircuitError(f"Variable reference {node.variable_name} is undefined")
        value = _evaluate_tree(
            variables[node.variable_name],
            inputs,
            variables,
            variable_cache,
        )
        variable_cache[node.variable_name] = value
        return value

    values = [
        _evaluate_tree(child, inputs, variables, variable_cache) for child in node.args
    ]
    if node.op == "AND":
        return values[0] and values[1]
    if node.op == "OR":
        return values[0] or values[1]
    if node.op == "NOT":
        return not values[0]
    if node.op == "XOR":
        return values[0] ^ values[1]
    if node.op == "NAND":
        return not (values[0] and values[1])
    if node.op == "NOR":
        return not (values[0] or values[1])
    raise CircuitError(f"Unsupported operator during evaluation: {node.op}")


class _ExpressionParser:
    def __init__(self, text: str) -> None:
        self.text = text
        self.pos = 0

    def parse(self) -> _ExprNode:
        node = self._parse_term()
        return node

    def is_done(self) -> bool:
        self._skip_whitespace()
        return self.pos >= len(self.text)

    def remaining_text(self) -> str:
        return self.text[self.pos :].strip()

    def _parse_term(self) -> _ExprNode:
        self._skip_whitespace()
        if self._peek().isalpha():
            token = self._parse_identifier().upper()
            if token.startswith("I") and token[1:].isdigit():
                index = int(token[1:])
                if index < 0:
                    raise CircuitFormatError(f"Invalid input reference: {token}")
                return _ExprNode(op="INPUT", input_index=index)
            if token.startswith("V"):
                if token[1:].isdigit():
                    return _ExprNode(op="VARIABLE", variable_name=token)
                raise CircuitFormatError(f"Invalid variable reference: {token}")
            if token not in Circuit.SUPPORTED_OPS:
                raise CircuitFormatError(f"Unsupported operator: {token}")
            self._skip_whitespace()
            if self._peek() != "(":
                raise CircuitFormatError(f"Operator '{token}' requires parentheses")
            self._consume("(")
            args = self._parse_arguments(token)
            self._consume(")")
            expected = Circuit.SUPPORTED_OPS[token]
            if len(args) != expected:
                raise CircuitFormatError(
                    f"Operator '{token}' expects {expected} arguments, got {len(args)}"
                )
            return _ExprNode(op=token, args=tuple(args))
        raise CircuitFormatError(
            "Expression must begin with an input reference, variable reference, or operator"
        )

    def _parse_arguments(self, operator: str) -> List[_ExprNode]:
        arguments: List[_ExprNode] = []
        while True:
            self._skip_whitespace()
            arguments.append(self._parse_term())
            self._skip_whitespace()
            if self._peek() == ")":
                break
            self._consume(",")
        return arguments

    def _parse_identifier(self) -> str:
        start = self.pos
        while self.pos < len(self.text) and self.text[self.pos].isalnum():
            self.pos += 1
        return self.text[start : self.pos]

    def _skip_whitespace(self) -> None:
        while self.pos < len(self.text) and self.text[self.pos].isspace():
            self.pos += 1

    def _peek(self) -> str:
        self._skip_whitespace()
        if self.pos >= len(self.text):
            return ""
        return self.text[self.pos]

    def _consume(self, expected: str) -> None:
        self._skip_whitespace()
        if self.pos >= len(self.text) or self.text[self.pos] != expected:
            raise CircuitFormatError(f"Expected '{expected}' at position {self.pos}")
        self.pos += 1
