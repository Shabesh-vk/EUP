"""
Live LLM Adapter for hosted or local models (OpenAI, Gemini, Ollama, Anthropic).
Provides structured JSON parsing with validation against Pydantic schema.
"""

from __future__ import annotations
import os
import json
from typing import Dict, Any, List, Optional
import httpx

from .adapter_interface import BaseLLMAdapter
from ..core.models import Transcript, StepResponse

SYSTEM_PROMPT = """You are the AI Video Editing Brain for the IncuBrix Prompt-Based Video Editing Engine.

Your task is to translate plain-language creator instructions into structured timeline operations based on the provided word-level video transcript and edit history.

### RULES & CONSTRAINTS:
1. OUTPUT FORMAT: You must ONLY output a valid JSON object. No explanations, no markdown fences, no conversational filler.
2. THREE-WAY ANSWER REQUIREMENT: Every instruction must result in EXACTLY ONE of three statuses:
   - "applied": The instruction is unambiguous and valid.
   - "needs_clarification": The instruction is ambiguous, mentions a topic with multiple occurrences, or is destructive without certainty. NEVER GUESS on destructive edits. Provide a specific question and numbered options.
   - "rejected": The instruction is impossible, exceeds duration, or contradicts previous edits. State the exact reason.
3. CONTENT-BASED ANCHORING: Always anchor operations to word indices (start_word_id, end_word_id) or semantic targets, NEVER raw absolute clock positions unless explicitly told.
4. TIME POLICY: When a clock timestamp (e.g., "1:20") is provided, state in the summary whether it refers to original_time or current_timeline_time.
5. CONTEXT & EDIT HISTORY:
   - Resolve references like "that caption", "make it red", "the intro", "the boring part" using previous turns.
   - For commands like "undo", "put back the intro", or "restore", identify the specific past edit step to reverse or restore.

### JSON OUTPUT SCHEMA:
{
  "status": "applied" | "needs_clarification" | "rejected",
  "summary": "Concise human-readable explanation of what happened or why",
  "operations": [
    {
      "op": "cut_range" | "keep_only" | "speed_change" | "mute_words" | "bleep_words" | "add_caption" | "auto_caption" | "remove_filler" | "remove_silence" | "add_bg_music" | "undo" | "redo" | "restore_edit" | "style_caption",
      "params": { ... }
    }
  ],
  "clarification": {
    "question": "Specific question if status is needs_clarification",
    "options": ["Option 1", "Option 2", "All"]
  },
  "rejection_reason": "Specific reason if status is rejected"
}
"""


class LiveLLMAdapter(BaseLLMAdapter):
    """
    Adapter communicating with OpenAI/Gemini/Ollama endpoints using structured JSON outputs.
    """

    def __init__(
        self,
        provider: str = "openai",
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self.provider = provider or os.getenv("LLM_PROVIDER", "openai")
        self.api_key = api_key or os.getenv("LLM_API_KEY", "")
        self.base_url = base_url or os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
        self.model = model or os.getenv("LLM_MODEL", "gpt-4o-mini")

    def translate_instruction(
        self,
        instruction: str,
        transcript: Transcript,
        history_summary: List[Dict[str, Any]],
        pending_clarification: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> StepResponse:
        user_payload = {
            "instruction": instruction,
            "pending_clarification": pending_clarification,
            "transcript_summary": {
                "duration": transcript.duration,
                "word_count": len(transcript.words),
                "sample_words": [w.model_dump() for w in transcript.words[:50]],
            },
            "history": history_summary,
            "context": context or {},
        }

        # Call OpenAI-compatible chat completion endpoint
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(user_payload)},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.0,
        }

        try:
            with httpx.Client(timeout=30.0) as client:
                res = client.post(f"{self.base_url}/chat/completions", headers=headers, json=body)
                res.raise_for_status()
                data = res.json()
                content = data["choices"][0]["message"]["content"]
                parsed = json.loads(content)
                return StepResponse(**parsed)
        except Exception as e:
            # Fallback to rejected on model failure
            return StepResponse(
                status="rejected",
                summary="External LLM service call failed.",
                rejection_reason=f"LLM API Error: {str(e)}",
            )
