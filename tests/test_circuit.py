import unittest

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
