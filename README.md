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

A circuit description contains only the number of inputs, the number of outputs, and the expression for each output. There are no intermediate variable names.

- Input references use `I0`, `I1`, `I2`, etc.
- Output lines use fixed names `OUT0`, `OUT1`, etc.
- Supported logic operators: `AND`, `OR`, `NOT`, `XOR`, `NAND`, `NOR`.

Example:

```text
INPUTS 3
OUTPUTS 2
OUT0 = AND(I0, I1)
OUT1 = NOR(I2, XOR(I0, I1))
```

### Saving a circuit

```python
from circuit_static_description import Circuit

circuit = Circuit(
    input_count=3,
    output_count=2,
    outputs=[
        "AND(I0, I1)",
        "NOR(I2, XOR(I0, I1))",
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
- Expressions cannot use custom variable names; they must use `I*` input references and supported logic operators.