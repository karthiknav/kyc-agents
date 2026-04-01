import json
import logging
import os
from datetime import datetime, timezone

import boto3

logger = logging.getLogger(__name__)


def _format_income_report(
    case_id: str,
    name: str,
    verification_result: str,
    income_source: str,
    income_details: dict,
    risk_indicators: list,
    summary: str,
    requires_additional_documents: bool,
    additional_documents_needed: list,
    updated_at: str,
) -> str:
    """Format income verification output as a markdown report."""
    status_emoji = {"VERIFIED": "\u2705", "INSUFFICIENT": "\u26a0\ufe0f", "SUSPICIOUS": "\u274c", "UNREADABLE": "\u2753"}
    emoji = status_emoji.get(verification_result, "\u2753")

    # Income details section
    if income_details and isinstance(income_details, dict):
        employer = income_details.get("employer_or_source", "Unknown")
        monthly = income_details.get("monthly_income_eur", "N/A")
        annual = income_details.get("annual_income_eur", "N/A")
        income_details_md = (
            f"- **Employer / Source:** {employer}\n"
            f"- **Monthly income (EUR):** {monthly}\n"
            f"- **Annual income (EUR):** {annual}\n"
            f"- **Income source type:** {income_source or 'Unknown'}"
        )
    else:
        income_details_md = "_No income details available._"

    # Risk indicators section
    if risk_indicators and isinstance(risk_indicators, list) and len(risk_indicators) > 0:
        risk_md = "\n".join(f"- {r}" for r in risk_indicators)
    else:
        risk_md = "_No risk indicators found._"

    # Additional documents section
    if requires_additional_documents and additional_documents_needed and isinstance(additional_documents_needed, list) and len(additional_documents_needed) > 0:
        additional_docs_md = "\n".join(
            f"- **{d.get('document_type', 'Unknown')}**: {d.get('reason', 'No reason provided')}"
            for d in additional_documents_needed
            if isinstance(d, dict)
        )
    else:
        additional_docs_md = None

    lines = [
        "# KYC Income Verification Report",
        "",
        f"**Case ID:** `{case_id}`",
        f"**Subject:** {name}",
        f"**Report generated:** {updated_at}",
        "",
        "---",
        "",
        "## Income Document Analysis",
        "",
        f"**Result:** {emoji} **{verification_result}**",
        "",
        "---",
        "",
        "## Income Details",
        "",
        income_details_md,
        "",
        "---",
        "",
        "## Risk Assessment",
        "",
        risk_md,
        "",
    ]

    if additional_docs_md:
        lines.extend([
            "---",
            "",
            "## Additional Documents",
            "",
            additional_docs_md,
            "",
        ])

    lines.extend([
        "---",
        "",
        "## Summary",
        "",
        summary or "_No summary available._",
        "",
    ])

    return "\n".join(lines)


def update_income_result(task_output):
    """Update the incomeVerification stage in the case document and notify the orchestrator."""
    logger.info("update_income_result input: task_output=%s", task_output)
    if hasattr(task_output, "raw"):
        task_output = task_output.raw
    if isinstance(task_output, str):
        try:
            task_output = json.loads(task_output)
        except json.JSONDecodeError:
            logger.error("update_income_result: task_output is not valid JSON")
            return
    case_id = task_output.get("case_id")
    name = task_output.get("name", "Unknown")
    verification_result = task_output.get("verification_result")
    income_source = task_output.get("income_source", "unknown")
    income_details = task_output.get("income_details")
    risk_indicators = task_output.get("risk_indicators", [])
    summary = task_output.get("summary", "")
    requires_additional_documents = task_output.get("requires_additional_documents", False)
    additional_documents_needed = task_output.get("additional_documents_needed", [])

    if not case_id or not verification_result:
        logger.info(
            "Results incomplete: case_id=%s, verification_result=%s",
            case_id, verification_result,
        )
        return

    # Normalise verification_result to canonical values
    result_map = {
        "verified": "VERIFIED",
        "insufficient": "INSUFFICIENT",
        "suspicious": "SUSPICIOUS",
        "unreadable": "UNREADABLE",
        "VERIFIED": "VERIFIED",
        "INSUFFICIENT": "INSUFFICIENT",
        "SUSPICIOUS": "SUSPICIOUS",
        "UNREADABLE": "UNREADABLE",
    }
    status = result_map.get(str(verification_result), "INSUFFICIENT")

    if not isinstance(risk_indicators, list):
        risk_indicators = [str(risk_indicators)] if risk_indicators else []
    if not isinstance(additional_documents_needed, list):
        additional_documents_needed = []

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    report_md = _format_income_report(
        case_id=case_id,
        name=name,
        verification_result=status,
        income_source=income_source,
        income_details=income_details,
        risk_indicators=risk_indicators,
        summary=summary,
        requires_additional_documents=requires_additional_documents,
        additional_documents_needed=additional_documents_needed,
        updated_at=now,
    )

    # Upload report to S3
    report_s3 = None
    bucket = os.environ.get("KYC_RESULTS_BUCKET", "kyc-results")
    report_key = f"cases/{case_id}/income-verification-report.md"
    try:
        s3 = boto3.client("s3")
        s3.put_object(
            Bucket=bucket,
            Key=report_key,
            Body=report_md.encode("utf-8"),
            ContentType="text/markdown",
        )
        report_s3 = {"bucket": bucket, "key": report_key}
        logger.info("Income verification report uploaded to s3://%s/%s", bucket, report_key)
    except Exception as e:
        logger.exception("Failed to upload income verification report to S3: %s", e)

    # Build the incomeVerification stage object
    income_stage = {
        "result": status,
        "incomeSource": income_source,
        "monthlyIncomeEur": income_details.get("monthly_income_eur") if income_details else None,
        "nameMatch": task_output.get("name_match"),
        "riskIndicators": risk_indicators if isinstance(risk_indicators, list) else [],
        "summary": summary,
        "requiresAdditionalDocuments": requires_additional_documents,
        "additionalDocumentsNeeded": additional_documents_needed if isinstance(additional_documents_needed, list) else [],
        "updatedAt": now,
    }
    if report_s3:
        income_stage["reportS3"] = report_s3

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
        # Step 2: write incomeVerification stage
        table.update_item(
            Key={"CaseId": case_id},
            UpdateExpression="SET #stages.#incomeVerification = :incomeVerification",
            ExpressionAttributeNames={
                "#stages": "stages",
                "#incomeVerification": "incomeVerification",
            },
            ExpressionAttributeValues={":incomeVerification": income_stage},
        )
    except Exception as e:
        logger.exception("update_income_result DynamoDB error: %s", e)
        return

    # Online evals: schema validation
    try:
        from crew.evals.online import run_online_evals
        run_online_evals(stage="income", task_output=task_output)
    except Exception:
        logger.debug("Online eval scoring skipped (income)", exc_info=True)
