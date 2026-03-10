"""Tool to verify an identity document against the Dutch BRP (mock) API."""
import json
import logging
import os
from typing import Type

import requests
from crewai.tools import BaseTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

BRP_API_URL_DEFAULT = "http://localhost:9000/api/v1/brp/personen/document-lookup"


class VerifyIdentityDocumentInput(BaseModel):
    document_type: str = Field(
        description='Document type: "paspoort", "identiteitskaart", or "rijbewijs"'
    )
    document_number: str = Field(
        description="The document number extracted from OCR text"
    )


class VerifyIdentityDocumentTool(BaseTool):
    """Verify an identity document against the BRP government registry."""

    name: str = "verify_identity_document"
    description: str = (
        "Verify an identity document against the Dutch BRP (Basisregistratie Personen) "
        "government registry. Accepts a document type (paspoort, identiteitskaart, rijbewijs) "
        "and document number. Returns the official person record associated with that document, "
        "including name, date of birth, nationality, and document validity dates. "
        "Use this to cross-check OCR-extracted document data against government records."
    )
    args_schema: Type[VerifyIdentityDocumentInput] = VerifyIdentityDocumentInput

    def _run(self, document_type: str, document_number: str) -> str:
        """Call the BRP API to verify the document."""
        api_url = os.environ.get("BRP_API_URL", BRP_API_URL_DEFAULT)

        logger.info(
            "verify_identity_document: type=%s, number=%s, url=%s",
            document_type, document_number, api_url,
        )

        payload = {
            "documentType": document_type,
            "documentNumber": document_number,
        }

        try:
            response = requests.post(api_url, json=payload, timeout=30)
            response.raise_for_status()
            data = response.json()
            logger.info("BRP verification response: %s", json.dumps(data, indent=2))
            return json.dumps(data, indent=2)
        except requests.exceptions.ConnectionError:
            error = {
                "error": "BRP API unavailable",
                "detail": f"Could not connect to {api_url}. Is the mock service running?",
            }
            logger.error("BRP API connection error: %s", api_url)
            return json.dumps(error)
        except requests.exceptions.HTTPError as e:
            error = {
                "error": "BRP API error",
                "status_code": e.response.status_code if e.response else None,
                "detail": e.response.text if e.response else str(e),
            }
            logger.error("BRP API HTTP error: %s", error)
            return json.dumps(error)
        except Exception as e:
            error = {"error": "BRP verification failed", "detail": str(e)}
            logger.exception("BRP verification error: %s", e)
            return json.dumps(error)
