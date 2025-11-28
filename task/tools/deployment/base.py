import json
from abc import ABC, abstractmethod
from typing import Any

from aidial_client import AsyncDial
from aidial_sdk.chat_completion import Message, Role, CustomContent
from pydantic import StrictStr

from task.tools.base import BaseTool
from task.tools.models import ToolCallParams


class DeploymentTool(BaseTool, ABC):

    def __init__(self, endpoint: str):
        self.endpoint = endpoint

    @property
    @abstractmethod
    def deployment_name(self) -> str:
        pass

    @property
    def tool_parameters(self) -> dict[str, Any]:
        return {}

    async def _execute(self, tool_call_params: ToolCallParams) -> str | Message:
        args = json.loads(tool_call_params.tool_call.function.arguments)

        prompt = args.get("prompt")

        custom_fields = {k: v for k, v in args.items() if k != "prompt"}

        stage = tool_call_params.stage
        stage.append_content("## Request arguments:\n")
        stage.append_content(f"**Prompt:** {prompt}\n\r")

        if custom_fields:
            stage.append_content(f"**Custom fields:** `{json.dumps(custom_fields)}`\n\r")

        client = AsyncDial(
            base_url=self.endpoint,
            api_key=tool_call_params.api_key,
        )

        messages = [{"role": "user", "content": prompt}]

        collected_output = ""
        attachments = []

        stage.append_content("## Response:\n")

        async for event in await client.chat.completions.create(
                deployment_name=self.deployment_name,
                api_version="2025-01-01-preview",
                messages=messages,
                stream=True,
                extra_body={"custom_fields": custom_fields},
                **self.tool_parameters
        ):
            if event.type == "chat.completion.chunk":
                delta = event.delta or ""
                if delta:
                    collected_output += delta
                    stage.append_content(delta)

            if event.type == "chat.completion.message":
                if event.custom_content:
                    attachments.extend(event.custom_content)
                    stage.add_attachment(event.custom_content)

        return Message(
            role=Role.TOOL,
            content=collected_output,
            custom_content=attachments,
            tool_call_id=tool_call_params.tool_call.id
        )

        #TODO:
        # 1. Load arguments with `json`
        # 2. Get `prompt` from arguments (by default we provide `prompt` for each deployment tool, use this param name as standard)
        # 3. Delete `prompt` from `arguments` (there can be provided additional parameters and `prompt` will be added
        #    as user message content and other parameters as `custom_fields`)
        # 4. Create AsyncDial client (api_version is 2025-01-01-preview)
        # 5. Call chat completions with:
        #   - messages (here will be just user message. Optionally, in this class you can add system prompt `property`
        #     and if any deployment tool provides system prompt then we need to set it as first message (system prompt))
        #   - stream it
        #   - deployment_name
        #   - extra_body with `custom_fields` https://dialx.ai/dial_api#operation/sendChatCompletionRequest (last request param in documentation)
        #   - **self.tool_parameters (will load all tool parameters that were set up in deployment tools as params, like
        #     `top_p`, `temperature`, etc...)
        # 6. Collect content and it to stage, also, collect custom_content -> attachments and if they are present add
        #    them to stage as attachment as well
        # 7. Return Message with tool role, content, custom_content and tool_call_id
