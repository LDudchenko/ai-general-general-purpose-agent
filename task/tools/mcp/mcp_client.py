from typing import Optional, Any

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.types import CallToolResult, TextContent, ReadResourceResult, TextResourceContents, BlobResourceContents, \
    ListToolsResult
from pydantic import AnyUrl

from task.tools.mcp.mcp_tool_model import MCPToolModel


class MCPClient:
    """Handles MCP server connection and tool execution"""

    def __init__(self, mcp_server_url: str) -> None:
        self.server_url = mcp_server_url
        self.session: Optional[ClientSession] = None
        self._streams_context = None
        self._session_context = None

    @classmethod
    async def create(cls, mcp_server_url: str) -> 'MCPClient':
        """Async factory method to create and connect MCPClient"""
        instance=cls(mcp_server_url)
        await instance.connect()
        return instance


    async def connect(self):
        """Connect to MCP server"""
        if self.session:
            return
        self._streams_context = streamablehttp_client(self.server_url)
        read_stream, write_stream, _ = await self._streams_context.__aenter__()
        self._session_context = ClientSession(read_stream, write_stream)
        self.session = await self._session_context.__aenter__()
        result = await self.session.initialize()
        print(result)



    async def get_tools(self) -> list[MCPToolModel]:
        """Get available tools from MCP server"""
        if not self.session:
            raise Exception("MCP client is not connected to MCP server")
        result_tools = []
        list_tools_result: ListToolsResult = await self.session.list_tools()
        for tool in list_tools_result.tools:
            result_tools.append(MCPToolModel(name=tool.name, description=tool.description, parameters=tool.inputSchema))
        return result_tools

    async def call_tool(self, tool_name: str, tool_args: dict[str, Any]) -> Any:
        """Call a tool on the MCP server"""
        if not self.session:
            raise Exception("MCP client is not connected to MCP server")
        print(f"Call to MCP server: tool_name - {tool_name}, tool_args - {tool_args}, url - {self.server_url}")
        result: CallToolResult = await self.session.call_tool(tool_name, tool_args)
        result_content = result.content[0]
        if isinstance(result_content, TextContent):
            return result_content.text
        else:
            return result_content

    async def get_resource(self, uri: AnyUrl) -> str | bytes:
        """Get specific resource content"""
        if not self.session:
            raise Exception("MCP client is not connected to MCP server")
        result = await self.session.read_resource(uri)
        content = result.contents[0]
        if isinstance(content, BlobResourceContents):
            return content.blob
        return result.text

    async def close(self):
        """Close connection to MCP server"""
        self._session_context.__aexit__(None, None, None)
        self._streams_context.__aexit__(None, None, None)
        self.session = None
        self._session_context = None
        self._streams_context = None

    async def __aenter__(self):
        """Async context manager entry"""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.close()
        return False

