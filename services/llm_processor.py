"""LLM-based meeting analysis using Groq's Free Developer Tier API."""

from __future__ import annotations

import json
import logging
import os
from typing import Literal

from openai import OpenAI
from pydantic import BaseModel, Field
from dotenv import load_dotenv

from config import Settings

logger = logging.getLogger(__name__)


class ActionItem(BaseModel):
    """A single actionable task extracted from a meeting transcript."""

    detected_name: str = Field(description="The person name spoken or inferred in the meeting")
    resolved_email: str = Field(description="Office email resolved from the contact directory")
    task_description: str = Field(description="Highly actionable, detailed task description")
    priority: Literal["Low", "Medium", "High"]
    timeline: str = Field(description="Deadline or timeline context extracted from the meeting")


class MeetingAnalysis(BaseModel):
    """Structured output schema enforced by Pydantic validation."""

    meeting_summary: str = Field(description="Concise summary of the meeting")
    action_items: list[ActionItem] = Field(default_factory=list)


class LLMProcessingError(Exception):
    """Raised when LLM extraction fails."""


class LLMProcessor:
    """Handles structured extraction from diarized transcripts using Groq's API."""

    SYSTEM_PROMPT = """You are an expert meeting analyst.

Given a diarized meeting transcript and an office contact directory, produce:
1. A concise meeting_summary.
2. A list of action_items with clear ownership and deadlines.

Rules:
- Use only names that appear in the transcript or can be reasonably inferred from speaker context.
- For resolved_email, match detected_name to the contact directory (case-insensitive, partial match allowed).
- If no email match exists, use the provided unknown_email_placeholder exactly.
- task_description must be specific and actionable (start with a verb).
- priority must be exactly one of: Low, Medium, High.
- timeline must capture any deadline, timeframe, or "not specified" if none was mentioned.
- Do not invent tasks that are not supported by the transcript.
"""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        
        # Explicitly force load the local .env file into os.environ right now
        load_dotenv(override=True)
        
        # Pull it directly from the system environment dictionary
        groq_key = os.environ.get("GROQ_API_KEY") or getattr(settings, "groq_api_key", None)
        
        if not groq_key:
            raise LLMProcessingError(
                "Missing Groq credentials. Please set GROQ_API_KEY in your .env file."
            )

        self._client = OpenAI(
            base_url="https://api.groq.com/openai/v1",
            api_key=groq_key
        )

    def _load_contact_directory(self) -> dict[str, str]:
        try:
            directory = json.loads(self._settings.contact_directory_json)
            if not isinstance(directory, dict):
                raise ValueError("contact_directory_json must decode to a JSON object")
            return {str(name): str(email) for name, email in directory.items()}
        except json.JSONDecodeError as exc:
            logger.warning("Invalid contact_directory_json; using empty directory: %s", exc)
            return {}

    def _build_user_prompt(self, transcript: str) -> str:
        directory = self._load_contact_directory()
        directory_text = json.dumps(directory, indent=2) if directory else "{}"

        return f"""Analyze the following diarized meeting transcript.

Contact directory (name -> email):
{directory_text}

Unknown email placeholder (use when no match is found):
{self._settings.unknown_email_placeholder}

Diarized transcript:
---
{transcript}
---
"""

    def extract_action_items(self, transcript: str) -> MeetingAnalysis:
        """Run Groq structured extraction using JSON mode and Pydantic validation."""
        
        # FIXED: Updated to active flagship open-weights reasoning model identifier
        model_name = "openai/gpt-oss-120b"
        logger.info("Starting Groq structural analysis with model=%s", model_name)

        schema_json = json.dumps(MeetingAnalysis.model_json_schema())
        groq_user_prompt = (
            self._build_user_prompt(transcript) + 
            f"\n\nYou MUST return your output strictly conforming to this JSON schema layout:\n{schema_json}"
        )

        try:
            completion = self._client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user", "content": groq_user_prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.2,
            )
        except Exception as exc:
            logger.exception("Groq API inference stream execution breakdown")
            raise LLMProcessingError(f"Groq structural transaction execution failed: {exc}") from exc

        message_content = completion.choices[0].message.content

        if not message_content:
            logger.error("Groq engine responded with an empty payload wrapper")
            raise LLMProcessingError("Groq transaction yielded empty response text content")

        try:
            parsed_data = json.loads(message_content)
            analysis = MeetingAnalysis.model_validate(parsed_data)
        except Exception as parse_exc:
            logger.error("Failed to parse Groq payload down into target Pydantic architecture: %s", parse_exc)
            raise LLMProcessingError(f"Pydantic target mapping structural validation failed: {parse_exc}") from parse_exc

        logger.info("Groq structural extraction parsed successfully (%d action items extracted)", len(analysis.action_items))
        return analysis