"""Circuit static description Python package."""

from .circuit import Circuit, CircuitError, CircuitFormatError

__all__ = ["Circuit", "CircuitError", "CircuitFormatError"]


def main() -> None:
    """Simple package entry point for basic verification."""
    print("circuit_static_description package is available")
