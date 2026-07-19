import json
import logging
import os
from datetime import datetime, timezone

import boto3

from crew.utils import parse_task_output

logger = logging.getLogger(__name__)


def _format_screening_report(
    case_id: str,
    name: str,
    analysis_result: str,
    analysis_summary: str,
    search_results_summary: str = "",
    updated_at: str = "",
    severity: str = "",
    pep_summary: str = "",
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
    ]
    if severity or pep_summary:
        lines.extend([
            "## PEP / Sanctions API",
            "",
            f"**Severity:** {severity or 'none'}",
            "",
            pep_summary or "_No PEP/sanctions matches._",
            "",
            "---",
            "",
        ])
    lines.extend([
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
    ])
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
    severity = task_output.get("severity", "")
    pep_summary = task_output.get("pep_summary", "")
    name = task_output.get("name", "Unknown")
    if not case_id or not analysis_result or not analysis_summary:
        logger.info("Results incomplete: case_id=%s, analysis_result=%s, analysis_summary=%s", case_id, analysis_result, analysis_summary)
        return


def update_risk_list_screening_result(task_output):
    """Update stages.screening.riskListScreening and upload raw response JSON to S3."""
    logger.info("update_risk_list_screening_result input: task_output=%s", task_output)
    task_output = parse_task_output(task_output)
    if task_output is None:
        logger.error("update_risk_list_screening_result: task_output is not valid JSON, skipping DB update")
        return

    case_id = task_output.get("case_id")
    name = task_output.get("name", "Unknown")
    result = task_output.get("result")
    pep_status = task_output.get("pepStatus")
    sanctions_status = task_output.get("sanctionsStatus")
    datasets_matched = task_output.get("datasetsMatched", [])
    summary = task_output.get("summary", "")
    clarification_requested = bool(task_output.get("clarificationRequested", False))
    raw = task_output.get("rawResponse", {})
    if not case_id or not result:
        logger.info("Risk-list results incomplete: case_id=%s, result=%s", case_id, result)
        return

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Upload raw response to S3 as JSON
    bucket = os.environ.get("KYC_RESULTS_BUCKET", "kyc-results")
    raw_key = f"cases/{case_id}/risk-list-report.json"
    raw_s3 = None
    try:
        s3 = boto3.client("s3")
        s3.put_object(
            Bucket=bucket,
            Key=raw_key,
            Body=json.dumps(raw, indent=2, default=str).encode("utf-8"),
            ContentType="application/json",
        )
        raw_s3 = {"bucket": bucket, "key": raw_key}
        logger.info("Risk-list raw response uploaded to s3://%s/%s", bucket, raw_key)
    except Exception as e:
        logger.exception("Failed to upload risk-list raw response to S3: %s", e)

    risk_list = {
        "result": result,
        "pepStatus": pep_status or "UNKNOWN",
        "sanctionsStatus": sanctions_status or "UNKNOWN",
        "datasetsMatched": datasets_matched if isinstance(datasets_matched, list) else [],
        "summary": summary or "",
        "clarificationRequested": clarification_requested,
        "updatedAt": now,
    }
    if raw_s3:
        risk_list["rawResponseS3"] = raw_s3

    table_name = os.environ.get("KYC_CASES_TABLE", "kyc-cases")
    try:
        dynamodb = boto3.resource("dynamodb")
        table = dynamodb.Table(table_name)

        # If request_clarification already ran earlier in this same task (it writes
        # clarificationRequest directly), carry it forward — the SET below replaces the whole
        # riskListScreening map and would otherwise clobber it.
        try:
            existing = table.get_item(Key={"CaseId": case_id}).get("Item") or {}
            existing_clarification = (
                (existing.get("stages") or {}).get("screening", {}).get("riskListScreening", {}).get("clarificationRequest")
            )
            if existing_clarification:
                risk_list["clarificationRequest"] = existing_clarification
        except Exception:
            logger.exception("update_risk_list_screening_result: failed to read existing clarificationRequest")

        # ensure stages and screening maps exist
        table.update_item(
            Key={"CaseId": case_id},
            UpdateExpression="SET #stages = if_not_exists(#stages, :empty_map)",
            ExpressionAttributeNames={"#stages": "stages"},
            ExpressionAttributeValues={":empty_map": {}},
        )
        table.update_item(
            Key={"CaseId": case_id},
            UpdateExpression="SET #stages.#screening = if_not_exists(#stages.#screening, :empty_map)",
            ExpressionAttributeNames={"#stages": "stages", "#screening": "screening"},
            ExpressionAttributeValues={":empty_map": {}},
        )
        table.update_item(
            Key={"CaseId": case_id},
            UpdateExpression="SET #stages.#screening.#risk = :risk",
            ExpressionAttributeNames={
                "#stages": "stages",
                "#screening": "screening",
                "#risk": "riskListScreening",
            },
            ExpressionAttributeValues={":risk": risk_list},
        )
        logger.info("update_risk_list_screening_result success: case_id=%s, name=%s, result=%s", case_id, name, result)
    except Exception as e:
        logger.exception("update_risk_list_screening_result error: %s", e)


