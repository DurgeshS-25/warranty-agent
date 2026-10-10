"""Delete the DynamoDB state table (wipes all state). Re-create with setup_state_table.py."""
import os

import boto3
from dotenv import load_dotenv

load_dotenv()

TABLE = os.environ.get("DYNAMODB_TABLE_NAME", "warranty-agent-state")

if __name__ == "__main__":
    client = boto3.client("dynamodb", region_name=os.environ["AWS_REGION"])
    client.delete_table(TableName=TABLE)
    client.get_waiter("table_not_exists").wait(TableName=TABLE)
    print(f"Deleted {TABLE}")
