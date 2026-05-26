# circuit-static-description
A text-based boolean gate circuit description format that is easy to save and port.

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

### Circuit description format

A circuit description contains the number of inputs, the number of outputs, optional intermediate variables, and the expression for each output.

- Input references use `I0`, `I1`, `I2`, etc.
- Intermediate variables use `V0`, `V1`, `V2`, etc. Only `V` followed by an integer is accepted as a variable name.
- Variable definitions use `V<number> = expression` and may reference inputs and earlier or later variables.
- Output lines use fixed names `OUT0`, `OUT1`, etc.
- Output definitions may reference inputs, variables, and supported logic operators.
- Supported logic operators: `AND`, `OR`, `NOT`, `XOR`, `NAND`, `NOR`.
- Circular variable dependencies and undefined variable references are rejected when the circuit is loaded or parsed.

Example:

```text
INPUTS 3
OUTPUTS 2
V0 = AND(I0, I1)
V1 = XOR(V0, I2)
OUT0 = V0
OUT1 = NOR(I2, V1)
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

circuit.save("example.circuit")
```

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

### Notes

- `evaluate` accepts a list of input values in input order.
- The output is returned as a list of `0` or `1` values.
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
