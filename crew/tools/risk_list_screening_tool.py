"""Tool to screen a person against risk lists (PEP/sanctions API)."""
import json
import logging
import os
import re
import threading
import uuid
from typing import List, Optional, Type, Tuple

import requests
from crewai.tools import BaseTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

MOCK_SERVICE_URL_DEFAULT = "http://localhost:9000"
PEP_PATH = "/api/v1/pep/match"

_screening_state = threading.local()


def get_last_screening_id() -> str | None:
    return getattr(_screening_state, "screening_id", None)


def get_last_screening_result() -> dict | None:
    return getattr(_screening_state, "last_result", None)


def reset_screening_state() -> None:
    _screening_state.screening_id = None
    _screening_state.last_result = None


def _join_url(base: str, path: str) -> str:
    return base.rstrip("/") + path


class RiskListScreeningInput(BaseModel):
    case_details: str = Field(
        description="JSON string from get_case_details (must include identity.fullName; identity.dateOfBirth and identity.nationality optional)."
    )


def _split_name(full_name: str) -> Tuple[str, str]:
    parts = full_name.split(None, 1)
    first_name = parts[0] if parts else full_name
    last_name = parts[1] if len(parts) > 1 else parts[0]
    return first_name, last_name


def _extract_birth_year(date_str: Optional[str]) -> Optional[str]:
    if not date_str:
        return None
    match = re.search(r"\d{4}", str(date_str))
    return match.group(0) if match else None


class RiskListScreeningTool(BaseTool):
    """Run risk list screening against PEP/sanctions API and return normalized statuses."""

    name: str = "risk_list_screening"
    description: str = (
        "Call the risk list screening API (OpenSanctions-style match endpoint). "
        "Use get_case_details first, then pass its JSON here. "
        "Returns a normalized object with result (CLEAR/HIT/ERROR), pepStatus, sanctionsStatus, "
        "datasetsMatched, and summary plus the raw API response."
    )
    args_schema: Type[RiskListScreeningInput] = RiskListScreeningInput

    def _run(self, case_details: str) -> str:
        # Backward compatible override: allow setting a full PEP endpoint URL
        explicit = (os.environ.get("PEP_API_URL") or "").strip()
        if explicit:
            api_url = explicit
        else:
            base_url = (os.environ.get("MOCK_SERVICE_URL") or "").strip() or MOCK_SERVICE_URL_DEFAULT
            api_url = _join_url(base_url, PEP_PATH)

        if not case_details or not case_details.strip():
            return json.dumps({"error": "case_details is required"})

        try:
            case = json.loads(case_details) if isinstance(case_details, str) else case_details
        except json.JSONDecodeError:
            return json.dumps({"error": "Invalid case_details JSON"})

        identity = case.get("identity") or {}
        if not isinstance(identity, dict):
            identity = {}
        full_name = (identity.get("fullName") or "").strip()
        if not full_name:
            return json.dumps({"error": "identity.fullName is required"})

        first_name, last_name = _split_name(full_name)
        birth_year = _extract_birth_year(identity.get("dateOfBirth"))
        nationality = (identity.get("nationality") or "").strip()

        # Issue nonce before the API call so the guardrail can verify this tool ran.
        screening_id = str(uuid.uuid4())
        _screening_state.screening_id = screening_id

        # OpenSanctions-style query: schema + multi-valued properties (arrays)
        properties = {
            "firstName": [first_name],
            "lastName": [last_name],
        }
        if birth_year:
            properties["birthDate"] = [birth_year]
        if nationality:
            properties["nationality"] = [nationality]

        payload = {"queries": {"q1": {"schema": "Person", "properties": properties}}}

        logger.info("risk_list_screening_update: caseId=%s, name=%s, url=%s", case.get("caseId"), full_name, api_url)
        try:
            resp = requests.post(api_url, json=payload, timeout=30)
            resp.raise_for_status()
            raw = resp.json()
        except requests.RequestException as e:
            logger.exception("risk_list_screening API request failed: %s", e)
            err_result = {
                "screening_id": screening_id,
                "case_id": case.get("caseId") or case.get("case_id"),
                "name": full_name,
                "result": "ERROR",
                "pepStatus": "UNKNOWN",
                "sanctionsStatus": "UNKNOWN",
                "datasetsMatched": [],
                "summary": "Risk list screening failed (PEP API call error).",
                "rawResponse": {"error": str(e)},
            }
            _screening_state.last_result = err_result
            return json.dumps(err_result, indent=2, default=str)

        results = []
        try:
            results = ((raw.get("responses") or {}).get("q1") or {}).get("results") or []
        except (TypeError, AttributeError):
            results = []

        datasets: List[str] = []
        for r in results:
            ds = r.get("datasets") or []
            if isinstance(ds, list):
                datasets.extend([d for d in ds if isinstance(d, str)])
            elif isinstance(ds, str):
                datasets.append(ds)

        datasets_norm = sorted({d for d in datasets if d})
        has_sanctions = any("sanction" in d.lower() for d in datasets_norm)
        has_pep = any("pep" in d.lower() for d in datasets_norm)

        sanctions_status = "SANCTIONED" if has_sanctions else "NOT_SANCTIONED"
        pep_status = "PEP" if has_pep else "NOT_PEP"

        if datasets_norm:
            result = "HIT"
            if has_sanctions:
                summary = f"Sanctions match found (datasets: {', '.join(datasets_norm)})."
            elif has_pep:
                summary = f"PEP match found (datasets: {', '.join(datasets_norm)})."
            else:
                summary = f"Risk list match found (datasets: {', '.join(datasets_norm)})."
        else:
            result = "CLEAR"
            summary = "No matches found across sanctions, PEP, or high-risk watchlists."

        out = {
            "screening_id": screening_id,
            "case_id": case.get("caseId") or case.get("case_id"),
            "name": full_name,
            "result": result,
            "pepStatus": pep_status,
            "sanctionsStatus": sanctions_status,
            "datasetsMatched": datasets_norm,
            "summary": summary,
            "rawResponse": raw,
        }
        _screening_state.last_result = out
        return json.dumps(out, indent=2, default=str)

