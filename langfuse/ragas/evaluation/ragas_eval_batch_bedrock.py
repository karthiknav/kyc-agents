"""
Batch RAGAS evaluation for KYC cases stored in DynamoDB + artifacts in S3.

Goal
----
Make the script runnable WITHOUT manual `export ...` by supporting:
  1) Environment variables (highest priority)
  2) Local config file: ragas_config.json (next to this script)
  3) Safe defaults for region + model IDs

We intentionally DO NOT hardcode your bucket/table as code defaults because those are
environment-specific and can cause accidental production access.

Compatible with:
  - ragas==0.4.3 (Faithfulness must be constructed with llm=...)
  - AWS Bedrock via langchain_aws.ChatBedrock + BedrockEmbeddings

Outputs (always written)
------------------------
../output/ragas_results.csv
../output/pipeline_missing.csv

Config sources
--------------
Environment variables (override everything):
  KYC_RESULTS_BUCKET
  KYC_CASES_TABLE
  AWS_REGION (default: us-east-1)
  AWS_PROFILE (optional)
  MAX_CASES (default: 100)
  CASE_IDS (optional: comma separated)
  S3_MAX_BYTES (default: 250000)
  RAGAS_EVAL_BEDROCK_MODEL_ID (default: amazon.nova-pro-v1:0)
  RAGAS_EVAL_BEDROCK_EMBEDDING_MODEL_ID (default: amazon.titan-embed-text-v2:0)

Local config file (optional):
  ragas_config.json next to this script with keys:
    aws_region
    aws_profile
    kyc_results_bucket
    kyc_cases_table
    max_cases
    case_ids
    s3_max_bytes
    ragas_eval_bedrock_model_id
    ragas_eval_bedrock_embedding_model_id
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional, Tuple

import boto3
import pandas as pd
from boto3.dynamodb.conditions import Attr
from botocore.exceptions import ClientError
from datasets import Dataset
from langchain_aws import BedrockEmbeddings, ChatBedrock
from ragas import evaluate
from ragas.metrics._answer_relevance import AnswerRelevancy
from ragas.metrics._faithfulness import Faithfulness


# -------------------------------
# Configuration
# -------------------------------

DEFAULT_AWS_REGION = "us-east-1"
DEFAULT_MAX_CASES = 100
DEFAULT_S3_MAX_BYTES = 250_000

# Use models that are commonly available in more AWS accounts.
DEFAULT_EVALUATOR_MODEL_ID = "amazon.nova-pro-v1:0"
DEFAULT_EMBEDDING_MODEL_ID = "amazon.titan-embed-text-v2:0"


def _script_dir() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def _output_dir() -> str:
    # ../output relative to this script
    return os.path.abspath(os.path.join(_script_dir(), "..", "output"))


def load_local_config() -> Dict[str, Any]:
    """
    Optional config file next to this script:
      ragas_config.json

    Example:
    {
      "aws_region": "us-east-1",
      "kyc_results_bucket": "your-bucket",
      "kyc_cases_table": "your-table",
      "ragas_eval_bedrock_model_id": "amazon.nova-pro-v1:0",
      "ragas_eval_bedrock_embedding_model_id": "amazon.titan-embed-text-v2:0",
      "max_cases": 100,
      "s3_max_bytes": 250000
    }
    """
    path = os.path.join(_script_dir(), "ragas_config.json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        # keep it non-fatal; we'll validate required settings later
        return {}


def _get_str(env_key: str, cfg: Dict[str, Any], cfg_key: str, default: str = "") -> str:
    v = os.environ.get(env_key)
    if v is not None and str(v).strip():
        return str(v).strip()
    cv = cfg.get(cfg_key)
    if cv is not None and str(cv).strip():
        return str(cv).strip()
    return default


def _get_int(env_key: str, cfg: Dict[str, Any], cfg_key: str, default: int) -> int:
    v = os.environ.get(env_key)
    if v is not None and str(v).strip():
        try:
            return int(str(v).strip())
        except ValueError:
            return default
    cv = cfg.get(cfg_key)
    if cv is not None and str(cv).strip():
        try:
            return int(str(cv).strip())
        except ValueError:
            return default
    return default


def _get_list_csv(env_key: str, cfg: Dict[str, Any], cfg_key: str) -> Optional[List[str]]:
    """
    Supports:
      - env var CASE_IDS="A,B,C"
      - config file case_ids can be list ["A","B"] or a CSV string "A,B"
    """
    raw = os.environ.get(env_key)
    if raw is not None and str(raw).strip():
        parts = [p.strip() for p in str(raw).split(",")]
        parts = [p for p in parts if p]
        return parts or None

    cv = cfg.get(cfg_key)
    if cv is None:
        return None
    if isinstance(cv, list):
        parts = [str(x).strip() for x in cv]
        parts = [p for p in parts if p]
        return parts or None
    if isinstance(cv, str) and cv.strip():
        parts = [p.strip() for p in cv.split(",")]
        parts = [p for p in parts if p]
        return parts or None

    return None


def resolve_settings() -> Dict[str, Any]:
    cfg = load_local_config()

    aws_region = _get_str("AWS_REGION", cfg, "aws_region", DEFAULT_AWS_REGION)
    aws_profile = _get_str("AWS_PROFILE", cfg, "aws_profile", default="") or None

    bucket = _get_str("KYC_RESULTS_BUCKET", cfg, "kyc_results_bucket", default="")
    table_name = _get_str("KYC_CASES_TABLE", cfg, "kyc_cases_table", default="")

    max_cases = _get_int("MAX_CASES", cfg, "max_cases", DEFAULT_MAX_CASES)
    s3_max_bytes = _get_int("S3_MAX_BYTES", cfg, "s3_max_bytes", DEFAULT_S3_MAX_BYTES)
    case_ids = _get_list_csv("CASE_IDS", cfg, "case_ids")

    evaluator_model_id = _get_str(
        "RAGAS_EVAL_BEDROCK_MODEL_ID",
        cfg,
        "ragas_eval_bedrock_model_id",
        DEFAULT_EVALUATOR_MODEL_ID,
    )

    embedding_model_id = _get_str(
        "RAGAS_EVAL_BEDROCK_EMBEDDING_MODEL_ID",
        cfg,
        "ragas_eval_bedrock_embedding_model_id",
        DEFAULT_EMBEDDING_MODEL_ID,
    )

    missing = []
    if not bucket:
        missing.append("KYC_RESULTS_BUCKET (or ragas_config.json: kyc_results_bucket)")
    if not table_name:
        missing.append("KYC_CASES_TABLE (or ragas_config.json: kyc_cases_table)")

    if missing:
        raise SystemExit(
            "Missing required configuration:\n"
            + "\n".join([f"  - {m}" for m in missing])
            + "\n\nFix options:\n"
            + "  1) Export env vars:\n"
            + "     export KYC_RESULTS_BUCKET='...'\n"
            + "     export KYC_CASES_TABLE='...'\n"
            + "  2) Create ragas_config.json next to this script with keys:\n"
            + "     kyc_results_bucket, kyc_cases_table\n"
        )

    return {
        "aws_region": aws_region,
        "aws_profile": aws_profile,
        "bucket": bucket,
        "table_name": table_name,
        "max_cases": max_cases,
        "case_ids": case_ids,
        "s3_max_bytes": s3_max_bytes,
        "evaluator_model_id": evaluator_model_id,
        "embedding_model_id": embedding_model_id,
    }


# -------------------------------
# AWS helpers
# -------------------------------

def build_session(aws_region: str, aws_profile: Optional[str]) -> boto3.Session:
    """Create boto3 session using AWS_PROFILE (optional) and explicit region."""
    return boto3.Session(profile_name=aws_profile, region_name=aws_region)


def ddb_scan_cases(
    session: boto3.Session,
    table_name: str,
    max_items: int = 100,
    case_ids: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """
    Scan DDB for items where stages.orchestrator exists.
    Pagination supported. Optional client-side filter by case id.
    """
    ddb = session.resource("dynamodb")
    table = ddb.Table(table_name)

    filter_expr = Attr("stages.orchestrator").exists()

    items: List[Dict[str, Any]] = []
    scan_kwargs: Dict[str, Any] = {"FilterExpression": filter_expr}

    last_evaluated_key = None
    wanted = set(case_ids) if case_ids else None

    while True:
        if last_evaluated_key:
            scan_kwargs["ExclusiveStartKey"] = last_evaluated_key

        resp = table.scan(**scan_kwargs)
        batch = resp.get("Items", [])

        if wanted is not None:
            filtered = []
            for it in batch:
                cid = str(it.get("CaseId") or it.get("caseId") or "")
                if cid and cid in wanted:
                    filtered.append(it)
            batch = filtered

        items.extend(batch)
        if len(items) >= max_items:
            break

        last_evaluated_key = resp.get("LastEvaluatedKey")
        if not last_evaluated_key:
            break

    return items[:max_items]


def s3_read_text(session: boto3.Session, bucket: str, key: str, max_bytes: int) -> str:
    """
    Read up to max_bytes from S3, decode utf-8 (replacement).
    If object is larger, Range header caps download size.
    """
    s3 = session.client("s3")
    range_header = f"bytes=0-{max_bytes - 1}" if max_bytes and max_bytes > 0 else None

    if range_header:
        obj = s3.get_object(Bucket=bucket, Key=key, Range=range_header)
    else:
        obj = s3.get_object(Bucket=bucket, Key=key)

    data = obj["Body"].read()
    return data.decode("utf-8", errors="replace")


def s3_try_read_text(session: boto3.Session, bucket: str, key: str, max_bytes: int) -> Optional[str]:
    """Return None for missing key/bucket or access denied; re-raise other errors."""
    try:
        return s3_read_text(session, bucket, key, max_bytes=max_bytes)
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        if code in ("NoSuchKey", "NoSuchBucket", "404", "AccessDenied"):
            return None
        raise


# -------------------------------
# Case shaping helpers
# -------------------------------

def case_artifact_keys(case_id: str) -> Tuple[str, str, str]:
    return (
        f"cases/{case_id}/document-processing-report.md",
        f"cases/{case_id}/risk-list-report.json",
        f"cases/{case_id}/adverse-media-report.md",
    )


def build_answer_from_orchestrator(item: Dict[str, Any]) -> str:
    stages = item.get("stages", {}) or {}
    orch = stages.get("orchestrator", {}) or {}

    decision = orch.get("decision") or ""
    summary = orch.get("recommendation_summary") or ""
    reasons = orch.get("reason", [])

    if isinstance(reasons, list):
        reasons_list = [str(r) for r in reasons if r is not None and str(r).strip()]
    elif isinstance(reasons, str):
        reasons_list = [reasons] if reasons.strip() else []
    elif reasons:
        reasons_list = [str(reasons)]
    else:
        reasons_list = []

    parts: List[str] = []
    if decision:
        parts.append(f"Decision: {decision}")
    if summary:
        parts.append(f"Summary: {summary}")
    if reasons_list:
        parts.append("Reasons:")
        parts.extend([f"- {r}" for r in reasons_list])

    return "\n".join(parts).strip() or json.dumps(orch, indent=2)


# -------------------------------
# Main
# -------------------------------

def main() -> None:
    settings = resolve_settings()

    aws_region: str = settings["aws_region"]
    aws_profile: Optional[str] = settings["aws_profile"]
    bucket: str = settings["bucket"]
    table_name: str = settings["table_name"]
    max_cases: int = settings["max_cases"]
    case_ids: Optional[List[str]] = settings["case_ids"]
    s3_max_bytes: int = settings["s3_max_bytes"]
    evaluator_model_id: str = settings["evaluator_model_id"]
    embedding_model_id: str = settings["embedding_model_id"]

    output_dir = _output_dir()
    os.makedirs(output_dir, exist_ok=True)

    print(f"Saving results to: {output_dir}")
    print(f"Scanning DynamoDB: table={table_name} region={aws_region} max_cases={max_cases}")
    if case_ids:
        print(f"CASE_IDS filter enabled: {case_ids}")
    print(f"S3 bucket: {bucket}")
    print(f"Bedrock evaluator model: {evaluator_model_id}")
    print(f"Bedrock embedding model: {embedding_model_id}")

    session = build_session(aws_region=aws_region, aws_profile=aws_profile)

    # 1) Discover cases
    items = ddb_scan_cases(session, table_name, max_items=max_cases, case_ids=case_ids)

    if not items:
        print("No cases found with stages.orchestrator (or none matched CASE_IDS). Writing empty CSVs.")
        pd.DataFrame().to_csv(os.path.join(output_dir, "ragas_results.csv"), index=False)
        pd.DataFrame().to_csv(os.path.join(output_dir, "pipeline_missing.csv"), index=False)
        return

    ragas_rows: List[Dict[str, Any]] = []
    pipeline_missing_rows: List[Dict[str, Any]] = []

    # 2) Build dataset rows
    for item in items:
        case_id = str(item.get("CaseId") or item.get("caseId") or "")
        if not case_id:
            continue

        doc_key, risk_key, adv_key = case_artifact_keys(case_id)

        doc_context = s3_try_read_text(session, bucket, doc_key, max_bytes=s3_max_bytes)
        risk_context = s3_try_read_text(session, bucket, risk_key, max_bytes=s3_max_bytes)
        adv_context = s3_try_read_text(session, bucket, adv_key, max_bytes=s3_max_bytes)

        missing: List[str] = []
        if not doc_context:
            missing.append("document-processing-report.md")
        if not risk_context:
            missing.append("risk-list-report.json")
        if not adv_context:
            missing.append("adverse-media-report.md")

        pipeline_missing_rows.append(
            {
                "case_id": case_id,
                "missing_artifacts": ", ".join(missing),
                "has_any_artifact": len(missing) < 3,
                "has_all_artifacts": len(missing) == 0,
            }
        )

        # Skip evaluation if no context at all
        if len(missing) == 3:
            continue

        contexts = [c for c in (doc_context, risk_context, adv_context) if c]
        answer = build_answer_from_orchestrator(item)

        question = (
            f"Using ONLY the available KYC reports for case {case_id}, decide "
            f"APPROVE or ESCALATE and justify your decision using only the provided evidence."
        )

        ragas_rows.append(
            {
                "case_id": case_id,
                "question": question,
                "answer": answer,
                "contexts": contexts,
                "missing_artifacts": ", ".join(missing),
            }
        )

    # 3) Evaluate via RAGAS (Bedrock LLM + Bedrock embeddings)
    if ragas_rows:
        evaluator_llm = ChatBedrock(
            model_id=evaluator_model_id,
            region_name=aws_region,
            model_kwargs={"temperature": 0},
        )
        embeddings = BedrockEmbeddings(
            model_id=embedding_model_id,
            region_name=aws_region,
        )

        ds = Dataset.from_list(
            [{"question": r["question"], "answer": r["answer"], "contexts": r["contexts"]} for r in ragas_rows]
        )

        # ragas==0.4.3 requires llm passed into Faithfulness.
        metrics = [
            Faithfulness(llm=evaluator_llm),
            AnswerRelevancy(),
        ]

        print(f"Evaluating {len(ds)} cases with metrics: {[m.name for m in metrics]}")

        results = evaluate(ds, metrics=metrics, llm=evaluator_llm, embeddings=embeddings)

        df_ragas = results.to_pandas()
        df_ragas.insert(0, "case_id", [r["case_id"] for r in ragas_rows])
        df_ragas.insert(1, "missing_artifacts", [r["missing_artifacts"] for r in ragas_rows])
    else:
        print("No evaluable cases (all missing artifacts). Writing empty ragas_results.csv.")
        df_ragas = pd.DataFrame(columns=["case_id", "missing_artifacts", "faithfulness", "answer_relevancy"])

    # 4) Save outputs always
    df_pipeline = pd.DataFrame(pipeline_missing_rows)

    ragas_path = os.path.join(output_dir, "ragas_results.csv")
    pipeline_path = os.path.join(output_dir, "pipeline_missing.csv")

    df_ragas.to_csv(ragas_path, index=False)
    df_pipeline.to_csv(pipeline_path, index=False)

    print("\nSaved:")
    print(f"  {ragas_path}")
    print(f"  {pipeline_path}")
    print(f"Evaluated cases: {len(df_ragas)} | Total discovered: {len(items)}")


if __name__ == "__main__":
    main()
