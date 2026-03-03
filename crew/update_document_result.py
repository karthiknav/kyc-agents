import json
import logging
import os
from datetime import datetime, timezone

import boto3

logger = logging.getLogger(__name__)


def _format_document_report(
    case_id: str,
    name: str,
    comparison_result: str,
    comparison_summary: str,
    discrepancies: list,
    documents_summary: str,
    updated_at: str,
) -> str:
    """Format document processing output as a markdown report."""
    status_emoji = {"MATCH": "✅", "PARTIAL_MATCH": "⚠️", "MISMATCH": "❌"}
    emoji = status_emoji.get(comparison_result, "❓")
    discrepancies_md = (
        "\n".join(f"- {d}" for d in discrepancies)
        if discrepancies
        else "_No discrepancies found._"
    )
    lines = [
        "# KYC Document Processing Report",
        "",
        f"**Case ID:** `{case_id}`",
        f"**Subject:** {name}",
        f"**Report generated:** {updated_at}",
        "",
        "---",
        "",
        "## Documents processed",
        "",
        documents_summary or "_No documents summary available._",
        "",
        "---",
        "",
        "## Identity comparison result",
        "",
        f"**Result:** {emoji} **{comparison_result}**",
        "",
        "**Discrepancies:**",
        "",
        discrepancies_md,
        "",
        "**Comparison summary:**",
        "",
        comparison_summary,
        "",
    ]
    return "\n".join(lines)


def update_document_result(task_output):
    """Update the documentProcessing stage in the case document and notify the orchestrator."""
    logger.info("update_document_result input: task_output=%s", task_output)
    if hasattr(task_output, "raw"):
        task_output = task_output.raw
    if isinstance(task_output, str):
        try:
            task_output = json.loads(task_output)
        except json.JSONDecodeError:
            logger.error("update_document_result: task_output is not valid JSON")
            return
    case_id = task_output.get("case_id")
    comparison_result = task_output.get("comparison_result")
    comparison_summary = task_output.get("comparison_summary")
    discrepancies = task_output.get("discrepancies", [])
    documents_summary = task_output.get("documents_summary", "")
    name = task_output.get("name", "Unknown")

    # Build identity for DynamoDB (fullName, dateOfBirth, nationality)
    identity = {
        "fullName": task_output.get("fullName") or name or "Unknown",
        "dateOfBirth": task_output.get("dateOfBirth") or task_output.get("identity", {}).get("dateOfBirth", ""),
        "nationality": task_output.get("nationality") or task_output.get("identity", {}).get("nationality", ""),
    }
    logger.info("Document result identity: fullName=%s, dateOfBirth=%s, nationality=%s", identity["fullName"], identity["dateOfBirth"], identity["nationality"])

    if not case_id or not comparison_result or not comparison_summary:
        logger.info(
            "Results incomplete: case_id=%s, comparison_result=%s, comparison_summary=%s",
            case_id, comparison_result, comparison_summary,
        )
        return

    # Normalise comparison_result to canonical values
    result_map = {
        "match": "MATCH",
        "partial_match": "PARTIAL_MATCH",
        "mismatch": "MISMATCH",
        "MATCH": "MATCH",
        "PARTIAL_MATCH": "PARTIAL_MATCH",
        "MISMATCH": "MISMATCH",
    }
    status = result_map.get(str(comparison_result), "PARTIAL_MATCH")

    if not isinstance(discrepancies, list):
        discrepancies = [str(discrepancies)] if discrepancies else []

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    report_md = _format_document_report(
        case_id=case_id,
        name=name,
        comparison_result=status,
        comparison_summary=comparison_summary,
        discrepancies=discrepancies,
        documents_summary=documents_summary,
        updated_at=now,
    )

    # Upload report to S3
    report_s3 = None
    bucket = os.environ.get("KYC_RESULTS_BUCKET", "kyc-results")
    report_key = f"cases/{case_id}/document-processing-report.md"
    try:
        s3 = boto3.client("s3")
        s3.put_object(
            Bucket=bucket,
            Key=report_key,
            Body=report_md.encode("utf-8"),
            ContentType="text/markdown",
        )
        report_s3 = {"bucket": bucket, "key": report_key}
        logger.info("Document processing report uploaded to s3://%s/%s", bucket, report_key)
    except Exception as e:
        logger.exception("Failed to upload document processing report to S3: %s", e)

    # Build the documentProcessing stage object
    document_processing_stage = {
        "result": status,
        "updatedAt": now,
        "summary": comparison_summary,
        "discrepancies": discrepancies,
    }
    if report_s3:
        document_processing_stage["reportS3"] = report_s3

    table_name = os.environ.get("KYC_CASES_TABLE", "kyc-cases")
    try:
        dynamodb = boto3.resource("dynamodb")
        table = dynamodb.Table(table_name)
        # Step 1: ensure #stages map exists
        table.update_item(
            Key={"CaseId": case_id},
            UpdateExpression="SET #stages = if_not_exists(#stages, :empty_map)",
            ExpressionAttributeNames={"#stages": "stages"},
            ExpressionAttributeValues={":empty_map": {}},
        )
        # Step 2: write documentProcessing stage
        table.update_item(
            Key={"CaseId": case_id},
            UpdateExpression="SET #stages.#documentProcessing = :documentProcessing",
            ExpressionAttributeNames={
                "#stages": "stages",
                "#documentProcessing": "documentProcessing",
            },
            ExpressionAttributeValues={":documentProcessing": document_processing_stage},
        )
    except Exception as e:
        logger.exception("update_document_result DynamoDB error: %s", e)
        return

