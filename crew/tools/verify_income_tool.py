"""Tools to verify income via UWV and business registration via KVK (mock) APIs."""
import json
import logging
import os
from typing import Type

import requests
from crewai.tools import BaseTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

MOCK_SERVICE_URL_DEFAULT = "http://localhost:9000"
UWV_PATH = "/api/v1/uwv/polisadministratie/dienstverbanden"
KVK_PATH = "/api/v1/kvk/basisprofiel"


def _join_url(base: str, path: str) -> str:
    return base.rstrip("/") + path


# ---------------------------------------------------------------------------
# UWV Polisadministratie tool
# ---------------------------------------------------------------------------

class VerifyIncomeUWVInput(BaseModel):
    burgerservicenummer: str = Field(
        description="The BSN (burgerservicenummer) of the person to verify"
    )


class VerifyIncomeUWVTool(BaseTool):
    """Verify employment and income records via the UWV Polisadministratie API."""

    name: str = "verify_income_uwv"
    description: str = (
        "Verifies employment and income records by querying the UWV Polisadministratie API "
        "with a BSN (burgerservicenummer). Returns employment records (dienstverbanden) including "
        "employer details, contract type, and income figures (svLoon)."
    )
    args_schema: Type[VerifyIncomeUWVInput] = VerifyIncomeUWVInput

    def _run(self, burgerservicenummer: str) -> str:
        """Call the UWV API to verify employment and income records."""
        explicit = (os.environ.get("UWV_API_URL") or "").strip()
        if explicit:
            api_url = explicit
        else:
            base_url = (os.environ.get("MOCK_SERVICE_URL") or "").strip() or MOCK_SERVICE_URL_DEFAULT
            api_url = _join_url(base_url, UWV_PATH)

        logger.info(
            "verify_income_uwv: bsn=%s, url=%s",
            burgerservicenummer, api_url,
        )

        payload = {
            "burgerservicenummer": burgerservicenummer,
        }

        try:
            response = requests.post(api_url, json=payload, timeout=30)
            response.raise_for_status()
            data = response.json()
            logger.info("UWV verification response: %s", json.dumps(data, indent=2))
            return json.dumps(data, indent=2)
        except requests.exceptions.ConnectionError:
            error = {
                "error": "UWV API unavailable",
                "detail": f"Could not connect to {api_url}. Is the mock service running?",
            }
            logger.error("UWV API connection error: %s", api_url)
            return json.dumps(error)
        except requests.exceptions.HTTPError as e:
            error = {
                "error": "UWV API error",
                "status_code": e.response.status_code if e.response else None,
                "detail": e.response.text if e.response else str(e),
            }
            logger.error("UWV API HTTP error: %s", error)
            return json.dumps(error)
        except Exception as e:
            error = {"error": "UWV verification failed", "detail": str(e)}
            logger.exception("UWV verification error: %s", e)
            return json.dumps(error)


# ---------------------------------------------------------------------------
# KVK Basisprofiel tool
# ---------------------------------------------------------------------------

class VerifyBusinessKVKInput(BaseModel):
    kvk_nummer: str = Field(
        description="The KVK number (Kamer van Koophandel registration number) of the business to verify"
    )


class VerifyBusinessKVKTool(BaseTool):
    """Verify business registration via the KVK Basisprofiel API."""

    name: str = "verify_business_kvk"
    description: str = (
        "Verifies business registration by querying the KVK (Kamer van Koophandel) Basisprofiel API. "
        "Returns business profile including registration details, SBI activity codes, legal form, and "
        "number of employees. Use this when the income source is self-employment or business ownership."
    )
    args_schema: Type[VerifyBusinessKVKInput] = VerifyBusinessKVKInput

    def _run(self, kvk_nummer: str) -> str:
        """Call the KVK API to verify business registration."""
        explicit = (os.environ.get("KVK_API_URL") or "").strip()
        if explicit:
            api_url = explicit
        else:
            base_url = (os.environ.get("MOCK_SERVICE_URL") or "").strip() or MOCK_SERVICE_URL_DEFAULT
            api_url = _join_url(base_url, KVK_PATH)

        logger.info(
            "verify_business_kvk: kvk_nummer=%s, url=%s",
            kvk_nummer, api_url,
        )

        payload = {
            "kvkNummer": kvk_nummer,
        }

        try:
            response = requests.post(api_url, json=payload, timeout=30)
            response.raise_for_status()
            data = response.json()
            logger.info("KVK verification response: %s", json.dumps(data, indent=2))
            return json.dumps(data, indent=2)
        except requests.exceptions.ConnectionError:
            error = {
                "error": "KVK API unavailable",
                "detail": f"Could not connect to {api_url}. Is the mock service running?",
            }
            logger.error("KVK API connection error: %s", api_url)
            return json.dumps(error)
        except requests.exceptions.HTTPError as e:
            error = {
                "error": "KVK API error",
                "status_code": e.response.status_code if e.response else None,
                "detail": e.response.text if e.response else str(e),
            }
            logger.error("KVK API HTTP error: %s", error)
            return json.dumps(error)
        except Exception as e:
            error = {"error": "KVK verification failed", "detail": str(e)}
            logger.exception("KVK verification error: %s", e)
            return json.dumps(error)
