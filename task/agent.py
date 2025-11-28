import asyncio
import json
from typing import Any

from aidial_client import AsyncDial
from aidial_client.types.chat.legacy.chat_completion import CustomContent, ToolCall
from aidial_sdk.chat_completion import Message, Role, Choice, Request, Response

from task.tools.base import BaseTool
from task.tools.models import ToolCallParams
from task.utils.constants import TOOL_CALL_HISTORY_KEY
from task.utils.history import unpack_messages
from task.utils.stage import StageProcessor


class GeneralPurposeAgent:

    def __init__(
            self,
            endpoint: str,
            system_prompt: str,
            tools: list[BaseTool],
    ):
        self.endpoint = endpoint
        self.system_prompt = system_prompt
        self.tools = tools

        self.tools_dict = {tool.name: tool for tool in tools}

        self.state = {
            TOOL_CALL_HISTORY_KEY: []
        }

    async def handle_request(
            self,
            deployment_name: str,
            choice: Choice,
            request: Request,
            response: Response
    ) -> Message:

        client = AsyncDial(
            base_url=self.endpoint,
            api_key=request.api_key,
            api_version=request.api_version
        )

        content = ""
        tool_call_index_map = {}

        tools_json = [tool.schema for tool in self.tools]

        print("=== SENDING MESSAGES ===")
        prepared_messages = self._prepare_messages(request.messages)
        print(json.dumps(prepared_messages, indent=2, ensure_ascii=False))

        chunks = await client.chat.completions.create(
            deployment_name=deployment_name,
            stream=True,
            messages=prepared_messages,
            tools=tools_json
        )

        async for chunk in chunks:
            if not chunk.choices:
                continue

            delta = chunk.choices[0].delta
            if not delta:
                continue

            # --- TEXT CONTENT ---
            if delta.content:
                print("CONTENT DELTA:", delta.content)
                choice.append_content(delta.content)
                content += delta.content

            # --- TOOL CALLS ---
            if delta.tool_calls:
                for tool_call_delta in delta.tool_calls:
                    idx = tool_call_delta.index

                    # First time seeing this tool call → store it
                    if tool_call_delta.id:
                        tool_call_index_map[idx] = tool_call_delta
                        print(f"REGISTER TOOL CALL {idx}: {tool_call_delta}")
                        continue

                    # Subsequent chunks (arguments come in pieces)
                    existing = tool_call_index_map.get(idx)
                    if not existing:
                        # Recover from out-of-order chunk
                        print(f"WARNING: tool call chunk arrived before init, creating stub for index {idx}")
                        tool_call_index_map[idx] = tool_call_delta
                        existing = tool_call_delta

                    if tool_call_delta.function:
                        arg_chunk = tool_call_delta.function.arguments or ""
                        if not existing.function.arguments:
                            existing.function.arguments = ""
                        existing.function.arguments += arg_chunk

                        print(f"ARG CHUNK ADDED TO {idx}: {arg_chunk}")

        # Convert to validated ToolCall objects
        tool_calls = [
            ToolCall.validate(tc.model_dump())
            for tc in tool_call_index_map.values()
        ]

        assistant_message = Message(
            role=Role.ASSISTANT,
            content=content,
            tool_calls=tool_calls
        )

        # --- TOOL CALL FLOW ---
        if assistant_message.tool_calls:
            conversation_id = request.headers.get("x-conversation-id")

            tasks = [
                self._process_tool_call(
                    tool_call=tool_call,
                    conversation_id=conversation_id,
                    api_key=request.api_key,
                    choice=choice
                )
                for tool_call in assistant_message.tool_calls
            ]

            tool_messages = await asyncio.gather(*tasks)

            self.state[TOOL_CALL_HISTORY_KEY].append(
                assistant_message.model_dump(exclude_none=True)
            )
            self.state[TOOL_CALL_HISTORY_KEY].extend(tool_messages)

            # Recursive call to process next model response
            return await self.handle_request(
                deployment_name=deployment_name,
                choice=choice,
                request=request,
                response=response
            )

        # No tool calls → final response
        choice.state = self.state
        return assistant_message

    def _prepare_messages(self, messages: list[Message]) -> list[dict[str, Any]]:
        unpacked=unpack_messages(messages, self.state[TOOL_CALL_HISTORY_KEY])
        system_msg = {"role": "system", "content": self.system_prompt}
        unpacked.insert(0, system_msg)
        for msg in unpacked:
            print(json.dumps(msg, ensure_ascii=False, indent=2))
        return unpacked

    async def _process_tool_call(self, tool_call: ToolCall, choice: Choice, api_key: str, conversation_id: str) -> dict[str, Any]:
        print(f"Calling tool - {tool_call}")
        tool_name=tool_call.function.name
        stage=StageProcessor.open_stage(choice, tool_name)
        tool=self.tools_dict[tool_name]
        if tool.show_in_stage:
            stage.append_content("## Request arguments: \n")
            stage.append_content(f"```json\n\r{json.dumps(json.loads(tool_call.function.arguments), indent=2)}\n\r```\n\r")
            stage.append_content("## Response: \n")
        tool_message = await tool.execute(ToolCallParams(tool_call=tool_call, choice=choice, api_key=api_key,
                                                   conversation_id=conversation_id, stage=stage))
        stage.close()
        return tool_message.model_dump(exclude_none=True)

