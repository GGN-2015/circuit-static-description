"""Benchmark sequential circuit evaluation using random gates."""

import argparse
import random
import sys
import time
from pathlib import Path
from typing import List

from tqdm import tqdm

root_dir = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root_dir))

from circuit_static_description import Circuit

SUPPORTED_OPS = ["AND", "OR", "XOR", "NAND", "NOR"]

def random_expression(input_count: int, depth: int) -> str:
    if depth <= 0 or random.random() < 0.2:
        return f"I{random.randrange(input_count)}"
    op = random.choice(SUPPORTED_OPS + ["NOT"])
    if op == "NOT":
        return f"NOT({random_expression(input_count, depth - 1)})"
    left = random_expression(input_count, depth - 1)
    right = random_expression(input_count, depth - 1)
    return f"{op}({left}, {right})"


def build_random_circuit(input_count: int, output_count: int, depth: int) -> Circuit:
    outputs = [random_expression(input_count, depth) for _ in range(output_count)]
    return Circuit(input_count=input_count, output_count=output_count, outputs=outputs)


def benchmark(circuit: Circuit, inputs: List[List[int]], show_progress: bool = True) -> float:
    circuit.evaluate(inputs[0])
    start = time.perf_counter()
    for vector in tqdm(inputs, desc="Sequential", unit="run", disable=not show_progress, file=sys.stdout):
        circuit.evaluate(vector)
    end = time.perf_counter()
    return end - start


def estimate_rounds(
    circuit: Circuit,
    inputs: List[List[int]],
    target_seconds: float = 240.0,
    show_progress: bool = True,
) -> int:
    sample_size = max(5, min(20, len(inputs)))
    sample_inputs = inputs[:sample_size]
    seq_time = benchmark(circuit, sample_inputs, show_progress=show_progress)
    if seq_time <= 0:
        return 100
    estimated = int(target_seconds / (seq_time / sample_size))
    return max(20, min(1000, estimated))


def run_benchmark(
    input_count: int = 16,
    output_count: int = 128,
    depth: int = 6,
    rounds: int = 120,
    target_seconds: float = 240.0,
    quick: bool = False,
    show_progress: bool = True,
) -> None:
    random.seed(0)
    if quick:
        rounds = min(rounds, 30)
        target_seconds = 60.0

    circuit = build_random_circuit(input_count, output_count, depth)
    inputs = [[random.randint(0, 1) for _ in range(input_count)] for _ in range(rounds)]

    print("Calibrating benchmark workload...", flush=True)
    estimated_rounds = estimate_rounds(
        circuit,
        inputs,
        target_seconds=target_seconds,
        show_progress=show_progress,
    )

    if estimated_rounds != rounds:
        print(f"Estimated round count: {estimated_rounds}", flush=True)

    if estimated_rounds < rounds:
        inputs = inputs[:estimated_rounds]
    elif estimated_rounds > rounds:
        extra = [[random.randint(0, 1) for _ in range(input_count)] for _ in range(estimated_rounds - rounds)]
        inputs.extend(extra)

    print(f"Circuit benchmark", flush=True)
    print(f"Input count: {input_count}, output count: {output_count}, depth: {depth}", flush=True)
    print(f"Rounds: {len(inputs)}", flush=True)

    seq_time = benchmark(circuit, inputs, show_progress=show_progress)

    print(f"Sequential time: {seq_time:.4f}s", flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark circuit evaluation performance.")
    parser.add_argument("--input-count", type=int, default=16)
    parser.add_argument("--output-count", type=int, default=128)
    parser.add_argument("--depth", type=int, default=6)
    parser.add_argument("--rounds", type=int, default=120)
    parser.add_argument("--target-seconds", type=float, default=240.0)
    parser.add_argument("--quick", action="store_true", help="Run a smaller quick benchmark.")
    parser.add_argument("--no-progress", action="store_true", help="Disable tqdm progress bars.")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run_benchmark(
        input_count=args.input_count,
        output_count=args.output_count,
        depth=args.depth,
        rounds=args.rounds,
        target_seconds=args.target_seconds,
        quick=args.quick,
        show_progress=not args.no_progress,
    )
