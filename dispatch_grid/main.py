"""CLI entry point.

    python -m dispatch_grid.main --duration 3600 --incidents 320 --seed 42
"""
import argparse
import json

from .simulation import run

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Smart City Dynamic Dispatch Grid")
    ap.add_argument("--duration", type=float, default=3600.0, help="seconds of call stream")
    ap.add_argument("--incidents", type=int, default=320, help="ground-truth incidents")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--tick", type=float, default=10.0, help="simulation tick (s)")
    ap.add_argument("--out", type=str, default="timeline.json")
    a = ap.parse_args()
    coord, timeline = run(duration=a.duration, tick=a.tick, seed=a.seed,
                          n_incidents=a.incidents)
    with open(a.out, "w") as f:
        json.dump(timeline, f, indent=1)
    print(f"\nTimeline written to {a.out}")
