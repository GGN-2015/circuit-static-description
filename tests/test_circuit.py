import unittest
import sys
from pathlib import Path

root_dir = Path(__file__).resolve().parents[1]
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from circuit_static_description import Circuit, CircuitError, CircuitFormatError


class CircuitVariableTests(unittest.TestCase):
    def test_evaluates_variables_and_outputs(self) -> None:
        circuit = Circuit.from_text(
            """
            INPUTS 3
            OUTPUTS 2
            V0 = AND(I0, I1)
            V1 = XOR(V0, I2)
            OUT0 = V0
            OUT1 = NOR(I2, V1)
            """
        )

        self.assertEqual(circuit.evaluate([1, 1, 0]), [1, 0])
        self.assertEqual(circuit.evaluate([1, 0, 0]), [0, 1])

    def test_constructor_accepts_variables(self) -> None:
        circuit = Circuit(
            input_count=2,
            output_count=1,
            variables={"V0": "XOR(I0, I1)"},
            outputs=["NOT(V0)"],
        )

        self.assertEqual(circuit.evaluate([1, 0]), [0])
        self.assertEqual(
            circuit.to_text(),
            "INPUTS 2\nOUTPUTS 1\nV0 = XOR(I0, I1)\nOUT0 = NOT(V0)\n",
        )

    def test_legacy_output_only_format_still_loads(self) -> None:
        circuit = Circuit.from_text(
            """
            INPUTS 2
            OUTPUTS 1
            OUT0 = XOR(I0, I1)
            """
        )

        self.assertEqual(circuit.evaluate([1, 0]), [1])

    def test_evaluate_reuses_compiled_graph_after_first_parse(self) -> None:
        circuit = Circuit(
            input_count=2,
            output_count=1,
            variables={"V0": "XOR(I0, I1)"},
            outputs=["NOT(V0)"],
        )
        parse_count = 0
        original_parse_expression = circuit._parse_expression

        def count_parse_expression(text: str):
            nonlocal parse_count
            parse_count += 1
            return original_parse_expression(text)

        circuit._parse_expression = count_parse_expression

        self.assertEqual(circuit.evaluate([1, 0]), [0])
        self.assertEqual(circuit.evaluate([0, 0]), [1])
        self.assertEqual(parse_count, 2)

    def test_compiled_graph_evaluates_only_output_dependencies(self) -> None:
        circuit = Circuit(
            input_count=2,
            output_count=1,
            variables=[
                ("V0", "I0"),
                ("V1", "I1"),
                ("V2", "AND(V0, V1)"),
            ],
            outputs=["V2"],
        )
        graph = circuit._ensure_compiled_graph()

        self.assertEqual(graph.evaluation_order, (0, 1, 2))

        circuit = Circuit(
            input_count=2,
            output_count=1,
            variables=[
                ("V0", "I0"),
                ("V1", "I1"),
            ],
            outputs=["V0"],
        )
        graph = circuit._ensure_compiled_graph()

        self.assertEqual(graph.evaluation_order, (0,))

    def test_rejects_non_numeric_variable_name(self) -> None:
        with self.assertRaises(CircuitFormatError):
            Circuit.from_text(
                """
                INPUTS 1
                OUTPUTS 1
                TEMP = I0
                OUT0 = TEMP
                """
            )

    def test_rejects_undefined_variable_reference(self) -> None:
        with self.assertRaisesRegex(CircuitFormatError, "undefined variable V1"):
            Circuit.from_text(
                """
                INPUTS 1
                OUTPUTS 1
                V0 = V1
                OUT0 = V0
                """
            )

    def test_rejects_circular_variable_dependency(self) -> None:
        with self.assertRaisesRegex(CircuitFormatError, "Circular variable dependency"):
            Circuit.from_text(
                """
                INPUTS 1
                OUTPUTS 1
                V0 = V1
                V1 = V0
                OUT0 = V0
                """
            )

    def test_rejects_duplicate_variable_definition(self) -> None:
        with self.assertRaisesRegex(CircuitFormatError, "Duplicate variable definition: V0"):
            Circuit.from_text(
                """
                INPUTS 1
                OUTPUTS 1
                V0 = I0
                V0 = NOT(I0)
                OUT0 = V0
                """
            )

    def test_rejects_invalid_constructor_variable_name(self) -> None:
        with self.assertRaisesRegex(CircuitError, "Invalid variable name"):
            Circuit(input_count=1, output_count=1, variables={"A0": "I0"}, outputs=["I0"])


if __name__ == "__main__":
    unittest.main()
