import unittest
import sys
import time
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

    def test_boolean_literals_work_in_all_expression_positions(self) -> None:
        circuit = Circuit.from_text(
            """
            INPUTS 1
            OUTPUTS 4
            V0 = True
            V1 = false
            OUT0 = V0
            OUT1 = V1
            OUT2 = AND(TRUE, I0)
            OUT3 = OR(False, I0)
            """
        )

        self.assertEqual(circuit.evaluate([0]), [1, 0, 0, 0])
        self.assertEqual(circuit.evaluate([1]), [1, 0, 1, 1])
        self.assertEqual(circuit.evaluate([1], targets=["V0", "V1"]), [1, 0])

    def test_constructor_accepts_boolean_literals(self) -> None:
        circuit = Circuit(
            input_count=1,
            output_count=3,
            variables={"V0": False},
            outputs=[True, "V0", "XOR(True, I0)"],
        )

        self.assertEqual(
            circuit.to_text(),
            "INPUTS 1\nOUTPUTS 3\nV0 = False\nOUT0 = True\n"
            "OUT1 = V0\nOUT2 = XOR(True, I0)\n",
        )
        self.assertEqual(circuit.evaluate([0]), [1, 0, 1])
        self.assertEqual(circuit.evaluate([1]), [1, 0, 0])

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

    def test_count_accessors_report_inputs_outputs_and_logic_gates(self) -> None:
        circuit = Circuit(
            input_count=3,
            output_count=3,
            variables=[
                ("V0", "AND(I0, I1)"),
                ("V1", "XOR(V0, NOT(I2))"),
                ("V2", "True"),
            ],
            outputs=[
                "V1",
                "NOR(I2, V0)",
                "I0",
            ],
        )

        self.assertEqual(circuit.get_input_count(), 3)
        self.assertEqual(circuit.get_output_count(), 3)
        self.assertEqual(circuit.get_gate_count(), 4)

    def test_gate_count_is_preserved_after_binary_round_trip(self) -> None:
        circuit = Circuit.from_text(
            """
            INPUTS 2
            OUTPUTS 2
            V0 = NAND(I0, I1)
            OUT0 = V0
            OUT1 = OR(V0, NOT(I1))
            """
        )

        loaded = Circuit.from_binary(circuit.to_binary())

        self.assertEqual(loaded.get_input_count(), 2)
        self.assertEqual(loaded.get_output_count(), 2)
        self.assertEqual(loaded.get_gate_count(), 3)

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


