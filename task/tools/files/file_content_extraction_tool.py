import json
from typing import Any

from aidial_sdk.chat_completion import Message

from task.tools.base import BaseTool
from task.tools.models import ToolCallParams
from task.utils.dial_file_conent_extractor import DialFileContentExtractor


class FileContentExtractionTool(BaseTool):
    """
    Extracts text content from files. Supported: PDF (text only), TXT, CSV (as markdown table), HTML/HTM.
    PAGINATION: Files >10,000 chars are paginated. Response format: `**Page #X. Total pages: Y**` appears at end if paginated.
    USAGE: Start with page=1 (by default)
    """

    def __init__(self, endpoint: str):
        self.endpoint = endpoint

    @property
    def show_in_stage(self) -> bool:
        return False

    @property
    def name(self) -> str:
        return "FileContentExtractionTool"

    @property
    def description(self) -> str:
        return """
        This tool extracts readable text or table data from user-provided files. 
        Use it whenever the user asks questions that require reading or analyzing the content of a file. 
        Supported formats: PDF (text only), TXT, CSV, HTML/HTM.
        """

    @property
    def parameters(self) -> dict[str, Any]:
        return {
        "type": "object",
        "properties": {
            "file_url": {
                "type": "string",
                "description": "URL of the file to extract content from. Supported formats: PDF (text only), TXT, CSV, HTML/HTM.",
            },
            "page": {
                "type": "integer",
                "description": (
                    "Page number for pagination. Large documents are split into 10,000-character pages. "
                    "Starts from 1."
                ),
                "default": 1,
            },
        },
        "required": ["file_url"],
    }

    async def _execute(self, tool_call_params: ToolCallParams) -> str | Message:
        args = json.loads(tool_call_params.tool_call.function.arguments)
        file_url = args.get("file_url")
        page = args.get("page", 1)
        stage = tool_call_params.stage
        stage.append_content("## Request arguments: \n")
        stage.append_content(f"**File URL**: {file_url}\n\r")
        if page > 1:
            stage.append_content(f"**Page**: {page}\n\r")
        stage.append_content("## Response: \n")
        content = DialFileContentExtractor(
            endpoint=self.endpoint,
            api_key=tool_call_params.api_key
        ).extract_text(file_url)
        if not content:
            content = "Error: File content not found."
        page_size = 10_000
        if len(content) > page_size:
            total_pages = (len(content) + page_size - 1) // page_size

            if page < 1:
                page = 1

            if page > total_pages:
                content = f"Error: Page {page} does not exist. Total pages: {total_pages}"
            else:
                start_index = (page - 1) * page_size
                end_index = start_index + page_size
                page_content = content[start_index:end_index]
                content = f"{page_content}\n\n**Page #{page}. Total pages: {total_pages}**"

        stage.append_content(f"```text\n\r{content}\n\r```\n\r")

        return content
