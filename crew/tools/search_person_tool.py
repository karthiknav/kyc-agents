"""Tool to search the web for information about a person."""
import json
import logging
import os
from typing import Type

from langchain_community.utilities import SerpAPIWrapper
from crewai.tools import BaseTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


def _default_serpapi() -> SerpAPIWrapper:
    return SerpAPIWrapper(serpapi_api_key=os.environ.get("SERPAPI_API_KEY", ""))


class SearchPersonInput(BaseModel):
    person_name: str = Field(description="The full name of the person to search for")
    case_id: str = Field(
        default="",
        description="Optional case ID for propagation; pass from get_case_details output",
    )


class SearchPersonTool(BaseTool):
    """Search the internet for news, sanctions, PEP, and adverse media about the given person name."""

    name: str = "search_person"
    description: str = (
        "Search the web for news, articles, sanctions, PEP (Politically Exposed Person), "
        "and adverse media about the given person's full name. Returns relevant findings for KYC screening."
    )
    search: SerpAPIWrapper = Field(default_factory=_default_serpapi)
    args_schema: Type[SearchPersonInput] = SearchPersonInput

    def _run(self, person_name: str, case_id: str = "") -> str:
        """Search the web for information about the person."""
        logger.info("search_person input: person_name=%s, case_id=%s", person_name, case_id)
        if not person_name:
            return "Error: person_name is required."

        # Build query to find relevant KYC/screening info
        query = f"{person_name} news sanctions adverse media PEP"
        try:
            out = self.search.run(query)
            logger.info("search_person output: returned %d chars", len(out) if out else 0)
            # Include case_id in output when provided for propagation
            if case_id:
                return json.dumps({"case_id": case_id, "search_results": out})
            return out
        except Exception as e:
            logger.exception("SearchPersonTool failed")
            return f"Error performing search: {str(e)}"
