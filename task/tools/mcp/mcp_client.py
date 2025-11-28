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
        #TODO:
        # 1. Check if session is present, if yes just return to finsh execution
        # 2. Call `streamablehttp_client` method with `server_url` and set as `self._streams_context`
        # 3. Enter `self._streams_context`, result set as `read_stream, write_stream, _`
        # 4. Create ClientSession with streams from above and set as `self._session_context`
        # 5. Enter `self._session_context` and set as self.session
        # 6. Initialize session and print its result to console


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
        result_content = result.content
        if isinstance(result_content[0], TextContent):
            return result_content[0].text
        else:
            return result_content
        #TODO: Make tool call and return its result. Do it in proper way (it returns array of content and you need to handle it properly)

    async def get_resource(self, uri: AnyUrl) -> str | bytes:
        """Get specific resource content"""
        if not self.session:
            raise Exception("MCP client is not connected to MCP server")
        result = await self.session.read_resource(uri)
        if isinstance(result, BlobResourceContents):
            return result.blob
        return result.text
        #TODO: Get and return resource. Resources can be returned as TextResourceContents and BlobResourceContents, you
        #      need to return resource value (text or blob)

    async def close(self):
        """Close connection to MCP server"""
        self._session_context.__aexit__(None, None, None)
        self._streams_context.__aexit__(None, None, None)
        self.session = None
        self._session_context = None
        self._streams_context = None
        #TODO:
        # 1. Close `self._session_context`
        # 2. Close `self._streams_context`
        # 3. Set session, _session_context and _streams_context as None

    async def __aenter__(self):
        """Async context manager entry"""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.close()
        return False

