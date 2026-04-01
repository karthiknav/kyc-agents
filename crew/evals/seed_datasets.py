"""Seed golden evaluation datasets into Langfuse.

Usage:
    python -m crew.evals.seed_datasets --all
    python -m crew.evals.seed_datasets --dataset kyc-identity-verification
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

DATASETS_DIR = Path(__file__).parent / "datasets"

DATASET_FILES = {
    "kyc-identity-verification": "identity_verification.json",
    "kyc-income-verification": "income_verification.json",
    "kyc-adverse-media": "adverse_media.json",
    "kyc-orchestrator-e2e": "orchestrator_e2e.json",
}


def seed_dataset(langfuse, dataset_name: str, filepath: Path) -> int:
    """Create or update a Langfuse dataset from a JSON file. Returns item count."""
    with open(filepath) as f:
        data = json.load(f)

    # Create dataset (idempotent)
    langfuse.create_dataset(
        name=data["name"],
        description=data.get("description", ""),
    )
    logger.info("Dataset '%s' created/updated", data["name"])

    count = 0
    for item in data.get("items", []):
        langfuse.create_dataset_item(
            dataset_name=data["name"],
            input=item.get("input"),
            expected_output=item.get("expected_output"),
            id=item.get("id"),
            metadata=item.get("metadata"),
        )
        count += 1
        logger.info("  Seeded item: %s", item.get("id", f"item-{count}"))

    return count


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser(description="Seed golden evaluation datasets into Langfuse")
    parser.add_argument("--all", action="store_true", help="Seed all datasets")
    parser.add_argument("--dataset", type=str, help="Seed a specific dataset by name")
    args = parser.parse_args()

    if not args.all and not args.dataset:
        parser.print_help()
        sys.exit(1)

    try:
        from langfuse import Langfuse
        langfuse = Langfuse()
    except Exception as e:
        logger.error("Failed to connect to Langfuse: %s", e)
        logger.error("Ensure LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, and LANGFUSE_HOST are set.")
        sys.exit(1)

    datasets_to_seed = DATASET_FILES if args.all else {}
    if args.dataset:
        if args.dataset in DATASET_FILES:
            datasets_to_seed = {args.dataset: DATASET_FILES[args.dataset]}
        else:
            logger.error("Unknown dataset: %s. Available: %s", args.dataset, list(DATASET_FILES.keys()))
            sys.exit(1)

    total = 0
    for name, filename in datasets_to_seed.items():
        filepath = DATASETS_DIR / filename
        if not filepath.exists():
            logger.warning("Dataset file not found: %s", filepath)
            continue
        count = seed_dataset(langfuse, name, filepath)
        total += count
        logger.info("Seeded %d items into '%s'", count, name)

    langfuse.flush()
    logger.info("Done. Total items seeded: %d across %d dataset(s)", total, len(datasets_to_seed))


if __name__ == "__main__":
    main()
