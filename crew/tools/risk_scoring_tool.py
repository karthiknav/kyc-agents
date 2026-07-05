"""Tool to score a KYC case using the deployed XGBoost risk-scoring endpoint."""

import json
import logging
import os
import threading
import uuid
from typing import Type

import boto3
from crewai.tools import BaseTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# ── Country risk tiers ────────────────────────────────────────────────────────
# Simplified FATF-aligned grouping.  Extend as needed.
_HIGH_RISK_NATIONALITIES = {
    "AF", "BY", "CF", "CD", "CU", "ER", "IR", "IQ", "KP", "LB",
    "LY", "ML", "MM", "NI", "RU", "SO", "SS", "SD", "SY", "VE",
    "YE", "ZW",
}
_MEDIUM_HIGH_RISK = {
    "AL", "BB", "BF", "CM", "GH", "GY", "HT", "JM", "JO", "KE",
    "MA", "MZ", "MU", "NG", "PA", "PK", "PH", "SN", "TZ", "TN",
    "TR", "UA", "UG",
}

def _country_risk_tier(nationality: str) -> int:
    code = (nationality or "").strip().upper()
    if code in _HIGH_RISK_NATIONALITIES:
        return 5
    if code in _MEDIUM_HIGH_RISK:
        return 3
    return 2  # default: medium-low

# ── Feature encoding (must match sagemaker/scripts/preprocess.py) ─────────────
_PEP_TYPE_MAP = {"none": 0, "fuzzy": 1, "exact": 2}
_DOC_STATUS_MAP = {"failed": 0, "unreadable": 1, "verified": 2}
_ADVERSE_SEV_MAP = {"none": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}

FEATURE_ORDER = [
    "pep_match_score",
    "sanctions_hit",
    "doc_authenticity_score",
    "adverse_media_hits",
    "adverse_media_severity",
    "pep_match_type",
    "doc_status",
    "country_risk_tier",
]
LABEL_NAMES = ["low", "medium", "high"]

# ── Thread-local nonce for guardrail ─────────────────────────────────────────
_scoring_state = threading.local()


def get_last_scoring_id() -> str | None:
    return getattr(_scoring_state, "scoring_id", None)


def reset_scoring_state() -> None:
    _scoring_state.scoring_id = None


# ── Feature extraction ────────────────────────────────────────────────────────

def _extract_features(case: dict) -> dict:
    """
    Map DynamoDB case + stages to the 8 feature values expected by the model.

    The KYC case schema stores coarse categorical results (MATCH/CLEAR/OK …).
    This function converts them to numeric features using the same encoding
    as sagemaker/scripts/preprocess.py.  Where the original numeric score is
    not stored (e.g. pep_match_score, doc_authenticity_score), conservative
    approximations are used and documented.
    """
    identity = case.get("identity") or {}
    stages = case.get("stages") or {}
    doc_stage = stages.get("documentProcessing") or {}
    screening = stages.get("screening") or {}
    risk_stage = screening.get("riskListScreening") or {}
    media_stage = screening.get("adverseMedia") or {}

    # ── Document ─────────────────────────────────────────────────────────────
    doc_result = (doc_stage.get("result") or "MISMATCH").upper()
    if doc_result == "MATCH":
        doc_status = 2        # verified
        doc_auth_score = 95.0
    elif doc_result == "PARTIAL_MATCH":
        doc_status = 1        # unreadable (closest approximation for partial)
        doc_auth_score = 50.0
    else:
        doc_status = 0        # failed
        doc_auth_score = 0.0

    # ── PEP / Sanctions ──────────────────────────────────────────────────────
    risk_result = (risk_stage.get("result") or "ERROR").upper()
    pep_status = (risk_stage.get("pepStatus") or "NOT_PEP").upper()
    sanctions_status = (risk_stage.get("sanctionsStatus") or "NOT_SANCTIONED").upper()

    sanctions_hit = 1 if sanctions_status == "SANCTIONED" else 0

    # pep_match_type / pep_match_score — not stored in current schema;
    # approximate from coarse pepStatus.
    if pep_status == "PEP":
        pep_match_type = 2    # exact (worst case)
        pep_match_score = 80.0
    elif risk_result == "HIT":
        pep_match_type = 1    # fuzzy
        pep_match_score = 50.0
    else:
        pep_match_type = 0    # none
        pep_match_score = 0.0

    # ── Adverse media ────────────────────────────────────────────────────────
    media_result = (media_stage.get("result") or "PENDING_REVIEW").upper()
    if media_result == "OK":
        adverse_media_hits = 0
        adverse_media_sev = 0
    elif media_result == "NOK":
        adverse_media_hits = 5   # conservative estimate
        adverse_media_sev = 3    # high
    else:  # PENDING_REVIEW / unknown
        adverse_media_hits = 2
        adverse_media_sev = 2    # medium

    # ── Country ──────────────────────────────────────────────────────────────
    nationality = identity.get("nationality") or ""
    country_tier = _country_risk_tier(nationality)

    return {
        "pep_match_score": pep_match_score,
        "sanctions_hit": sanctions_hit,
        "doc_authenticity_score": doc_auth_score,
        "adverse_media_hits": adverse_media_hits,
        "adverse_media_severity": adverse_media_sev,
        "pep_match_type": pep_match_type,
        "doc_status": doc_status,
        "country_risk_tier": country_tier,
    }


