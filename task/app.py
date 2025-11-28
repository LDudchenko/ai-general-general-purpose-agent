import os

import uvicorn
from aidial_sdk import DIALApp
from aidial_sdk.chat_completion import ChatCompletion, Request, Response

from task.agent import GeneralPurposeAgent
from task.prompts import SYSTEM_PROMPT
from task.tools.base import BaseTool
from task.tools.deployment.image_generation_tool import ImageGenerationTool
from task.tools.files.file_content_extraction_tool import FileContentExtractionTool
from task.tools.py_interpreter.python_code_interpreter_tool import PythonCodeInterpreterTool
from task.tools.mcp.mcp_client import MCPClient
from task.tools.mcp.mcp_tool import MCPTool
from task.tools.rag.document_cache import DocumentCache
from task.tools.rag.rag_tool import RagTool

DIAL_ENDPOINT = os.getenv('DIAL_ENDPOINT', "http://localhost:8080")
DEPLOYMENT_NAME = os.getenv('DEPLOYMENT_NAME', 'gpt-4o')

class GeneralPurposeAgentApplication(ChatCompletion):

    def __init__(self):
        self.tools: list[BaseTool] = []

    async def _get_mcp_tools(self, url: str) -> list[BaseTool]:
        base_tool_list=[]
        mcp_client = MCPClient(url)
        tools = await mcp_client.get_tools()
        for tool_model in tools:
            mcp_tool = MCPTool(
                client=mcp_client,
                mcp_tool_model=tool_model
            )
            base_tool_list.append(mcp_tool)
        return base_tool_list

    async def _create_tools(self) -> list[BaseTool]:
        tools = []
        tools.append(FileContentExtractionTool(DIAL_ENDPOINT))
        tools.append(RagTool(DIAL_ENDPOINT, DEPLOYMENT_NAME, DocumentCache.create()))
        # tools.extend(
        #     [ImageGenerationTool(DIAL_ENDPOINT),
        #     FileContentExtractionTool(DIAL_ENDPOINT),
        #     RagTool(DIAL_ENDPOINT, DEPLOYMENT_NAME, DocumentCache.create()),
        #     PythonCodeInterpreterTool(dial_endpoint=DIAL_ENDPOINT, tool_name="execute_code",
        #                               mcp_client=MCPClient("http://localhost:8050/mcp"), mcp_tool_models=[])]
        # )
        # tools.extend(await self._get_mcp_tools("http://localhost:8051/mcp"))
        return tools

    async def chat_completion(self, request: Request, response: Response) -> None:
        if not self.tools:
            self.tools = await self._create_tools()
        with response.create_single_choice() as choice:
            general_purpose_agent = GeneralPurposeAgent(endpoint=DIAL_ENDPOINT,
                                                        system_prompt=SYSTEM_PROMPT, tools=self.tools)
            await general_purpose_agent.handle_request(choice=choice, deployment_name=DEPLOYMENT_NAME, request=request, response=response)

def main():
    app=DIALApp(dial_endpoint=DIAL_ENDPOINT, deployment_name=DEPLOYMENT_NAME)
    agent_app=GeneralPurposeAgentApplication()
    app.add_chat_completion(deployment_name="general-purpose-agent", impl=agent_app)
    uvicorn.run(app, port=5030, host="0.0.0.0")

if __name__ == "__main__":
    main()
