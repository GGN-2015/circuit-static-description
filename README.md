# circuit-static-description
A boolean gate circuit description package with compact binary files and a readable legacy text format.

## Installation

Install from PyPI:

```bash
pip install circuit-static-description
```

## Python package usage

This project provides a Python package named `circuit_static_description`. The package supports saving circuits, loading circuits, and evaluating outputs.

### Importing

```python
from circuit_static_description import Circuit
```

### Circuit file formats

Circuit files can be saved in two formats:

- Binary format, the default for `Circuit.save(...)`. It stores the parsed expression tree using a compact opcode and varuint encoding, so loading avoids reparsing text expressions.
- Text format, kept for compatibility and readability. Old text files continue to load normally.

`Circuit.load(...)` automatically detects binary files by their file header. If the header is not present, it reads the file as UTF-8 text.

The text description contains the number of inputs, the number of outputs, optional intermediate variables, and the expression for each output.

- Text comments start with `#`. The parser ignores everything from `#` to the end of the line, so comments may appear on their own line or after a definition.
- Input references use `I0`, `I1`, `I2`, etc.
- Intermediate variables use `V0`, `V1`, `V2`, etc. Only `V` followed by an integer is accepted as a variable name.
- Variable definitions use `V<number> = expression` and may reference inputs and earlier or later variables.
- Output lines use fixed names `OUT0`, `OUT1`, etc.
- Output definitions may reference inputs, variables, and supported logic operators.
- Boolean literals `True` and `False` are accepted anywhere an expression is accepted. Literal parsing is case-insensitive.
- Supported logic operators: `AND`, `OR`, `NOT`, `XOR`, `NAND`, `NOR`.
- Circular variable dependencies and undefined variable references are rejected when the circuit is loaded or parsed.

Example:

```text
# This is a readable text circuit file.
INPUTS 3
OUTPUTS 2
V0 = AND(I0, I1)
V1 = XOR(V0, I2)
OUT0 = V0
OUT1 = NOR(False, V1)  # trailing comments are allowed
```

### Saving a circuit

```python
from circuit_static_description import Circuit

circuit = Circuit(
    input_count=3,
    output_count=2,
    variables=[
        ("V0", "AND(I0, I1)"),
        ("V1", "XOR(V0, I2)"),
    ],
    outputs=[
        "V0",
        "NOR(I2, V1)",
    ],
)

circuit.save("example.circuit")  # binary by default
circuit.save("example-text.circuit", mode="text")
circuit.save("example-binary.circuit", mode="binary")
```

`save(...)` simplifies the circuit before writing by default. Pass `simplify=False` to preserve the original expression text:

```python
circuit.save("example-text.circuit", mode="text", simplify=False)
```

You can also simplify manually. `simplify()` returns a new `Circuit` and leaves the original object unchanged.

```python
simplified = circuit.simplify()
```

Simplification folds constant-only logic, applies boolean identities such as `AND(True, X) = X` and `XOR(True, X) = NOT(X)`, propagates constant intermediate variables through the circuit, and extracts repeated gate expressions into new intermediate variables. Existing inputs, outputs, and variable names keep their original numbering.

### Loading a circuit

```python
from circuit_static_description import Circuit

circuit = Circuit.load("example.circuit")
```

### Evaluating a circuit

```python
result = circuit.evaluate([1, 0, 1])
print(result)
# Example output: [0, 0]
```

By default, `evaluate(...)` returns all declared outputs in `OUT0`, `OUT1`, ... order. You can also request specific outputs or intermediate variables with `targets`:

```python
values = circuit.evaluate([1, 0, 1], targets=["V0", "OUT1"])
print(values)
# Example output: [0, 0]
```

`targets` accepts either one name such as `"V0"` or a list of names such as `["OUT0", "V1"]`. Target names must be `OUT<number>` or `V<number>`, and results are returned in the same order as requested.

### Querying circuit size

```python
input_count = circuit.get_input_count()
output_count = circuit.get_output_count()
gate_count = circuit.get_gate_count()
```

`get_gate_count()` returns the number of supported logic operator nodes (`AND`, `OR`, `NOT`, `XOR`, `NAND`, `NOR`) declared in variable definitions and output expressions. Input references, variable references, and boolean literals are not counted as gates.

### Notes

- `evaluate` accepts a list of input values in input order.
- The output is returned as a list of `0` or `1` values.
- Intermediate variables can be read with `evaluate(inputs, targets="V0")` or mixed with outputs using `targets=["OUT0", "V1"]`.
- Custom variable names are not supported. Intermediate variables must be named `V0`, `V1`, `V2`, etc.
- Old files without variable definitions still load normally.

## Benchmarking sequential evaluation

The repository includes a local benchmark script in `tests/benchmark.py` for measuring sequential `Circuit.evaluate(...)` performance on random circuits.

The benchmark script uses `tqdm` to show progress while running evaluation loops.

Run the benchmark from the project root with the Poetry environment active:

```bash
python tests/benchmark.py
```

For a shorter run, use the quick mode:

```bash
python tests/benchmark.py --quick
```

This script is for local testing only and is not included in the published PyPI package.

### Benchmark details

- `tests/benchmark.py` generates a random circuit with input size, output size, and depth.
- It performs a small calibration run first to choose a comfortable workload that should finish in under 5 minutes.
- It reports the sequential evaluation time for the generated circuit.

### Example output

```text
Circuit benchmark
Input count: 16, output count: 128, depth: 6
Rounds: 200
Sequential time: 2.1234s
```
