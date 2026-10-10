"""Run the agent once. Usage: python scripts/run_agent.py [--within-days 7]"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent import run_check

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--within-days", type=int, default=7)
    args = parser.parse_args()
    run_check(within_days=args.within_days)
