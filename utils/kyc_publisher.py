"""
Utility to create a KYC case: write to DynamoDB and send JSON payload to SQS.
Record shape excludes results, personScreening, and finalDecision.
Testing only: uses hardcoded names matching the deployed stacks.
"""

import json
import logging
from typing import Any

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

# Hardcoded for testing — match deploy.sh default BASE_NAME (e.g. kyc-agent)
_DEFAULT_BASE_NAME = "kyc-agent"
TEST_TABLE_NAME = f"{_DEFAULT_BASE_NAME}-storage-kyc-cases"
TEST_QUEUE_NAME = f"{_DEFAULT_BASE_NAME}-main-kyc-initiated"
TEST_S3_BUCKET_NAME = f"{_DEFAULT_BASE_NAME}-storage-agent-source"
TEST_REGION = "us-east-1"

# Default dummy record for testing (includes dummy S3 keys under files)
DUMMY_RECORD: dict[str, Any] = {
    "CaseId": "1234",
    "createdAt": "2026-02-26T01:55:22Z",
    "createdBy": "user-abc",
    "status": "INITIATED",
    "statusUpdatedAt": "2026-02-26T02:18:10Z",
    "files": [
        {"type": "passport", "bucket": "kyc-agent-storage-agent-source", "key": "cases/1234/passport.pdf"},
        {"type": "license", "bucket": "kyc-agent-storage-agent-source", "key": "cases/1234/license.pdf"}
    ],
    "identity": {
        "fullName": "Alex Morgan Lee",
        "dateOfBirth": "1990-05-12",
        "nationality": "UTO (Mock)",
    }
}

# Fields to omit from the stored/published case record
_OMIT_KEYS = frozenset({"results", "personScreening", "finalDecision"})


def _sanitize_record(record: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of the record without results, personScreening, finalDecision."""
    return {k: v for k, v in record.items() if k not in _OMIT_KEYS}


class KycCasePublisher:
    """Pushes a KYC case record to DynamoDB and sends a JSON payload to SQS."""

    def __init__(
        self,
        table_name: str,
        queue_url: str,
        region_name: str | None = None,
        dynamodb_table=None,
        sqs_client=None,
    ):
        self.table_name = table_name
        self.queue_url = queue_url
        self._region = region_name
        self._dynamodb_table = dynamodb_table
        self._sqs = sqs_client

    @property
    def _table(self):
        if self._dynamodb_table is None:
            resource = boto3.resource("dynamodb", region_name=self._region)
            self._dynamodb_table = resource.Table(self.table_name)
        return self._dynamodb_table

    @property
    def sqs(self):
        if self._sqs is None:
            self._sqs = boto3.client("sqs", region_name=self._region)
        return self._sqs

    def push_case(self, record: dict[str, Any]) -> tuple[bool, str | None]:
        """
        Write the case to DynamoDB and send a JSON payload to SQS.
        Record is sanitized: results, personScreening, and finalDecision are omitted.

        Returns:
            (success: bool, error_message: str | None)
        """
        payload = _sanitize_record(record)
        case_id = payload.get("CaseId")
        if not case_id:
            return False, "record must contain 'CaseId'"

        try:
            self._put_dynamodb(payload)
            self._send_sqs(payload)
            logger.info("Pushed caseId=%s to DynamoDB and SQS", case_id)
            return True, None
        except ClientError as e:
            msg = f"caseId={case_id} error: {e.response.get('Error', {}).get('Message', str(e))}"
            logger.exception(msg)
            return False, msg
        except Exception as e:
            logger.exception("push_case failed: %s", e)
            return False, str(e)

    def _put_dynamodb(self, payload: dict[str, Any]) -> None:
        """Put item into DynamoDB (resource accepts plain dict with nested types)."""
        self._table.put_item(Item=payload)

    def _send_sqs(self, payload: dict[str, Any]) -> None:
        """Send JSON payload as SQS message body."""
        body = json.dumps(payload, default=str)
        self.sqs.send_message(QueueUrl=self.queue_url, MessageBody=body)


def _get_queue_url(queue_name: str, region: str | None) -> str:
    """Resolve SQS queue URL from queue name."""
    client = boto3.client("sqs", region_name=region or TEST_REGION)
    resp = client.get_queue_url(QueueName=queue_name)
    return resp["QueueUrl"]


def main() -> None:
    """CLI: push dummy KYC case to DynamoDB and SQS (testing)."""
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="Push a dummy KYC case record to DynamoDB and SQS."
    )
    parser.add_argument("--table", default=TEST_TABLE_NAME, help=f"DynamoDB table (default: {TEST_TABLE_NAME})")
    parser.add_argument("--queue-url", default=None, help="SQS queue URL (default: resolve from queue name)")
    parser.add_argument("--queue-name", default=TEST_QUEUE_NAME, help=f"SQS queue name (default: {TEST_QUEUE_NAME})")
    parser.add_argument("--region", default=TEST_REGION, help=f"AWS region (default: {TEST_REGION})")
    args = parser.parse_args()

    queue_url = args.queue_url
    if queue_url is None:
        queue_url = _get_queue_url(args.queue_name, args.region)

    publisher = KycCasePublisher(
        table_name=args.table,
        queue_url=queue_url,
        region_name=args.region,
    )
    ok, err = publisher.push_case(DUMMY_RECORD)
    if not ok:
        print(f"Error: {err}", file=sys.stderr)
        sys.exit(1)
    print("OK: case pushed to DynamoDB and SQS")
    sys.exit(0)


if __name__ == "__main__":
    main()
