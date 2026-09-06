"""Command-line entrypoint for Monte-Carlo simulation and smoothing collateral script.

Notes/Architectural Intent:
    Serves as an executable collateral script invoked by batch worker tasks
    across various parameter regimes (simulate) and aggregation stages (aggregate).
"""

import argparse
import json
import math
import random
import sys
from pathlib import Path


def run_simulate(
    regime: str,
    seed: int,
    drift: float,
    vol: float,
    num_paths: int,
    steps: int,
    dt: float,
    initial_value: float,
    output_dir: Path,
) -> None:
    """Simulate geometric Brownian motion paths and save to output JSON file.

    Args:
        regime: Name of the volatility/market regime.
        seed: Random seed for reproducibility.
        drift: Drift rate parameter mu.
        vol: Volatility rate parameter sigma.
        num_paths: Total trajectory paths to simulate.
        steps: Time steps per path.
        dt: Delta time increment.
        initial_value: Starting value at step 0.
        output_dir: Target directory for result JSON.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)  # noqa: S311

    drift_term = (drift - 0.5 * vol**2) * dt
    vol_term = vol * math.sqrt(dt)

    paths: list[list[float]] = []
    for _ in range(num_paths):
        path = [initial_value]
        current = initial_value
        for _ in range(steps - 1):
            u1 = rng.random()
            u2 = rng.random()
            z = math.sqrt(-2.0 * math.log(max(u1, 1e-12))) * math.cos(
                2.0 * math.pi * u2
            )
            current = current * math.exp(drift_term + vol_term * z)
            path.append(current)
        paths.append(path)

    out_file = output_dir / f"{regime}.json"
    with out_file.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "regime": regime,
                "seed": seed,
                "drift": drift,
                "vol": vol,
                "paths": paths,
            },
            f,
        )

    print(
        f"[Monte-Carlo Worker] Simulated {regime}: "
        f"{len(paths)} paths, {steps} steps -> {out_file}"
    )


def run_aggregate(
    input_dir: Path,
    regimes: list[str],
    window_size: int,
) -> None:
    """Aggregate multiple simulated regimes, compute pointwise mean, and apply smoothing.

    Args:
        input_dir: Directory containing simulation JSON outputs.
        regimes: List of regime names to load and merge.
        window_size: Moving average smoothing window size.
    """
    all_paths: list[list[float]] = []
    for reg in regimes:
        reg_file = input_dir / f"{reg}.json"
        if not reg_file.is_file():
            msg = f"Missing expected regime simulation output file: {reg_file}"
            raise FileNotFoundError(msg)

        with reg_file.open("r", encoding="utf-8") as f:
            data = json.load(f)
            all_paths.extend(data["paths"])

    if not all_paths:
        msg = "No paths found for aggregation"
        raise ValueError(msg)

    total_paths = len(all_paths)
    steps = len(all_paths[0])

    mean_trajectory: list[float] = []
    for step_idx in range(steps):
        step_sum = sum(p[step_idx] for p in all_paths)
        mean_trajectory.append(step_sum / total_paths)

    smoothed: list[float] = []
    half_w = window_size // 2
    for i in range(steps):
        start = max(0, i - half_w)
        end = min(steps, i + half_w + 1)
        win = mean_trajectory[start:end]
        smoothed.append(sum(win) / len(win))

    terminals = [p[-1] for p in all_paths]
    term_mean = sum(terminals) / total_paths
    term_var = sum((v - term_mean) ** 2 for v in terminals) / total_paths
    std_err = math.sqrt(term_var) / math.sqrt(total_paths) if total_paths > 1 else 0.0

    print(
        f"[Monte-Carlo Aggregation Complete] Total Paths: {total_paths}, "
        f"Terminal Mean: {term_mean:.2f} (95% CI: [{term_mean - 1.96 * std_err:.2f}, {term_mean + 1.96 * std_err:.2f}]), "
        f"Smoothed T={steps}: {smoothed[-1]:.2f}"
    )


def main(argv: list[str] | None = None) -> int:
    """Main CLI parser entrypoint for monte carlo collateral script."""
    parser = argparse.ArgumentParser(
        description="Monte-Carlo simulation and smoothing worker script."
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    # simulate subcommand
    sim_p = subparsers.add_parser("simulate", help="Run a single simulation regime.")
    sim_p.add_argument("--regime", type=str, required=True, help="Regime identifier")
    sim_p.add_argument("--seed", type=int, default=101, help="Random seed")
    sim_p.add_argument("--drift", type=float, default=0.05, help="Drift mu")
    sim_p.add_argument("--vol", type=float, default=0.20, help="Volatility sigma")
    sim_p.add_argument("--paths", type=int, default=50, help="Number of paths")
    sim_p.add_argument("--steps", type=int, default=100, help="Steps per path")
    sim_p.add_argument("--dt", type=float, default=0.01, help="Delta time increment")
    sim_p.add_argument(
        "--initial-value", type=float, default=100.0, help="Starting price/value"
    )
    sim_p.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Output directory for JSON results",
    )

    # aggregate subcommand
    agg_p = subparsers.add_parser(
        "aggregate", help="Aggregate and smooth simulated regime outputs."
    )
    agg_p.add_argument(
        "--input-dir",
        type=Path,
        required=True,
        help="Input directory containing regime JSONs",
    )
    agg_p.add_argument(
        "--regimes", nargs="+", required=True, help="List of regime names"
    )
    agg_p.add_argument("--window", type=int, default=5, help="Smoothing window size")

    args = parser.parse_args(argv)

    if args.subcommand == "simulate":
        run_simulate(
            regime=args.regime,
            seed=args.seed,
            drift=args.drift,
            vol=args.vol,
            num_paths=args.paths,
            steps=args.steps,
            dt=args.dt,
            initial_value=args.initial_value,
            output_dir=args.output_dir,
        )
    elif args.subcommand == "aggregate":
        run_aggregate(
            input_dir=args.input_dir,
            regimes=args.regimes,
            window_size=args.window,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