def update_adverse_media_result(task_output):
    """Update stages.screening.adverseMedia and upload raw response JSON to S3."""
    logger.info("update_adverse_media_result input: task_output=%s", task_output)
    task_output = parse_task_output(task_output)
    if task_output is None:
        logger.error("update_adverse_media_result: task_output is not valid JSON, skipping DB update")
        return

    case_id = task_output.get("case_id")
    name = task_output.get("name", "Unknown")
    result = task_output.get("result")
    summary = task_output.get("summary", "")
    search_queries = task_output.get("searchQueries", [])
    raw = task_output.get("rawResponse", {})
    if not case_id or not result:
        logger.info("Adverse media results incomplete: case_id=%s, result=%s", case_id, result)
        return

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    bucket = os.environ.get("KYC_RESULTS_BUCKET", "kyc-results")
    raw_key = f"cases/{case_id}/adverse-media-report.json"
    report_key = f"cases/{case_id}/adverse-media-report.md"
    raw_s3 = None
    report_s3 = None
    try:
        s3 = boto3.client("s3")
        s3.put_object(
            Bucket=bucket,
            Key=raw_key,
            Body=json.dumps(raw, indent=2, default=str).encode("utf-8"),
            ContentType="application/json",
        )
        raw_s3 = {"bucket": bucket, "key": raw_key}
        logger.info("Adverse media raw response uploaded to s3://%s/%s", bucket, raw_key)

        status_emoji = {"OK": "✅", "NOK": "❌", "PENDING_REVIEW": "⚠️"}
        emoji = status_emoji.get(str(result).upper(), "❓")
        queries_md = ""
        if isinstance(search_queries, list) and search_queries:
            queries_md = "\n".join([f"- `{q}`" for q in search_queries])
        else:
            queries_md = "_No search queries recorded._"

        report_md = "\n".join(
            [
                "# Adverse Media Screening Report",
                "",
                f"**Case ID:** `{case_id}`",
                f"**Subject:** {name}",
                f"**Report generated:** {now}",
                "",
                "---",
                "",
                "## Search queries",
                "",
                queries_md,
                "",
                "---",
                "",
                "## Result",
                "",
                f"**Result:** {emoji} **{str(result).upper()}**",
                "",
                "## Summary",
                "",
                summary or "_No summary available._",
                "",
            ]
        )
        s3.put_object(
            Bucket=bucket,
            Key=report_key,
            Body=report_md.encode("utf-8"),
            ContentType="text/markdown",
        )
        report_s3 = {"bucket": bucket, "key": report_key}
        logger.info("Adverse media markdown report uploaded to s3://%s/%s", bucket, report_key)
    except Exception as e:
        logger.exception("Failed to upload adverse media raw response to S3: %s", e)

    adverse_media = {
        "result": result,
        "summary": summary or "",
        "searchQueries": search_queries if isinstance(search_queries, list) else [],
        "updatedAt": now,
    }
    if raw_s3:
        adverse_media["rawResponseS3"] = raw_s3
    if report_s3:
        adverse_media["reportS3"] = report_s3

    table_name = os.environ.get("KYC_CASES_TABLE", "kyc-cases")
    try:
        dynamodb = boto3.resource("dynamodb")
        table = dynamodb.Table(table_name)
        # ensure stages and screening maps exist
        table.update_item(
            Key={"CaseId": case_id},
            UpdateExpression="SET #stages = if_not_exists(#stages, :empty_map)",
            ExpressionAttributeNames={"#stages": "stages"},
            ExpressionAttributeValues={":empty_map": {}},
        )
        table.update_item(
            Key={"CaseId": case_id},
            UpdateExpression="SET #stages.#screening = if_not_exists(#stages.#screening, :empty_map)",
            ExpressionAttributeNames={"#stages": "stages", "#screening": "screening"},
            ExpressionAttributeValues={":empty_map": {}},
        )
        table.update_item(
            Key={"CaseId": case_id},
            UpdateExpression="SET #stages.#screening.#adv = :adv",
            ExpressionAttributeNames={
                "#stages": "stages",
                "#screening": "screening",
                "#adv": "adverseMedia",
            },
            ExpressionAttributeValues={":adv": adverse_media},
        )
        logger.info("update_adverse_media_result success: case_id=%s, name=%s, result=%s", case_id, name, result)
    except Exception as e:
        logger.exception("update_adverse_media_result error: %s", e)
