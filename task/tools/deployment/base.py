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
            api_version='2025-01-01-preview'
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
            if event.choices:
                delta = event.choices[0].delta
                if delta:
                    if delta.content:
                        tool_call_params.stage.append_content(delta.content)
                        collected_output += delta.content
                    if delta.custom_content and delta.custom_content.attachments:
                        attachments = delta.custom_content.attachments

                        for attachment in attachments:
                            attachments.append(attachment)
                            tool_call_params.stage.add_attachment(
                                type=attachment.type,
                                title=attachment.title,
                                data=attachment.data,
                                url=attachment.url,
                                reference_url=attachment.reference_url,
                                reference_type=attachment.reference_type,
                            )

        return Message(
            role=Role.TOOL,
            content=StrictStr(collected_output),
            custom_content=CustomContent(attachments=attachments),
            tool_call_id=StrictStr(tool_call_params.tool_call.id)
        )
