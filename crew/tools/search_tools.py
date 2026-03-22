import json
import logging
import os
from typing import Type

from ddgs import DDGS
from crewai.tools import BaseTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class SearchInput(BaseModel):
    query: str = Field(description="The search query to execute")


class SearchTool(BaseTool):
    name: str = "search_internet"
    description: str = "Search the internet for the given query using DuckDuckGo."
    args_schema: Type[SearchInput] = SearchInput

    def _run(self, query: str) -> str:
        """Search the internet for the given query via DuckDuckGo."""
        logger.warning("SearchTool received: query=%r", query)
        if not query:
            return "Error: no query provided."
        try:
            max_results = int(os.getenv("SEARCH_MAX_RESULTS", "5"))
            ddg = DDGS()
            results = list(ddg.text(query, max_results=max_results))
            # Valid JSON so downstream tools can nest it in structured payloads (Python repr breaks JSON).
            return json.dumps(results, ensure_ascii=False)
        except Exception as e:
            logger.exception("DuckDuckGo search failed")
            return f"Error performing search: {str(e)}"
