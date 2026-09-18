"""Interactive executable entrypoint for the 100-slot monopoly demonstration.

Notes/Architectural Intent:
    Provides a standalone CLI runner demonstrating how Hexaqueue resolves
    cluster monopolies via fair-share trees, starvation thresholds, and
    controlled preemption.
"""

import sys
from pathlib import Path

# Ensure examples/monopoly/src is in sys.path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from monopoly.infra.runner import render_monopoly_report, run_monopoly_simulation


def main() -> int:
    """Execute 100-slot monopoly simulation and render Rich report."""
    phases, audit_records = run_monopoly_simulation(
        total_slots=100,
        grace_period_seconds=30.0,
        starvation_deficit_threshold=0.4,
        preemption_bonus=5000.0,
    )
    render_monopoly_report(phases, audit_records)
    return 0


if __name__ == "__main__":
    sys.exit(main())
