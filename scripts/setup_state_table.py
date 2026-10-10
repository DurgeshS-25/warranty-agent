"""Create the DynamoDB table (safe to run more than once)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from state import create_table_if_missing

if __name__ == "__main__":
    create_table_if_missing()
