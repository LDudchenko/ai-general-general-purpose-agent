import base64
import json
from typing import Any, Optional

from aidial_client import Dial
from aidial_sdk.chat_completion import Message, Attachment
from pydantic import StrictStr, AnyUrl

from task.tools.base import BaseTool
from task.tools.py_interpreter._response import _ExecutionResult
from task.tools.mcp.mcp_client import MCPClient
from task.tools.mcp.mcp_tool_model import MCPToolModel
from task.tools.models import ToolCallParams


class PythonCodeInterpreterTool(BaseTool):
    """
    Uses https://github.com/khshanovskyi/mcp-python-code-interpreter PyInterpreter MCP Server.

    ⚠️ Pay attention that this tool will wrap all the work with PyInterpreter MCP Server.
    """

    def __init__(
            self,
            mcp_client: MCPClient,
            mcp_tool_models: list[MCPToolModel],
            tool_name: str,
            dial_endpoint: str,
    ):
        """
        :param tool_name: it must be actual name of tool that executes code. It is 'execute_code'.
            https://github.com/khshanovskyi/mcp-python-code-interpreter/blob/main/interpreter/server.py#L303
        """
        self.dial_endpoint = dial_endpoint
        self.mcp_client = mcp_client
        self._code_execute_tool = None
        for tool in mcp_tool_models:
            if tool.name == tool_name:
                self._code_execute_tool = tool
                break

        if self._code_execute_tool is None:
            raise ValueError(
                f"Cannot initialize PythonCodeInterpreterTool: "
                f"tool with name '{tool_name}' not found among MCP tools."
            )

    @classmethod
    async def create(
            cls,
            mcp_url: str,
            tool_name: str,
            dial_endpoint: str,
    ) -> 'PythonCodeInterpreterTool':
        """Async factory method to create PythonCodeInterpreterTool"""
        mcp_client = MCPClient(mcp_url)
        await mcp_client.connect()

        mcp_tool_models = await mcp_client.get_tools()

        return cls(
            mcp_client=mcp_client,
            mcp_tool_models=mcp_tool_models,
            tool_name=tool_name,
            dial_endpoint=dial_endpoint,
        )

    @property
    def show_in_stage(self) -> bool:
        return False

    @property
    def name(self) -> str:
        tool_name = self._code_execute_tool.name
        print(tool_name)
        return tool_name

    @property
    def description(self) -> str:
        return self._code_execute_tool.description

    @property
    def parameters(self) -> dict[str, Any]:
        return self._code_execute_tool.parameters

    async def _execute(self, tool_call_params: ToolCallParams) -> str | Message:
        args = json.loads(tool_call_params.tool_call.function.arguments)
        code = args["code"]
        session_id = args.get("session_id")
        stage = tool_call_params.stage
        stage.append_content("## Request arguments: \n")
        stage.append_content("""```python\n\r{code}\n\r```\n""")
        if session_id:
            stage.append_content(f"**session_id**: {session_id}\n\r")
        else:
            stage.append_content("New session will be created\n\r")

        result = await self.mcp_client.call_tool(tool_call_params.tool_call.function.name, args)
        print("RAW RESULT:", result)
        result_json = json.loads(result)
        execution_result = _ExecutionResult(**result_json)
        if execution_result.files:
            attachments = []

            if execution_result.files:
                dial = Dial(base_url=self.dial_endpoint)
                files_home = dial.my_appdata_home()

                for file in execution_result.files:
                    file_name = file.name
                    mime_type = file.mime_type
                    resource_url = file.url

                    resource = await self.mcp_client.get_resource(resource_url)

                    if mime_type.startswith("text/") or mime_type in (
                            "application/json", "application/xml"
                    ):
                        data_bytes = resource.encode("utf-8")
                    else:
                        data_bytes = base64.b64decode(resource)

                    upload_path = f"files/{(files_home / file_name).as_posix()}"
                    await dial.files.upload(url=upload_path, file=data_bytes)

                    attachment = Attachment(
                        url=upload_path,
                        type=mime_type,
                        title=file_name
                    )

                    attachments.append(attachment)
                    stage.add_attachment(attachment)
                    tool_call_params.choice.add_attachment(attachment)

                execution_result.attachments = [a.model_dump() for a in attachments]

            if execution_result.output:
                for chunk in execution_result.output:
                    if chunk.text:
                        chunk.text = chunk.text[:1000]

            json_dump = execution_result.model_dump_json(indent=2)
            stage.append_content(f"```json\n{json_dump}\n```\n")

            return json_dump
        #TODO:
        # 10. Validate result with _ExecutionResult (it is full copy of https://github.com/khshanovskyi/mcp-python-code-interpreter/blob/main/interpreter/models.py)
        # 11. If execution_result contains files we need to pool files from PyInterpreter and upload them to DIAL bucked:
        #       - Create Dial client
        #       - Get with client `my_appdata_home` path as `files_home`
        #       - Iterated through files and:
        #           - get file name and mime_type and assign to appropriate variables
        #           - get resource with mcp client by URL from file (https://github.com/khshanovskyi/mcp-python-code-interpreter/blob/main/interpreter/server.py#L429)
        #           - according to MCP binary resources must be encoded with base64 https://modelcontextprotocol.io/specification/2025-06-18/server/resources#binary-content
        #             Check if mime_type starts with `text/` or some of 'application/json', 'application/xml', is yes
        #             then encode resource with 'utf-8' format (text will be present as bytes to upload to DIAL bucket).
        #             Otherwise (binary file) decode it with `b64decode`
        #           - Prepare URL to upload downloaded file: file"files/{(files_home / file_name).as_posix()}"
        #           - Upload file with DIAL client
        #           - Prepare Attachment with url, type (mime_type), and title (file_name)
        #           - Add attachment to stage and also add this attachment to choice (it will be chown in both stage and choice)
        #       - Add to execution_result json addition
        # 12. Check if execution_result output present and if yes iterate through all output results and cut it length
        #     to 1000 chars, it is needed to avoid high costs and context window overload
        # 13. Append to stage response file"```json\n\r{execution_result.model_dump_json(indent=2)}\n\r```\n\r"
        # 14. Return execution result as string (model_dump_json method)
