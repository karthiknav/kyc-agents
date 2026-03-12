"""Tool to screen a person against the PEP/sanctions API (OpenSanctions-style)."""
import json
import logging
import os
import re
from typing import Type

import requests
from crewai.tools import BaseTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

MOCK_SERVICE_URL_DEFAULT = "http://localhost:9000"
PEP_PATH = "/api/v1/pep/match"


def _join_url(base: str, path: str) -> str:
    return base.rstrip("/") + path


class PepScreeningInput(BaseModel):
    case_details: str = Field(
        description="JSON string of case details from get_case_details (must include identity.fullName; identity.dateOfBirth and identity.nationality optional)."
    )


class PepScreeningTool(BaseTool):
    """Screen a person against the PEP/sanctions API. Call this before web search. Returns severity (HIGH if sanctions, MEDIUM if PEP only) and a summary of matches."""

    name: str = "pep_screening"
    description: str = (
        "Screen the person from case details against the PEP/sanctions API (OpenSanctions-style). "
        "Use get_case_details first, then pass the result here. Builds a Person query from identity.fullName, "
        "dateOfBirth, and nationality. Returns severity (HIGH if any result has sanctions dataset, "
        "MEDIUM if only PEP datasets, none if no results), pep_summary, and the raw match results. "
        "Always call this before search_internet; then pass pep_results to produce_screening_analysis."
    )
    args_schema: Type[PepScreeningInput] = PepScreeningInput

    def _run(self, case_details: str) -> str:
        """Call PEP API and return severity + summary."""
        # Backward compatible override: allow setting a full PEP endpoint URL
        explicit = (os.environ.get("PEP_API_URL") or "").strip()
        if explicit:
            api_url = explicit
        else:
            base_url = (os.environ.get("MOCK_SERVICE_URL") or "").strip() or MOCK_SERVICE_URL_DEFAULT
            api_url = _join_url(base_url, PEP_PATH)

        if not case_details or not case_details.strip():
            return json.dumps({"error": "case_details is required", "severity": None, "pep_summary": ""})

        try:
            case = json.loads(case_details) if isinstance(case_details, str) else case_details
        except json.JSONDecodeError:
            return json.dumps({"error": "Invalid case_details JSON", "severity": None, "pep_summary": ""})

        identity = case.get("identity") or {}
        if not isinstance(identity, dict):
            identity = {}
        full_name = (identity.get("fullName") or "Unknown").strip()
        if full_name == "Unknown" or not full_name:
            return json.dumps({"error": "identity.fullName is required", "severity": None, "pep_summary": ""})

        # Split fullName into first and last (simple: first word = first name, rest = last name)
        parts = full_name.split(None, 1)
        first_name = parts[0] if parts else full_name
        last_name = parts[1] if len(parts) > 1 else parts[0]
        birth = identity.get("dateOfBirth")
        nationality = identity.get("nationality") or ""

        # Build OpenSanctions-style query (properties as arrays)
        birth_year = None
        if birth:
            match = re.search(r"\d{4}", str(birth))
            if match:
                birth_year = match.group(0)
        payload = {
            "queries": {
                "q1": {
                    "schema": "Person",
                    "properties": {
                        "firstName": [first_name],
                        "lastName": [last_name],
                        "birthDate": [birth_year] if birth_year else [],
                        "nationality": [nationality] if nationality else [],
                    },
                }
            }
        }
        # Remove empty arrays so API accepts
        payload["queries"]["q1"]["properties"] = {
            k: v for k, v in payload["queries"]["q1"]["properties"].items() if v
        }

        logger.info("pep_screening: name=%s, url=%s", full_name, api_url)
        try:
            response = requests.post(api_url, json=payload, timeout=30)
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as e:
            logger.exception("PEP API request failed: %s", e)
            return json.dumps({
                "error": str(e),
                "severity": None,
                "pep_summary": "PEP API call failed.",
                "results": [],
            })

        results = []
        try:
            resp_q1 = (data.get("responses") or {}).get("q1") or {}
            results = resp_q1.get("results") or []
        except (TypeError, AttributeError):
            pass

        severity = None
        pep_summary_parts = []

        for r in results:
            datasets = r.get("datasets") or []
            if not isinstance(datasets, list):
                datasets = [datasets] if datasets else []
            caption = r.get("caption") or "Unknown"
            has_sanctions = any("sanction" in (d or "").lower() for d in datasets)
            has_pep = any("pep" in (d or "").lower() for d in datasets)

            if has_sanctions:
                severity = "HIGH"
                pep_summary_parts.append(f"Sanctions match: {caption} (datasets: {', '.join(datasets)})")
            elif has_pep and severity != "HIGH":
                if severity is None:
                    severity = "MEDIUM"
                pep_summary_parts.append(f"PEP match: {caption} (datasets: {', '.join(datasets)})")

        pep_summary = " ".join(pep_summary_parts) if pep_summary_parts else (
            "No PEP or sanctions matches found." if not results else "API returned matches but none classified as sanctions or PEP."
        )

        out = {
            "case_id": case.get("caseId") or case.get("case_id"),
            "severity": severity,
            "pep_summary": pep_summary,
            "results_count": len(results),
            "results": results,
        }
        logger.info("pep_screening result: severity=%s, results_count=%s", severity, len(results))
        return json.dumps(out, indent=2, default=str)