class CircuitSimplifyTests(unittest.TestCase):
    @staticmethod
    def _make_balanced_expression(depth: int, offset: int = 0) -> str:
        if depth == 0:
            return f"I{offset % 8}"
        left = CircuitSimplifyTests._make_balanced_expression(depth - 1, offset)
        right = CircuitSimplifyTests._make_balanced_expression(depth - 1, offset + 1)
        operator = ["AND", "OR", "XOR", "NAND"][depth % 4]
        return f"{operator}({left}, {right})"

    def test_simplify_folds_constants_and_boolean_identities(self) -> None:
        circuit = Circuit(
            input_count=2,
            output_count=8,
            outputs=[
                "AND(True, I0)",
                "AND(False, I0)",
                "OR(False, I1)",
                "OR(True, I1)",
                "XOR(True, I0)",
                "XOR(False, I1)",
                "NAND(True, I0)",
                "NOR(False, I1)",
            ],
        )

        simplified = circuit.simplify()

        self.assertEqual(
            simplified.to_text(),
            "INPUTS 2\nOUTPUTS 8\nV0 = NOT(I0)\nOUT0 = I0\nOUT1 = False\n"
            "OUT2 = I1\nOUT3 = True\nOUT4 = V0\nOUT5 = I1\nOUT6 = V0\n"
            "OUT7 = NOT(I1)\n",
        )
        for left in [0, 1]:
            for right in [0, 1]:
                inputs = [left, right]
                self.assertEqual(simplified.evaluate(inputs), circuit.evaluate(inputs))

    def test_simplify_evaluates_all_constant_subtrees(self) -> None:
        circuit = Circuit(
            input_count=1,
            output_count=2,
            outputs=[
                "AND(OR(True, False), NOT(False))",
                "XOR(NAND(True, True), NOR(False, False))",
            ],
        )

        simplified = circuit.simplify()

        self.assertEqual(
            simplified.to_text(),
            "INPUTS 1\nOUTPUTS 2\nOUT0 = True\nOUT1 = True\n",
        )
        self.assertEqual(simplified.evaluate([0]), circuit.evaluate([0]))

    def test_simplify_propagates_constant_variables_without_removing_them(self) -> None:
        circuit = Circuit.from_text(
            """
            INPUTS 1
            OUTPUTS 3
            V0 = True
            V2 = AND(V0, I0)
            V5 = OR(False, V0)
            OUT0 = AND(V0, I0)
            OUT1 = NAND(V5, I0)
            OUT2 = V2
            """
        )

        simplified = circuit.simplify()

        self.assertEqual(
            simplified.to_text(),
            "INPUTS 1\nOUTPUTS 3\nV0 = True\nV2 = I0\nV5 = True\n"
            "OUT0 = I0\nOUT1 = NOT(I0)\nOUT2 = V2\n",
        )
        self.assertEqual([name for name, _ in simplified.variables], ["V0", "V2", "V5"])
        for value in [0, 1]:
            self.assertEqual(simplified.evaluate([value]), circuit.evaluate([value]))

    def test_simplify_propagates_later_constant_variable_references(self) -> None:
        circuit = Circuit.from_text(
            """
            INPUTS 1
            OUTPUTS 1
            V3 = AND(V7, I0)
            V7 = True
            OUT0 = V3
            """
        )

        simplified = circuit.simplify()

        self.assertEqual(
            simplified.to_text(),
            "INPUTS 1\nOUTPUTS 1\nV3 = I0\nV7 = True\nOUT0 = V3\n",
        )
        self.assertEqual([name for name, _ in simplified.variables], ["V3", "V7"])
        for value in [0, 1]:
            self.assertEqual(simplified.evaluate([value]), circuit.evaluate([value]))

    def test_simplify_extracts_repeated_subexpressions_to_new_variables(self) -> None:
        circuit = Circuit(
            input_count=2,
            output_count=2,
            variables=[("V0", "I0")],
            outputs=[
                "XOR(AND(I0, I1), I0)",
                "NAND(AND(I0, I1), I1)",
            ],
        )

        simplified = circuit.simplify()

        self.assertEqual(
            simplified.to_text(),
            "INPUTS 2\nOUTPUTS 2\nV0 = I0\nV1 = AND(I0, I1)\n"
            "OUT0 = XOR(V1, I0)\nOUT1 = NAND(V1, I1)\n",
        )
        for left in [0, 1]:
            for right in [0, 1]:
                inputs = [left, right]
                self.assertEqual(simplified.evaluate(inputs), circuit.evaluate(inputs))

    def test_simplify_hashes_commutative_subexpressions_canonically(self) -> None:
        circuit = Circuit(
            input_count=2,
            output_count=2,
            outputs=[
                "XOR(AND(I0, I1), I0)",
                "NAND(AND(I1, I0), I1)",
            ],
        )

        simplified = circuit.simplify()

        self.assertEqual(
            simplified.to_text(),
            "INPUTS 2\nOUTPUTS 2\nV0 = AND(I0, I1)\n"
            "OUT0 = XOR(V0, I0)\nOUT1 = NAND(V0, I1)\n",
        )

    def test_simplify_large_repeated_circuit_finishes_quickly(self) -> None:
        shared = self._make_balanced_expression(depth=6)
        outputs = []
        for index in range(150):
            outputs.append(f"XOR({shared}, I{index % 8})")
            outputs.append(f"NAND({shared}, I{(index + 1) % 8})")
        circuit = Circuit(input_count=8, output_count=len(outputs), outputs=outputs)

        start = time.perf_counter()
        simplified = circuit.simplify()
        elapsed = time.perf_counter() - start

        self.assertLess(
            elapsed,
            4.0,
            f"simplifying a large repeated circuit took {elapsed:.3f}s",
        )
        self.assertLess(len(simplified.variables), len(outputs))
        inputs = [1, 0, 1, 1, 0, 1, 0, 1]
        self.assertEqual(simplified.evaluate(inputs)[:8], circuit.evaluate(inputs)[:8])

    def test_simplify_reuses_old_variable_without_renumbering(self) -> None:
        circuit = Circuit(
            input_count=2,
            output_count=2,
            variables=[
                ("V3", "AND(I0, I1)"),
            ],
            outputs=[
                "XOR(AND(I0, I1), I0)",
                "NAND(AND(I0, I1), I1)",
            ],
        )

        simplified = circuit.simplify()

        self.assertEqual(
            simplified.to_text(),
            "INPUTS 2\nOUTPUTS 2\nV3 = AND(I0, I1)\n"
            "OUT0 = XOR(V3, I0)\nOUT1 = NAND(V3, I1)\n",
        )
        self.assertEqual(simplified.evaluate([1, 1], targets="V3"), [1])

    def test_simplify_can_reuse_duplicate_old_variable_expressions(self) -> None:
        circuit = Circuit(
            input_count=2,
            output_count=1,
            variables=[
                ("V0", "AND(I0, I1)"),
                ("V2", "AND(I0, I1)"),
            ],
            outputs=["V2"],
        )

        simplified = circuit.simplify()

        self.assertEqual(
            simplified.to_text(),
            "INPUTS 2\nOUTPUTS 1\nV0 = AND(I0, I1)\nV2 = V0\nOUT0 = V2\n",
        )
        self.assertEqual(simplified.evaluate([1, 1], targets=["V0", "V2", "OUT0"]), [1, 1, 1])

    def test_save_simplifies_by_default_and_can_be_disabled(self) -> None:
        circuit = Circuit(
            input_count=2,
            output_count=1,
            outputs=["AND(True, AND(I0, I1))"],
        )
        temp_dir = Path(__file__).resolve().parent
        simplified_path = temp_dir / "_tmp_simplified.circuit"
        raw_path = temp_dir / "_tmp_raw.circuit"
        try:
            circuit.save(simplified_path, mode="text")
            circuit.save(raw_path, mode="text", simplify=False)

            self.assertIn("OUT0 = AND(I0, I1)", simplified_path.read_text("utf-8"))
            self.assertIn(
                "OUT0 = AND(True, AND(I0, I1))",
                raw_path.read_text("utf-8"),
            )
        finally:
            simplified_path.unlink(missing_ok=True)
            raw_path.unlink(missing_ok=True)


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

    def test_binary_round_trip_preserves_boolean_literals(self) -> None:
        circuit = Circuit(
            input_count=1,
            output_count=3,
            variables=[
                ("V0", "True"),
                ("V1", "False"),
            ],
            outputs=[
                "V0",
                "V1",
                "AND(True, I0)",
            ],
        )

        loaded = Circuit.from_binary(circuit.to_binary())

        self.assertEqual(loaded.to_text(), circuit.to_text())
        self.assertEqual(loaded.evaluate([0]), [1, 0, 0])
        self.assertEqual(loaded.evaluate([1]), [1, 0, 1])

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