# ── Tool ─────────────────────────────────────────────────────────────────────

class RiskScoringInput(BaseModel):
    case_id: str = Field(description="The KYC case ID to score.")


class RiskScoringTool(BaseTool):
    """
    Score a KYC case using the deployed XGBoost risk-scoring model.

    Reads case stages from DynamoDB (populated by the previous three agents),
    builds the 8-feature vector, calls the SageMaker endpoint, and returns
    risk_tier (low/medium/high), a confidence score (0–100), and the per-class
    probabilities.

    Requires env var: RISK_SCORER_ENDPOINT_NAME
    """

    name: str = "score_case_risk"
    description: str = (
        "Derives a machine-learning risk score from the case screening results "
        "(document, PEP/sanctions, adverse media) produced by the earlier agents. "
        "Returns risk_tier (low | medium | high), confidence (0-100), and "
        "per-class probabilities. Use this BEFORE making the final decision."
    )
    args_schema: Type[RiskScoringInput] = RiskScoringInput

    def _run(self, case_id: str) -> str:
        if not case_id or not case_id.strip():
            return json.dumps({"error": "case_id is required"})

        endpoint_name = os.environ.get("RISK_SCORER_ENDPOINT_NAME", "").strip()
        if not endpoint_name:
            return json.dumps({
                "error": "RISK_SCORER_ENDPOINT_NAME env var is not set — endpoint not deployed yet",
                "case_id": case_id,
            })

        # Issue nonce so the guardrail can confirm this tool ran
        scoring_id = str(uuid.uuid4())
        _scoring_state.scoring_id = scoring_id

        try:
            case = self._fetch_case(case_id)
        except Exception as e:
            logger.exception("risk_scoring: failed to fetch case %s", case_id)
            return json.dumps({"error": f"DynamoDB fetch failed: {e}", "case_id": case_id})

        features = _extract_features(case)
        csv_row = ",".join(str(features[f]) for f in FEATURE_ORDER)

        try:
            probabilities = self._invoke_endpoint(endpoint_name, csv_row)
        except Exception as e:
            logger.exception("risk_scoring: endpoint invocation failed for case %s", case_id)
            return json.dumps({"error": f"Endpoint call failed: {e}", "case_id": case_id})

        predicted_idx = probabilities.index(max(probabilities))
        risk_tier = LABEL_NAMES[predicted_idx]
        confidence = round(probabilities[predicted_idx] * 100, 1)

        result = {
            "scoring_id": scoring_id,
            "case_id": case_id,
            "risk_tier": risk_tier,
            "confidence": confidence,
            "probabilities": {
                LABEL_NAMES[i]: round(probabilities[i] * 100, 1)
                for i in range(3)
            },
            "features_used": features,
        }
        logger.info(
            "risk_scoring: case=%s  tier=%s  confidence=%.1f%%",
            case_id, risk_tier, confidence,
        )
        return json.dumps(result, indent=2, default=str)

    @staticmethod
    def _fetch_case(case_id: str) -> dict:
        table_name = os.environ.get("KYC_CASES_TABLE", "kyc-cases")
        table = boto3.resource("dynamodb").Table(table_name)
        response = table.get_item(Key={"CaseId": case_id})
        item = response.get("Item")
        if not item:
            raise ValueError(f"No case found for caseId {case_id}")
        return item

    @staticmethod
    def _invoke_endpoint(endpoint_name: str, csv_row: str) -> list[float]:
        region = os.environ.get("AWS_REGION", "us-east-1")
        rt = boto3.client("sagemaker-runtime", region_name=region)
        response = rt.invoke_endpoint(
            EndpointName=endpoint_name,
            ContentType="text/csv",
            Body=csv_row,
        )
        raw = response["Body"].read().decode().strip()
        # multi:softprob returns space or comma-separated probabilities
        sep = "," if "," in raw else " "
        return [float(x) for x in raw.split(sep)]
