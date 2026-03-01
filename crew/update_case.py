import json
import logging
import os
from datetime import datetime, timezone

import boto3

logger = logging.getLogger(__name__)


def _format_screening_report(
    case_id: str,
    name: str,
    analysis_result: str,
    analysis_summary: str,
    search_results_summary: str = "",
    updated_at: str = "",
) -> str:
    """Format screening output as a markdown report."""
    status_emoji = {"OK": "✅", "NOK": "❌", "AMBIGUOUS": "⚠️"}
    emoji = status_emoji.get(analysis_result, "❓")
    lines = [
        "# KYC Screening Report",
        "",
        f"**Case ID:** `{case_id}`",
        f"**Subject:** {name}",
        f"**Report generated:** {updated_at}",
        "",
        "---",
        "",
        "## Search results summary",
        "",
        search_results_summary or "_No search results summary available._",
        "",
        "---",
        "",
        "## Screening result",
        "",
        f"**Result:** {emoji} **{analysis_result}**",
        "",
        "**Analysis summary:**",
        "",
        analysis_summary,
        "",
    ]
    return "\n".join(lines)


def update_screening_result(task_output):
    """Update the screening stage in the case document according to the schema."""
    logger.info("update_screening_result input: task_output=%s", task_output)
    # task_output may be TaskOutput object or dict or JSON string from agent
    if hasattr(task_output, "raw"):
        task_output = task_output.raw
    if isinstance(task_output, str):
        try:
            task_output = json.loads(task_output)
        except json.JSONDecodeError:
            logger.error("update_screening_result: task_output is not valid JSON")
            return
    case_id = task_output.get("case_id")
    analysis_result = task_output.get("analysis_result")
    analysis_summary = task_output.get("analysis_summary")
    search_results_summary = task_output.get("search_results_summary", "")
    name = task_output.get("name", "Unknown")
    if not case_id or not analysis_result or not analysis_summary:
        logger.info("Results incomplete: case_id=%s, analysis_result=%s, analysis_summary=%s", case_id, analysis_result, analysis_summary)
        return

    # Map analysis_result (screening ok | screening not ok | ambiguous) to schema status (OK | NOT_OK | AMBIGUOUS)
    result_map = {
        "screening ok": "OK",
        "screening not ok": "NOK",
        "ambiguous": "AMBIGUOUS",
        "ok": "OK",
        "nok": "NOK",
        "OK": "OK",
        "NOK": "NOK",
        "AMBIGUOUS": "AMBIGUOUS",
    }
    status = result_map.get(str(analysis_result).lower(), "AMBIGUOUS")
    # finalDecision: LOGICALLY DERIVED from screening result
    final_decision_map = {
        "OK": "OK",
        "NOK": "NOT_OK",
        "AMBIGUOUS": "PENDING_REVIEW",
    }
    final_decision = final_decision_map.get(status, "PENDING_REVIEW")

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Build markdown report
    report_md = _format_screening_report(
        case_id=case_id,
        name=name,
        analysis_result=status,
        analysis_summary=analysis_summary,
        search_results_summary=search_results_summary,
        updated_at=now,
    )

    # Upload report to S3 and get key
    report_s3 = None
    bucket = os.environ.get("KYC_RESULTS_BUCKET", "kyc-results")
    report_key = f"cases/{case_id}/screening-report.md"
    try:
        s3 = boto3.client("s3")
        s3.put_object(
            Bucket=bucket,
            Key=report_key,
            Body=report_md.encode("utf-8"),
            ContentType="text/markdown",
        )
        report_s3 = {"bucket": bucket, "key": report_key}
        logger.info("Screening report uploaded to s3://%s/%s", bucket, report_key)
    except Exception as e:
        logger.exception("Failed to upload screening report to S3: %s", e)

    # Build the screening stage object per schema
    screening_stage = {
        "result": status,
        "updatedAt": now,
        "summary": analysis_summary,
    }
    if report_s3:
        screening_stage["reportS3"] = report_s3

    table_name = os.environ.get("KYC_CASES_TABLE", "kyc-cases")
    try:
        dynamodb = boto3.resource("dynamodb")
        table = dynamodb.Table(table_name)
        # Step 1: ensure #stages map exists (create empty if not)
        table.update_item(
            Key={"CaseId": case_id},
            UpdateExpression="SET #stages = if_not_exists(#stages, :empty_map)",
            ExpressionAttributeNames={"#stages": "stages"},
            ExpressionAttributeValues={":empty_map": {}},
        )
        # Step 2: set #stages.screening with status, summary, updatedAt, reportMarkdown, reportS3
        table.update_item(
            Key={"CaseId": case_id},
            UpdateExpression="SET #stages.#screening = :screening",
            ExpressionAttributeNames={
                "#stages": "stages",
                "#screening": "screening",
            },
            ExpressionAttributeValues={":screening": screening_stage},
        )
        logger.info("update_screening_result success: case_id=%s, status=%s, final_decision=%s", case_id, status, final_decision)
    except Exception as e:
        logger.exception("update_screening_result error: %s", e)
