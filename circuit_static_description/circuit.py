"""Circuit load/save/evaluate implementation for boolean gate circuits."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Sequence, Tuple


class CircuitError(Exception):
    """Base exception raised by circuit_static_description."""


class CircuitFormatError(CircuitError):
    """Raised when a circuit description file cannot be parsed."""


@dataclass(frozen=True)
class _ExprNode:
    op: str
    args: Tuple["_ExprNode", ...] = ()
    input_index: int | None = None


class Circuit:
    """A boolean logic circuit with only input count, output count and output expressions."""

    SUPPORTED_OPS = {
        "AND": 2,
        "OR": 2,
        "NOT": 1,
        "XOR": 2,
        "NAND": 2,
        "NOR": 2,
    }

    def __init__(self, input_count: int, output_count: int, outputs: List[str] | None = None) -> None:
        if input_count < 1:
            raise CircuitError("input_count must be at least 1")
        if output_count < 1:
            raise CircuitError("output_count must be at least 1")
        self.input_count = input_count
        self.output_count = output_count
        self.outputs = outputs or ["" for _ in range(output_count)]
        if len(self.outputs) != self.output_count:
            raise CircuitError("outputs length must match output_count")

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.write_text(self.to_text(), encoding="utf-8")

    def to_text(self) -> str:
        lines: List[str] = [f"INPUTS {self.input_count}", f"OUTPUTS {self.output_count}"]
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
            if not line.upper().startswith(prefix):
                raise CircuitFormatError(f"Expected '{prefix}' header, got: {line}")
            parts = line.split(None, 1)
            if len(parts) != 2 or not parts[1].isdigit():
                raise CircuitFormatError(f"Invalid {prefix} header: {line}")
            return int(parts[1])

        input_count = parse_header("INPUTS", lines[0])
        output_count = parse_header("OUTPUTS", lines[1])
        if len(lines) != output_count + 2:
            raise CircuitFormatError(
                f"Expected {output_count} output lines after headers, got {len(lines) - 2}"
            )

        outputs: List[str] = []
        for index, line in enumerate(lines[2:]):
            if "=" not in line:
                raise CircuitFormatError(f"Missing '=' on output line {index}: {line}")
            name, expr = [part.strip() for part in line.split("=", 1)]
            expected_name = f"OUT{index}"
            if name.upper() != expected_name:
                raise CircuitFormatError(f"Expected output name '{expected_name}', got '{name}'")
            if not expr:
                raise CircuitFormatError(f"Empty expression for {expected_name}")
            outputs.append(expr)

        circuit = cls(input_count=input_count, output_count=output_count, outputs=outputs)
        return circuit

    def evaluate(self, inputs: Sequence[Any]) -> List[int]:
        if len(inputs) != self.input_count:
            raise CircuitError(
                f"Expected {self.input_count} input values, got {len(inputs)}"
            )
        parsed_outputs = [self._parse_expression(expression) for expression in self.outputs]
        return [int(bool(self._evaluate_node(node, inputs))) for node in parsed_outputs]

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
        if node.op == "INPUT":
            assert node.input_index is not None
            if node.input_index < 0 or node.input_index >= len(inputs):
                raise CircuitError(f"Input reference I{node.input_index} is out of range")
            return bool(inputs[node.input_index])
        values = [self._evaluate_node(child, inputs) for child in node.args]
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
        raise CircuitFormatError("Expression must begin with an input reference or operator")

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
