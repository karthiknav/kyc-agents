"""
Seed eval test cases into DynamoDB + S3.

Scans eval/fixtures/ for sub-folders, each containing:
  - case.json       identity data for DynamoDB
  - <any image/PDF> document file(s) to upload to S3

For each fixture:
  1. Uploads all document files to S3 under cases/{caseId}/
  2. Creates a DynamoDB case record with identity + file references

Writes eval/case_ids.json — fixture name → caseId.
Re-running is safe: existing case IDs are reused (no duplicates created).

Usage (from repo root):
  python -m eval.seed

Required env (read from crew/.env):
  KYC_CASES_TABLE     DynamoDB table name
  KYC_RESULTS_BUCKET  S3 bucket name
  AWS_REGION          (default: us-east-1)
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from pathlib import Path

import boto3
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / "crew" / ".env")

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

EVAL_DIR      = Path(__file__).parent
FIXTURES_DIR  = EVAL_DIR / "fixtures"
CASE_IDS_FILE = EVAL_DIR / "case_ids.json"

DOCUMENT_EXTENSIONS = {".png", ".jpg", ".jpeg", ".pdf", ".tiff", ".tif"}
CONTENT_TYPES = {
    ".png":  "image/png",
    ".jpg":  "image/jpeg",
    ".jpeg": "image/jpeg",
    ".pdf":  "application/pdf",
    ".tiff": "image/tiff",
    ".tif":  "image/tiff",
}


def _table():
    name = os.environ.get("KYC_CASES_TABLE", "kyc-agent-storage-kyc-cases")
    return boto3.resource("dynamodb", region_name=os.environ.get("AWS_REGION", "us-east-1")).Table(name)


def _s3():
    return boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-east-1"))


def _bucket() -> str:
    return os.environ.get("KYC_RESULTS_BUCKET", "kyc-results")


def _load_case_ids() -> dict[str, str]:
    if CASE_IDS_FILE.exists():
        return json.loads(CASE_IDS_FILE.read_text())
    return {}


def _save_case_ids(mapping: dict[str, str]) -> None:
    CASE_IDS_FILE.write_text(json.dumps(mapping, indent=2))


def seed_fixture(fixture_name: str, existing_ids: dict[str, str]) -> str:
    fixture_dir = FIXTURES_DIR / fixture_name
    case_json   = fixture_dir / "case.json"
    fixture     = json.loads(case_json.read_text())

    doc_files = sorted(
        f for f in fixture_dir.iterdir()
        if f.is_file() and f.suffix.lower() in DOCUMENT_EXTENSIONS
    )
    if not doc_files:
        raise FileNotFoundError(
            f"No document files found in {fixture_dir}. "
            f"Add at least one image or PDF ({', '.join(DOCUMENT_EXTENSIONS)})."
        )

    case_id = existing_ids.get(fixture_name) or str(uuid.uuid4())
    bucket  = _bucket()
    iden    = fixture["identity"]
    doc_cfg = fixture.get("document", {})

    # Upload each document file to S3
    file_refs = []
    for doc_file in doc_files:
        s3_key = f"cases/{case_id}/{doc_file.name}"
        logger.info("  S3 upload  s3://%s/%s", bucket, s3_key)
        _s3().upload_file(
            str(doc_file),
            bucket,
            s3_key,
            ExtraArgs={"ContentType": CONTENT_TYPES.get(doc_file.suffix.lower(), "application/octet-stream")},
        )
        file_refs.append({
            "bucket":     bucket,
            "key":        s3_key,
            "type": doc_cfg.get("type", "paspoort"),
        })

    # Create DynamoDB record
    item = {
        "CaseId":   case_id,
        "identity": {
            "fullName":    iden["fullName"],
            "firstName":   iden["firstName"],
            "lastName":    iden["lastName"],
            "dateOfBirth": iden["dateOfBirth"],
            "nationality": iden["nationality"],
        },
        "files":  file_refs,
        "status": "PENDING",
    }
    logger.info("  DynamoDB put  CaseId=%s  (%s)", case_id, iden["fullName"])
    _table().put_item(Item=item)

    return case_id


def main() -> None:
    fixture_dirs = sorted(
        p for p in FIXTURES_DIR.iterdir()
        if p.is_dir() and (p / "case.json").exists()
    )
    if not fixture_dirs:
        logger.error("No fixtures found in %s (each must have a case.json)", FIXTURES_DIR)
        return

    existing_ids = _load_case_ids()
    updated_ids  = dict(existing_ids)

    for fixture_dir in fixture_dirs:
        name = fixture_dir.name
        logger.info("Seeding: %s", name)
        case_id = seed_fixture(name, existing_ids)
        updated_ids[name] = case_id
        logger.info("  caseId: %s\n", case_id)

    _save_case_ids(updated_ids)
    logger.info("Done. case_ids.json:")
    for k, v in updated_ids.items():
        logger.info("  %-25s → %s", k, v)
    logger.info("\nNext: python -m eval.run_eval --seed-dataset")


if __name__ == "__main__":
    main()
