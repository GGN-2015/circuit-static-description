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

    def test_text_format_allows_full_line_and_trailing_comments(self) -> None:
        circuit = Circuit.from_text(
            """
            # Comments may appear on their own line.
            INPUTS 2  # input width
            OUTPUTS 1
            V0 = AND(I0, I1)  # intermediate value
            OUT0 = NOT(V0)
            """
        )

        self.assertEqual(circuit.evaluate([1, 1]), [0])

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

    def test_evaluate_can_return_intermediate_variable_values(self) -> None:
        circuit = Circuit(
            input_count=3,
            output_count=2,
            variables=[
                ("V0", "AND(I0, I1)"),
                ("V1", "XOR(V0, I2)"),
            ],
            outputs=["V1", "NOR(I2, V0)"],
        )

        self.assertEqual(circuit.evaluate([1, 1, 0], targets="V0"), [1])
        self.assertEqual(circuit.evaluate([1, 1, 0], targets=["V1", "OUT1", "OUT0"]), [1, 0, 1])

    def test_evaluate_rejects_unknown_target(self) -> None:
        circuit = Circuit(input_count=1, output_count=1, outputs=["I0"])

        with self.assertRaisesRegex(CircuitError, "Target variable V0 is not defined"):
            circuit.evaluate([1], targets=["V0"])

        with self.assertRaisesRegex(CircuitError, "Unknown evaluation target"):
            circuit.evaluate([1], targets=["TEMP"])

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


class CircuitBinaryFormatTests(unittest.TestCase):
    def test_binary_round_trip_preserves_behavior_and_text_shape(self) -> None:
        circuit = Circuit(
            input_count=3,
            output_count=2,
            variables=[
                ("V3", "AND(I0, I1)"),
                ("V1", "XOR(V3, I2)"),
            ],
            outputs=[
                "V1",
                "NOR(I2, V3)",
            ],
        )

        data = circuit.to_binary()
        loaded = Circuit.from_binary(data)

        self.assertTrue(data.startswith(b"CSDCIR\x00"))
        self.assertEqual(loaded.to_text(), circuit.to_text())
        self.assertEqual(loaded.evaluate([1, 1, 0]), circuit.evaluate([1, 1, 0]))
        self.assertEqual(loaded.evaluate([1, 0, 1]), circuit.evaluate([1, 0, 1]))
        self.assertEqual(loaded.evaluate([1, 1, 0], targets=["V3", "V1"]), [1, 1])

    def test_load_auto_detects_binary_or_text_files(self) -> None:
        circuit = Circuit(
            input_count=2,
            output_count=1,
            variables={"V0": "XOR(I0, I1)"},
            outputs=["NOT(V0)"],
        )
        temp_dir = Path(__file__).resolve().parent
        binary_path = temp_dir / "_tmp_binary.circuit"
        text_path = temp_dir / "_tmp_text.circuit"
        try:
            circuit.save(binary_path)
            circuit.save(text_path, mode="text")

            self.assertEqual(Circuit.load(binary_path).evaluate([1, 0]), [0])
            self.assertEqual(Circuit.load(text_path).evaluate([1, 0]), [0])
            self.assertTrue(binary_path.read_bytes().startswith(b"CSDCIR\x00"))
            self.assertTrue(text_path.read_text(encoding="utf-8").startswith("INPUTS 2"))
        finally:
            binary_path.unlink(missing_ok=True)
            text_path.unlink(missing_ok=True)

    def test_save_rejects_unknown_mode(self) -> None:
        circuit = Circuit(input_count=1, output_count=1, outputs=["I0"])

        with self.assertRaisesRegex(CircuitError, "mode must be"):
            circuit.save(Path(__file__).resolve().parent / "_tmp_bad.circuit", mode="json")

    def test_from_binary_rejects_corrupt_data(self) -> None:
        with self.assertRaisesRegex(CircuitFormatError, "Unexpected end"):
            Circuit.from_binary(b"CSDCIR\x00\x01\x01")

    def test_load_rejects_unknown_non_utf8_file(self) -> None:
        path = Path(__file__).resolve().parent / "_tmp_unknown.circuit"
        try:
            path.write_bytes(b"\xff\xfe\xfd")
            with self.assertRaisesRegex(CircuitFormatError, "neither recognized binary"):
                Circuit.load(path)
        finally:
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
