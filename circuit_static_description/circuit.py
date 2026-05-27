"""Circuit load/save/evaluate implementation for boolean gate circuits."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterator, List, Mapping, Sequence, Tuple

_BINARY_MAGIC = b"CSDCIR\x00"
_BINARY_VERSION = 1
_MAX_VARUINT_BYTES = 10
_INPUT_OPCODE = 0x00
_VARIABLE_OPCODE = 0x01
_FALSE_OPCODE = 0x02
_TRUE_OPCODE = 0x03
_OP_TO_OPCODE = {
    "AND": 0x10,
    "OR": 0x11,
    "NOT": 0x12,
    "XOR": 0x13,
    "NAND": 0x14,
    "NOR": 0x15,
}
_OPCODE_TO_OP = {opcode: op for op, opcode in _OP_TO_OPCODE.items()}


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
    variable_index: int | None = None
    constant_value: bool | None = None


@dataclass(frozen=True)
class _CompiledGraph:
    variable_nodes: Tuple[_ExprNode, ...]
    output_nodes: Tuple[_ExprNode, ...]
    evaluation_order: Tuple[int, ...]


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
        outputs: Sequence[str | bool] | None = None,
        variables: (
            Mapping[str, str | bool] | Sequence[Tuple[str, str | bool]] | None
        ) = None,
    ) -> None:
        if input_count < 1:
            raise CircuitError("input_count must be at least 1")
        if output_count < 1:
            raise CircuitError("output_count must be at least 1")
        self.input_count = input_count
        self.output_count = output_count
        self.variables = _normalize_variables(variables)
        self.outputs = (
            [_normalize_expression(expression, "Output expression") for expression in outputs]
            if outputs is not None
            else ["" for _ in range(output_count)]
        )
        if len(self.outputs) != self.output_count:
            raise CircuitError("outputs length must match output_count")
        self._compiled_graph: _CompiledGraph | None = None

    def save(self, path: str | Path, mode: str = "binary", simplify: bool = True) -> None:
        path = Path(path)
        normalized_mode = mode.lower()
        circuit = self.simplify() if simplify else self
        if normalized_mode in {"binary", "bin"}:
            path.write_bytes(circuit.to_binary())
            return
        if normalized_mode in {"text", "txt"}:
            path.write_text(circuit.to_text(), encoding="utf-8")
            return
        raise CircuitError("mode must be 'binary' or 'text'")

    def to_text(self, simplify: bool = False) -> str:
        if simplify:
            return self.simplify().to_text()
        lines: List[str] = [f"INPUTS {self.input_count}", f"OUTPUTS {self.output_count}"]
        for name, expression in self.variables:
            lines.append(f"{name} = {expression}")
        for index, expression in enumerate(self.outputs):
            lines.append(f"OUT{index} = {expression}")
        return "\n".join(lines) + "\n"

    def to_binary(self, simplify: bool = False) -> bytes:
        if simplify:
            return self.simplify().to_binary()
        graph = self._ensure_compiled_graph()
        writer = _BinaryWriter()
        writer.write_bytes(_BINARY_MAGIC)
        writer.write_byte(_BINARY_VERSION)
        writer.write_varuint(self.input_count)
        writer.write_varuint(self.output_count)
        writer.write_varuint(len(self.variables))

        for index, (name, _) in enumerate(self.variables):
            writer.write_varuint(_variable_number_from_name(name))
            _write_expr_node(writer, graph.variable_nodes[index], self.variables)
        for node in graph.output_nodes:
            _write_expr_node(writer, node, self.variables)
        return writer.to_bytes()

    def simplify(self) -> "Circuit":
        parsed_variables = {
            name: self._parse_expression(expression) for name, expression in self.variables
        }
        parsed_outputs = [self._parse_expression(expression) for expression in self.outputs]
        self._validate_graph(parsed_variables, parsed_outputs)

        hasher = _ExpressionHasher()
        simplified_variables = {
            name: _simplify_expr_node(node, hasher) for name, node in parsed_variables.items()
        }
        simplified_outputs = [_simplify_expr_node(node, hasher) for node in parsed_outputs]
        variables, outputs = _extract_repeated_subexpressions(
            self.variables,
            simplified_variables,
            simplified_outputs,
        )
        simplified = Circuit(
            input_count=self.input_count,
            output_count=self.output_count,
            outputs=outputs,
            variables=variables,
        )
        simplified._ensure_compiled_graph()
        return simplified

    @classmethod
    def load(cls, path: str | Path) -> "Circuit":
        path = Path(path)
        data = path.read_bytes()
        if data.startswith(_BINARY_MAGIC):
            return cls.from_binary(data)
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise CircuitFormatError(
                "Circuit file is neither recognized binary format nor valid UTF-8 text"
            ) from exc
        return cls.from_text(text)

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

    @classmethod
    def from_binary(cls, data: bytes | bytearray | memoryview) -> "Circuit":
        reader = _BinaryReader(bytes(data))
        if reader.read_bytes(len(_BINARY_MAGIC)) != _BINARY_MAGIC:
            raise CircuitFormatError("Invalid binary circuit magic")
        version = reader.read_byte()
        if version != _BINARY_VERSION:
            raise CircuitFormatError(f"Unsupported binary circuit version: {version}")

        input_count = reader.read_varuint()
        output_count = reader.read_varuint()
        variable_count = reader.read_varuint()
        if input_count < 1:
            raise CircuitFormatError("INPUTS must be at least 1")
        if output_count < 1:
            raise CircuitFormatError("OUTPUTS must be at least 1")

        parsed_variables: Dict[str, _ExprNode] = {}
        variables: List[Tuple[str, str]] = []
        for _ in range(variable_count):
            variable_number = reader.read_varuint()
            name = f"V{variable_number}"
            if name in parsed_variables:
                raise CircuitFormatError(f"Duplicate variable definition: {name}")
            node = _read_expr_node(reader)
            parsed_variables[name] = node
            variables.append((name, _expr_node_to_text(node)))

        parsed_outputs = [_read_expr_node(reader) for _ in range(output_count)]
        reader.ensure_done()

        circuit = cls(
            input_count=input_count,
            output_count=output_count,
            outputs=[_expr_node_to_text(node) for node in parsed_outputs],
            variables=variables,
        )
        circuit._validate_graph(parsed_variables, parsed_outputs)
        circuit._compiled_graph = circuit._compile_graph(parsed_variables, parsed_outputs)
        return circuit

    def evaluate(
        self,
        inputs: Sequence[Any],
        targets: Sequence[str] | str | None = None,
    ) -> List[int]:
        if len(inputs) != self.input_count:
            raise CircuitError(
                f"Expected {self.input_count} input values, got {len(inputs)}"
            )
        graph = self._ensure_compiled_graph()
        target_nodes = (
            list(graph.output_nodes)
            if targets is None
            else self._resolve_evaluation_targets(targets, graph)
        )
        return _evaluate_compiled_nodes(target_nodes, graph, inputs)

    def _ensure_parsed_outputs(self) -> List[_ExprNode]:
        graph = self._ensure_compiled_graph()
        return list(graph.output_nodes)

    def _ensure_parsed_graph(self) -> Tuple[Dict[str, _ExprNode], List[_ExprNode]]:
        graph = self._ensure_compiled_graph()
        return (
            {name: graph.variable_nodes[index] for index, (name, _) in enumerate(self.variables)},
            list(graph.output_nodes),
        )

    def _ensure_compiled_graph(self) -> _CompiledGraph:
        if self._compiled_graph is None:
            parsed_variables = {
                name: self._parse_expression(expression) for name, expression in self.variables
            }
            parsed_outputs = [self._parse_expression(expression) for expression in self.outputs]
            self._validate_graph(parsed_variables, parsed_outputs)
            self._compiled_graph = self._compile_graph(parsed_variables, parsed_outputs)
        return self._compiled_graph

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
        graph = self._ensure_compiled_graph()
        return bool(_evaluate_compiled_nodes([node], graph, inputs)[0])

    def _resolve_evaluation_targets(
        self,
        targets: Sequence[str] | str,
        graph: _CompiledGraph,
    ) -> List[_ExprNode]:
        target_names = [targets] if isinstance(targets, str) else list(targets)
        variable_indices = {
            name: index for index, (name, _) in enumerate(self.variables)
        }
        target_nodes: List[_ExprNode] = []
        for target in target_names:
            normalized_target = str(target).upper()
            output_index = _parse_output_name(normalized_target)
            if output_index is not None:
                if output_index >= self.output_count:
                    raise CircuitError(
                        f"Target OUT{output_index} is outside OUTPUTS {self.output_count}"
                    )
                target_nodes.append(graph.output_nodes[output_index])
                continue

            if _is_variable_name(normalized_target):
                variable_index = variable_indices.get(normalized_target)
                if variable_index is None:
                    raise CircuitError(f"Target variable {normalized_target} is not defined")
                target_nodes.append(_ExprNode(op="VARIABLE", variable_index=variable_index))
                continue

            raise CircuitError(
                f"Unknown evaluation target '{target}'; expected OUT<number> or V<number>"
            )
        return target_nodes

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

    def _compile_graph(
        self,
        parsed_variables: Dict[str, _ExprNode],
        parsed_outputs: List[_ExprNode],
    ) -> _CompiledGraph:
        variable_indices = {
            name: index for index, (name, _) in enumerate(self.variables)
        }
        variable_nodes = [
            _resolve_variable_references(parsed_variables[name], variable_indices)
            for name, _ in self.variables
        ]
        output_nodes = [
            _resolve_variable_references(node, variable_indices)
            for node in parsed_outputs
        ]
        evaluation_order = _build_evaluation_order(parsed_variables, parsed_outputs, variable_indices)
        return _CompiledGraph(
            variable_nodes=tuple(variable_nodes),
            output_nodes=tuple(output_nodes),
            evaluation_order=tuple(evaluation_order),
        )

    def _validate_expression_references(
        self,
        node: _ExprNode,
        parsed_variables: Dict[str, _ExprNode],
        owner: str,
    ) -> None:
        for child in _iter_tree(node):
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
    variables: Mapping[str, str | bool] | Sequence[Tuple[str, str | bool]] | None,
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
        normalized_variables.append(
            (
                normalized_name,
                _normalize_expression(expression, f"Expression for {normalized_name}"),
            )
        )
        seen.add(normalized_name)
    return normalized_variables


def _normalize_expression(expression: str | bool, owner: str) -> str:
    if isinstance(expression, bool):
        return "True" if expression else "False"
    if not isinstance(expression, str) or not expression.strip():
        raise CircuitError(f"{owner} cannot be empty")
    return expression.strip()


def _constant_node(value: bool) -> _ExprNode:
    return _ExprNode(op="CONSTANT", constant_value=value)


def _not_node(node: _ExprNode) -> _ExprNode:
    return _ExprNode(op="NOT", args=(node,))


_ExprFingerprint = int
_ExprSignature = Tuple[Any, ...]


class _ExpressionHasher:
    COMMUTATIVE_OPS = {"AND", "OR", "XOR", "NAND", "NOR"}

    def __init__(self) -> None:
        self._cache: Dict[int, Tuple[_ExprNode, _ExprFingerprint]] = {}
        self._fingerprints: Dict[_ExprSignature, _ExprFingerprint] = {}
        self._next_fingerprint = 0

    def fingerprint(self, node: _ExprNode) -> _ExprFingerprint:
        node_id = id(node)
        cached = self._cache.get(node_id)
        if cached is not None and cached[0] is node:
            return cached[1]

        if node.op == "INPUT":
            signature = (node.op, node.input_index)
        elif node.op == "VARIABLE":
            signature = (node.op, node.variable_name, node.variable_index)
        elif node.op == "CONSTANT":
            signature = (node.op, node.constant_value)
        else:
            child_fingerprints = [self.fingerprint(child) for child in node.args]
            if node.op in self.COMMUTATIVE_OPS:
                child_fingerprints.sort()
            signature = (node.op, tuple(child_fingerprints))

        fingerprint = self._fingerprints.get(signature)
        if fingerprint is None:
            fingerprint = self._next_fingerprint
            self._next_fingerprint += 1
            self._fingerprints[signature] = fingerprint
        self._cache[node_id] = (node, fingerprint)
        return fingerprint


def _constant_value(node: _ExprNode) -> bool | None:
    return node.constant_value if node.op == "CONSTANT" else None


def _is_same_expr(left: _ExprNode, right: _ExprNode, hasher: _ExpressionHasher) -> bool:
    return hasher.fingerprint(left) == hasher.fingerprint(right)


def _is_not_of(node: _ExprNode, other: _ExprNode, hasher: _ExpressionHasher) -> bool:
    return (
        node.op == "NOT"
        and len(node.args) == 1
        and _is_same_expr(node.args[0], other, hasher)
    )


def _are_complements(left: _ExprNode, right: _ExprNode, hasher: _ExpressionHasher) -> bool:
    return _is_not_of(left, right, hasher) or _is_not_of(right, left, hasher)


def _evaluate_constant_operator(operator: str, values: Sequence[bool]) -> bool:
    if operator == "AND":
        return values[0] and values[1]
    if operator == "OR":
        return values[0] or values[1]
    if operator == "NOT":
        return not values[0]
    if operator == "XOR":
        return values[0] ^ values[1]
    if operator == "NAND":
        return not (values[0] and values[1])
    if operator == "NOR":
        return not (values[0] or values[1])
    raise CircuitError(f"Unsupported operator during simplification: {operator}")


def _simplify_expr_node(
    node: _ExprNode,
    hasher: _ExpressionHasher | None = None,
) -> _ExprNode:
    if hasher is None:
        hasher = _ExpressionHasher()
    if node.op in {"INPUT", "VARIABLE", "CONSTANT"}:
        return node

    args = tuple(_simplify_expr_node(child, hasher) for child in node.args)
    constant_values = [_constant_value(child) for child in args]
    if all(value is not None for value in constant_values):
        return _constant_node(
            _evaluate_constant_operator(node.op, [bool(value) for value in constant_values])
        )

    if node.op == "NOT":
        child = args[0]
        if child.op == "NOT":
            return child.args[0]
        return _ExprNode(op="NOT", args=(child,))

    left, right = args
    left_constant = _constant_value(left)
    right_constant = _constant_value(right)

    if node.op == "AND":
        if left_constant is False or right_constant is False:
            return _constant_node(False)
        if left_constant is True:
            return right
        if right_constant is True:
            return left
        if _is_same_expr(left, right, hasher):
            return left
        if _are_complements(left, right, hasher):
            return _constant_node(False)

    if node.op == "OR":
        if left_constant is True or right_constant is True:
            return _constant_node(True)
        if left_constant is False:
            return right
        if right_constant is False:
            return left
        if _is_same_expr(left, right, hasher):
            return left
        if _are_complements(left, right, hasher):
            return _constant_node(True)

    if node.op == "XOR":
        if left_constant is False:
            return right
        if right_constant is False:
            return left
        if left_constant is True:
            return _simplify_expr_node(_not_node(right), hasher)
        if right_constant is True:
            return _simplify_expr_node(_not_node(left), hasher)
        if _is_same_expr(left, right, hasher):
            return _constant_node(False)
        if _are_complements(left, right, hasher):
            return _constant_node(True)

    if node.op == "NAND":
        if left_constant is False or right_constant is False:
            return _constant_node(True)
        if left_constant is True:
            return _simplify_expr_node(_not_node(right), hasher)
        if right_constant is True:
            return _simplify_expr_node(_not_node(left), hasher)
        if _is_same_expr(left, right, hasher):
            return _simplify_expr_node(_not_node(left), hasher)
        if _are_complements(left, right, hasher):
            return _constant_node(True)

    if node.op == "NOR":
        if left_constant is True or right_constant is True:
            return _constant_node(False)
        if left_constant is False:
            return _simplify_expr_node(_not_node(right), hasher)
        if right_constant is False:
            return _simplify_expr_node(_not_node(left), hasher)
        if _is_same_expr(left, right, hasher):
            return _simplify_expr_node(_not_node(left), hasher)
        if _are_complements(left, right, hasher):
            return _constant_node(False)

    return _ExprNode(op=node.op, args=args)


def _is_extractable_subexpression(node: _ExprNode) -> bool:
    return node.op in Circuit.SUPPORTED_OPS


def _collect_subexpression_counts(
    node: _ExprNode,
    counts: Dict[_ExprFingerprint, int],
    examples: Dict[_ExprFingerprint, _ExprNode],
    hasher: _ExpressionHasher,
) -> None:
    if _is_extractable_subexpression(node):
        key = hasher.fingerprint(node)
        counts[key] = counts.get(key, 0) + 1
        examples.setdefault(key, node)
    for child in node.args:
        _collect_subexpression_counts(child, counts, examples, hasher)


def _extract_repeated_subexpressions(
    original_variables: Sequence[Tuple[str, str]],
    simplified_variables: Dict[str, _ExprNode],
    simplified_outputs: Sequence[_ExprNode],
) -> Tuple[List[Tuple[str, str]], List[str]]:
    hasher = _ExpressionHasher()
    counts: Dict[_ExprFingerprint, int] = {}
    examples: Dict[_ExprFingerprint, _ExprNode] = {}
    for name, _ in original_variables:
        _collect_subexpression_counts(simplified_variables[name], counts, examples, hasher)
    for node in simplified_outputs:
        _collect_subexpression_counts(node, counts, examples, hasher)

    replacements: Dict[_ExprFingerprint, str] = {}
    for name, _ in original_variables:
        node = simplified_variables[name]
        if _is_extractable_subexpression(node):
            replacements.setdefault(hasher.fingerprint(node), name)

    new_variable_nodes: List[Tuple[str, _ExprNode]] = []
    used_numbers = {_variable_number_from_name(name) for name, _ in original_variables}
    for key, count in counts.items():
        if count < 2 or key in replacements:
            continue
        name = _next_variable_name(used_numbers)
        replacements[key] = name
        new_variable_nodes.append((name, examples[key]))

    def replace(node: _ExprNode, protected_name: str | None = None) -> _ExprNode:
        key = hasher.fingerprint(node)
        replacement_name = replacements.get(key)
        if replacement_name is not None and replacement_name != protected_name:
            return _ExprNode(op="VARIABLE", variable_name=replacement_name)
        if not node.args:
            return node
        return _ExprNode(
            op=node.op,
            args=tuple(replace(child) for child in node.args),
            input_index=node.input_index,
            variable_name=node.variable_name,
            variable_index=node.variable_index,
            constant_value=node.constant_value,
        )

    variables: List[Tuple[str, str]] = []
    for name, _ in original_variables:
        node = simplified_variables[name]
        variables.append((name, _expr_node_to_text(replace(node, name))))
    for name, node in new_variable_nodes:
        variables.append((name, _expr_node_to_text(replace(node, name))))

    outputs = [_expr_node_to_text(replace(node)) for node in simplified_outputs]
    return variables, outputs


def _next_variable_name(used_numbers: set[int]) -> str:
    number = max(used_numbers, default=-1) + 1
    while number in used_numbers:
        number += 1
    used_numbers.add(number)
    return f"V{number}"


def _is_variable_name(name: str) -> bool:
    return len(name) > 1 and name.startswith("V") and name[1:].isdigit()


def _parse_output_name(name: str) -> int | None:
    if len(name) <= 3 or not name.startswith("OUT") or not name[3:].isdigit():
        return None
    return int(name[3:])


def _iter_tree(node: _ExprNode) -> Iterator[_ExprNode]:
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(reversed(current.args))


def _iter_variable_references(node: _ExprNode) -> List[str]:
    references: List[str] = []
    for child in _iter_tree(node):
        if child.op == "VARIABLE":
            assert child.variable_name is not None
            references.append(child.variable_name)
    return references


def _resolve_variable_references(
    node: _ExprNode,
    variable_indices: Dict[str, int],
) -> _ExprNode:
    if node.op == "VARIABLE":
        assert node.variable_name is not None
        return _ExprNode(op="VARIABLE", variable_index=variable_indices[node.variable_name])
    if not node.args:
        return node
    return _ExprNode(
        op=node.op,
        args=tuple(
            _resolve_variable_references(child, variable_indices) for child in node.args
        ),
        input_index=node.input_index,
        variable_name=node.variable_name,
        variable_index=node.variable_index,
        constant_value=node.constant_value,
    )


def _build_evaluation_order(
    parsed_variables: Dict[str, _ExprNode],
    parsed_outputs: List[_ExprNode],
    variable_indices: Dict[str, int],
) -> List[int]:
    order: List[int] = []
    visited: set[str] = set()

    def visit(name: str) -> None:
        if name in visited:
            return
        visited.add(name)
        for dependency in _iter_variable_references(parsed_variables[name]):
            visit(dependency)
        order.append(variable_indices[name])

    for output_node in parsed_outputs:
        for reference in _iter_variable_references(output_node):
            visit(reference)
    return order


def _evaluation_order_for_nodes(
    graph: _CompiledGraph,
    nodes: Sequence[_ExprNode],
) -> List[int]:
    order: List[int] = []
    visited: set[int] = set()

    def visit_node(node: _ExprNode) -> None:
        if node.op == "VARIABLE":
            assert node.variable_index is not None
            visit_variable(node.variable_index)
            return
        for child in node.args:
            visit_node(child)

    def visit_variable(variable_index: int) -> None:
        if variable_index in visited:
            return
        visited.add(variable_index)
        visit_node(graph.variable_nodes[variable_index])
        order.append(variable_index)

    for node in nodes:
        visit_node(node)
    return order


def _evaluate_compiled_nodes(
    nodes: Sequence[_ExprNode],
    graph: _CompiledGraph,
    inputs: Sequence[Any],
) -> List[int]:
    variable_values = [False for _ in graph.variable_nodes]
    for variable_index in _evaluation_order_for_nodes(graph, nodes):
        variable_values[variable_index] = _evaluate_compiled_tree(
            graph.variable_nodes[variable_index],
            inputs,
            variable_values,
        )
    return [
        int(_evaluate_compiled_tree(node, inputs, variable_values))
        for node in nodes
    ]


def _evaluate_compiled_tree(
    node: _ExprNode,
    inputs: Sequence[Any],
    variable_values: Sequence[bool],
) -> bool:
    if node.op == "INPUT":
        assert node.input_index is not None
        if node.input_index < 0 or node.input_index >= len(inputs):
            raise CircuitError(f"Input reference I{node.input_index} is out of range")
        return bool(inputs[node.input_index])
    if node.op == "VARIABLE":
        assert node.variable_index is not None
        return variable_values[node.variable_index]
    if node.op == "CONSTANT":
        assert node.constant_value is not None
        return node.constant_value

    values = [
        _evaluate_compiled_tree(child, inputs, variable_values) for child in node.args
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
            if token == "TRUE":
                return _ExprNode(op="CONSTANT", constant_value=True)
            if token == "FALSE":
                return _ExprNode(op="CONSTANT", constant_value=False)
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
            "Expression must begin with a boolean literal, input reference, "
            "variable reference, or operator"
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


def _variable_number_from_name(name: str) -> int:
    normalized_name = name.upper()
    if not _is_variable_name(normalized_name):
        raise CircuitFormatError(f"Invalid variable name: {name}")
    return int(normalized_name[1:])


def _write_expr_node(
    writer: "_BinaryWriter",
    node: _ExprNode,
    variables: Sequence[Tuple[str, str]],
) -> None:
    if node.op == "INPUT":
        assert node.input_index is not None
        writer.write_byte(_INPUT_OPCODE)
        writer.write_varuint(node.input_index)
        return
    if node.op == "VARIABLE":
        writer.write_byte(_VARIABLE_OPCODE)
        if node.variable_name is not None:
            writer.write_varuint(_variable_number_from_name(node.variable_name))
            return
        assert node.variable_index is not None
        writer.write_varuint(_variable_number_from_name(variables[node.variable_index][0]))
        return
    if node.op == "CONSTANT":
        assert node.constant_value is not None
        writer.write_byte(_TRUE_OPCODE if node.constant_value else _FALSE_OPCODE)
        return

    opcode = _OP_TO_OPCODE.get(node.op)
    if opcode is None:
        raise CircuitFormatError(f"Unsupported operator in binary writer: {node.op}")
    writer.write_byte(opcode)
    for child in node.args:
        _write_expr_node(writer, child, variables)


def _read_expr_node(reader: "_BinaryReader") -> _ExprNode:
    opcode = reader.read_byte()
    if opcode == _INPUT_OPCODE:
        return _ExprNode(op="INPUT", input_index=reader.read_varuint())
    if opcode == _VARIABLE_OPCODE:
        return _ExprNode(op="VARIABLE", variable_name=f"V{reader.read_varuint()}")
    if opcode == _FALSE_OPCODE:
        return _ExprNode(op="CONSTANT", constant_value=False)
    if opcode == _TRUE_OPCODE:
        return _ExprNode(op="CONSTANT", constant_value=True)

    op = _OPCODE_TO_OP.get(opcode)
    if op is None:
        raise CircuitFormatError(f"Unknown binary expression opcode: 0x{opcode:02x}")
    arity = Circuit.SUPPORTED_OPS[op]
    return _ExprNode(
        op=op,
        args=tuple(_read_expr_node(reader) for _ in range(arity)),
    )


def _expr_node_to_text(node: _ExprNode) -> str:
    if node.op == "INPUT":
        assert node.input_index is not None
        return f"I{node.input_index}"
    if node.op == "VARIABLE":
        if node.variable_name is not None:
            return node.variable_name
        assert node.variable_index is not None
        return f"V{node.variable_index}"
    if node.op == "CONSTANT":
        assert node.constant_value is not None
        return "True" if node.constant_value else "False"

    if node.op not in Circuit.SUPPORTED_OPS:
        raise CircuitFormatError(f"Unsupported operator in binary expression: {node.op}")
    return f"{node.op}({', '.join(_expr_node_to_text(child) for child in node.args)})"


class _BinaryWriter:
    def __init__(self) -> None:
        self._buffer = bytearray()

    def write_byte(self, value: int) -> None:
        if value < 0 or value > 0xFF:
            raise CircuitFormatError(f"Byte value out of range: {value}")
        self._buffer.append(value)

    def write_bytes(self, data: bytes) -> None:
        self._buffer.extend(data)

    def write_varuint(self, value: int) -> None:
        if value < 0:
            raise CircuitFormatError(f"varuint cannot encode negative value: {value}")
        while value >= 0x80:
            self._buffer.append((value & 0x7F) | 0x80)
            value >>= 7
        self._buffer.append(value)

    def to_bytes(self) -> bytes:
        return bytes(self._buffer)


class _BinaryReader:
    def __init__(self, data: bytes) -> None:
        self._data = data
        self._pos = 0

    def read_byte(self) -> int:
        if self._pos >= len(self._data):
            raise CircuitFormatError("Unexpected end of binary circuit data")
        value = self._data[self._pos]
        self._pos += 1
        return value

    def read_bytes(self, count: int) -> bytes:
        if count < 0:
            raise CircuitFormatError("Cannot read a negative byte count")
        end = self._pos + count
        if end > len(self._data):
            raise CircuitFormatError("Unexpected end of binary circuit data")
        value = self._data[self._pos : end]
        self._pos = end
        return value

    def read_varuint(self) -> int:
        shift = 0
        value = 0
        for _ in range(_MAX_VARUINT_BYTES):
            byte = self.read_byte()
            value |= (byte & 0x7F) << shift
            if byte < 0x80:
                return value
            shift += 7
        raise CircuitFormatError("Binary varuint is too long")

    def ensure_done(self) -> None:
        if self._pos != len(self._data):
            raise CircuitFormatError("Trailing bytes after binary circuit data")
