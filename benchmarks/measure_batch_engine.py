from __future__ import annotations

import argparse
import json
import platform
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

from pocketrocks.sim import BatchSimEngine

try:
    import resource
except ImportError:  # pragma: no cover - unavailable on Windows
    resource = None  # type: ignore[assignment]


def run_episode(batch_size: int, seed_offset: int) -> None:
    """Run complete games, including setup, terminal scoring, and ranking."""
    seeds = tuple(str(seed_offset + index) for index in range(batch_size))
    engine = BatchSimEngine.start(player_count=3, seeds=seeds)
    policy_rng = np.random.default_rng(seed_offset)

    while True:
        actions = engine.flip_actions()
        if not actions.any():
            break
        legal = engine.legal_max_bids()
        bids = np.floor(policy_rng.random(legal.shape) * (legal + 1)).astype(np.int16)
        outcome = engine.resolve_bids(bids)
        reveals = np.full(batch_size, -1, dtype=np.int8)
        reveals[outcome.reveal_modes > 0] = 0
        engine.apply_reveals(reveals)

    engine.scores()
    engine.rankings()


def peak_rss_mib() -> float | None:
    if resource is None:
        return None
    peak = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    if platform.system() != "Darwin":
        peak *= 1024
    return peak / (1024 * 1024)


def measure(
    batch_size: int,
    *,
    warmups: int,
    repeats: int,
    seed_offset: int,
) -> dict[str, Any]:
    for index in range(warmups):
        run_episode(batch_size, seed_offset + index * 100_000)

    samples: list[float] = []
    sample_seed = seed_offset + warmups * 100_000
    for index in range(repeats):
        started = time.perf_counter()
        run_episode(batch_size, sample_seed + index * 100_000)
        samples.append(time.perf_counter() - started)

    median = statistics.median(samples)
    return {
        "batch_size": batch_size,
        "median_seconds": median,
        "games_per_second": batch_size / median,
        "peak_rss_mib": peak_rss_mib(),
        "samples_seconds": samples,
    }


def run_isolated(args: argparse.Namespace, batch_size: int) -> dict[str, Any]:
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--worker-batch-size",
        str(batch_size),
        "--warmups",
        str(args.warmups),
        "--repeats",
        str(args.repeats),
        "--seed-offset",
        str(args.seed_offset),
    ]
    # Re-invokes this same script (sys.executable + our own path) with argparse
    # `type=int` values only; no shell, no untrusted/string input.
    completed = subprocess.run(  # noqa: S603
        command,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def print_result(result: dict[str, Any]) -> None:
    rss = result["peak_rss_mib"]
    rss_text = "n/a" if rss is None else f"{rss:.1f} MiB"
    print(
        f"batch={result['batch_size']} "
        f"median={result['median_seconds']:.6f}s "
        f"throughput={result['games_per_second']:.2f} games/s "
        f"peak_rss={rss_text} "
        f"samples={result['samples_seconds']}"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Measure full-episode BatchSimEngine throughput; each batch size "
            "runs in a fresh process so peak RSS values are independent."
        )
    )
    parser.add_argument(
        "--batch-sizes",
        nargs="+",
        type=int,
        default=(1, 64, 256, 1024, 4096),
    )
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--seed-offset", type=int, default=1_000_000)
    parser.add_argument("--worker-batch-size", type=int, help=argparse.SUPPRESS)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.worker_batch_size is not None:
        print(
            json.dumps(
                measure(
                    args.worker_batch_size,
                    warmups=args.warmups,
                    repeats=args.repeats,
                    seed_offset=args.seed_offset,
                )
            )
        )
        return

    for batch_size in args.batch_sizes:
        print_result(run_isolated(args, batch_size))


if __name__ == "__main__":
    main()
