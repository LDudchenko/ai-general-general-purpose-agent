import json
from typing import Any

import faiss
import numpy as np
from aidial_client import AsyncDial
from aidial_sdk.chat_completion import Message, Role
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sentence_transformers import SentenceTransformer

from task.tools.base import BaseTool
from task.tools.models import ToolCallParams
from task.tools.rag.document_cache import DocumentCache
from task.utils.dial_file_conent_extractor import DialFileContentExtractor

_SYSTEM_PROMPT = """
Use the following document context to answer the question.

Context:
{context_text}

Question: 
{request}
"""


class RagTool(BaseTool):
    """
    Performs semantic search on documents to find and answer questions based on relevant content.
    Supports: PDF, TXT, CSV, HTML.
    """

    def __init__(self, endpoint: str, deployment_name: str, document_cache: DocumentCache):
        self.endpoint = endpoint
        self.deployment_name = deployment_name
        self.document_cache = document_cache
        self.model = SentenceTransformer(
            model_name_or_path='all-MiniLM-L6-v2',

        )
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=500,
            chunk_overlap=50,
            length_function=len,
            separators=["\n\n", "\n", ". ", " ", ""]
        )

    @property
    def show_in_stage(self) -> bool:
        return False

    @property
    def name(self) -> str:
        return "rag_tool"

    @property
    def description(self) -> str:
        return (
            "Performs semantic search over documents (PDF, TXT, CSV, HTML) and generates answers "
            "to user questions using relevant content."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "request": {
                    "type": "string",
                    "description": "The search query or question to search for in the document",
                },
                "file_url": {
                    "type": "string",
                    "description": "File URL",
                },
            },
            "required": ["request", "file_url"],
        }

    async def _execute(self, tool_call_params: ToolCallParams) -> str | Message:
        args = json.loads(tool_call_params.tool_call.function.arguments)
        request_text = args["request"]
        file_url = args["file_url"]
        stage = tool_call_params.stage

        stage.append_content("## Request arguments: \n")
        stage.append_content(f"**Request**: {request_text}\n\r")
        stage.append_content(f"**File URL**: {file_url}\n\r")

        conversation_id = tool_call_params.conversation_id
        cache_key = f"{conversation_id}_{file_url}"

        cached_data = self.document_cache.get(cache_key)
        if cached_data:
            index, chunks = cached_data
        else:
            text_content = DialFileContentExtractor(
                endpoint=self.endpoint,
                api_key=tool_call_params.api_key
            ).extract_text(file_url)

            if not text_content:
                stage.append_content("## Response: \n")
                return "Error: File content not found."

            chunks = self.text_splitter.split_text(text_content)
            embeddings = self.model.encode(chunks, convert_to_numpy=True)

            index = faiss.IndexFlatL2(384)
            index.add(np.array(embeddings).astype("float32"))

        query_embedding = self.model.encode([request_text], convert_to_numpy=True).astype('float32')
        distances, indices = index.search(query_embedding, k=3)
        retrieved_chunks = [chunks[i] for i in indices[0] if i < len(chunks)]

        augmented_prompt = self.__augmentation(request_text, retrieved_chunks)

        stage.append_content("## RAG Request: \n")
        stage.append_content(f"```text\n\r{augmented_prompt}\n\r```\n\r")
        stage.append_content("## Response: \n")

        client = AsyncDial(base_url=self.endpoint, api_key=tool_call_params.api_key)
        collected_content = ""

        async for chunk in await client.chat.completions.create(
                deployment_name=self.deployment_name,
                messages=[{"role": "system", "content": _SYSTEM_PROMPT},
                          {"role": "user", "content": augmented_prompt}],
                api_version="025-01-01-preview",
                stream=True
        ):
            if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                delta_content = chunk.choices[0].delta.content
                collected_content += delta_content
                stage.append_content(delta_content)

        return collected_content

    def __augmentation(self, request: str, chunks: list[str]) -> str:
        context_text = "\n\n---\n\n".join(chunks)
        prompt = _SYSTEM_PROMPT.format(
            context_text=context_text,
            request=request
        )
        return prompt