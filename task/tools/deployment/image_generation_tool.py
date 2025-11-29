from typing import Any

from aidial_sdk.chat_completion import Message
from pydantic import StrictStr

from task.tools.deployment.base import DeploymentTool
from task.tools.models import ToolCallParams


class ImageGenerationTool(DeploymentTool):

    async def _execute(self, tool_call_params: ToolCallParams) -> str | Message:
        result: Message = await super()._execute(tool_call_params)
        images = [
            attachment for attachment in (result.custom_content.attachments or [])
            if attachment.type in ("image/png", "image/jpeg")
        ]
        for img in images:
            print(f"IMAGE URL: {img.url}")
            tool_call_params.choice.append_content(f"\n\r![image]({img.url})\n\r")
        if not result.content:
            result.content = StrictStr("The image has been successfully generated according to request and shown to user!")
        return result
        #TODO:
        # In this override impl we just need to add extra actions, we need to propagate attachment to the Choice since
        # in DeploymentTool they were propagated to the stage only as files. The main goal here is show pictures in chat
        # (DIAL Chat support special markdown to load pictures from DIAL bucket directly to the chat)
        # ---
        # 1. Call parent function `_execute` and get result
        # 2. If attachments are present then filter only "image/png" and "image/jpeg"
        # 3. Append then as content to choice in such format `f"\n\r![image]({attachment.url})\n\r")`
        # 4. After iteration through attachment if message content is absent add such instruction:
        #    'The image has been successfully generated according to request and shown to user!'
        #    Sometimes models are trying to add generated pictures as well to content (choice), with this instruction
        #    we are notifing LLLM that it was done (but anyway sometimes it will try to add file 😅)

    @property
    def deployment_name(self) -> str:
        return "dall-e-3"

    @property
    def name(self) -> str:
        return "image_generation"

    @property
    def description(self) -> str:
        return (
            """
            This tool generates images from detailed textual descriptions using the DALL·E 3 model.
            Use it whenever the user explicitly requests an image, a picture, an illustration, a scene,
            or visual content.
            The tool accepts a prompt (required) that describes the image, and optional parameters such as
            size, quality, and style to customize the result.
            It returns generated images as attachments and displays them directly in the chat.
            If a user requests modifications to an image, the tool can also be used for updated generation.
            """
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Extensive description of the image that should be generated."
                },
                "size": {
                    "type": "string",
                    "description": (
                        "Optional. The size of the generated image. "
                        "Valid values: '1024x1024', '1024x1792', '1792x1024'."
                    ),
                    "enum": ["1024x1024", "1024x1792", "1792x1024"]
                },
                "quality": {
                    "type": "string",
                    "description": (
                        "Optional. Controls image fidelity. "
                        "Valid values: 'standard', 'hd'."
                    ),
                    "enum": ["standard", "hd"]
                },
                "style": {
                    "type": "string",
                    "description": (
                        "Optional. Whether the image should be in a 'vivid' artistic style "
                        "or 'natural' photographic style."
                    ),
                    "enum": ["vivid", "natural"]
                }
            },
            "required": ["prompt"]
        }