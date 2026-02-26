import logging
from typing import Type
from pydantic import BaseModel, Field
from langchain_tavily import TavilySearch
from crewai.tools import BaseTool

logger = logging.getLogger(__name__)


class SearchInput(BaseModel):
    query: str = Field(description="The search query to execute")


class SearchTool(BaseTool):
    name: str = "search_internet"
    description: str = "Search the internet for the given query. Use this to find current information on any topic."
    search: TavilySearch = Field(default_factory=TavilySearch)
    args_schema: Type[SearchInput] = SearchInput

    def _run(self, query: str) -> str:
        """Search the internet for the given query."""
        logger.warning("SearchTool received: query=%r", query)
        if not query:
            return "Error: no query provided."
        try:
            return self.search.invoke({"query": query})
        except Exception as e:
            return f"Error performing search: {str(e)}"
