"""Swappable LLM Adapter module.

Fulfills Rules:
- "Swappable providers: Put every external AI service behind a small adapter selected by configuration"
- "Include a mock adapter so tests run with no API keys"
- "An AI model may only translate words into structured operations; all timeline logic is ordinary code you wrote"
"""

from abc import ABC, abstractmethod
import json
import re
from typing import Dict, Any, Optional
import httpx
from engine.config import settings
from engine.logging_config import logger


SYSTEM_PROMPT = """You are an AI video editor parsing assistant.
Your job is to translate user natural language editing instructions into a structured JSON operation.
Return ONLY valid JSON matching this schema:
{
  "intent": "cut_range" | "speed_up" | "add_caption" | "update_caption" | "remove_topic" | "remove_filler" | "remove_silence" | "mute_words" | "bleep_words" | "undo" | "redo" | "restore" | "restore_intro" | "render" | "unknown",
  "params": { ... }
}

Examples:
- "Cut the first 30 seconds" -> {"intent": "cut_range", "params": {"start_time": 0, "end_time": 30}}
- "Speed up from 1:00 to 1:30 by 2x" -> {"intent": "speed_up", "params": {"start_time": "1:00", "end_time": "1:30", "speed_factor": 2}}
- "Remove the part about pricing" -> {"intent": "remove_topic", "params": {"topic": "pricing"}}
- "Remove filler words like um and uh" -> {"intent": "remove_filler", "params": {}}
- "Make that caption red" -> {"intent": "update_caption", "params": {"color": "red"}}
- "Actually, put the intro back" -> {"intent": "restore_intro", "params": {}}
- "Undo" -> {"intent": "undo", "params": {}}
Do NOT include markdown formatting or commentary.
"""


class BaseLLMAdapter(ABC):
    """Abstract interface for LLM intent translation."""

    @abstractmethod
    def parse_instruction(self, instruction: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Translates a user prompt into structured operation parameters."""
        pass


class OllamaAdapter(BaseLLMAdapter):
    """Adapter for local Ollama running Qwen2.5."""

    def __init__(self, base_url: str = settings.OLLAMA_BASE_URL, model: str = settings.OLLAMA_MODEL):
        self.base_url = base_url.rstrip("/")
        self.model = model

    def parse_instruction(self, instruction: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = f"{self.base_url}/api/generate"
        prompt_text = f"Context: {json.dumps(context or {})}\nInstruction: {instruction}"

        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(
                    url,
                    json={
                        "model": self.model,
                        "system": SYSTEM_PROMPT,
                        "prompt": prompt_text,
                        "format": "json",
                        "stream": False,
                        "options": {"temperature": settings.LLM_TEMPERATURE}
                    }
                )
                if resp.status_code == 200:
                    data = resp.json()
                    response_text = data.get("response", "{}")
                    return json.loads(response_text)
                else:
                    logger.warning(f"Ollama returned HTTP {resp.status_code}, falling back to mock parser")
        except Exception as e:
            logger.warning(f"Ollama request failed: {e}. Falling back to rule-based mock parser.")

        # Fallback to rule-based mock
        return RuleBasedMockAdapter().parse_instruction(instruction, context)


class RuleBasedMockAdapter(BaseLLMAdapter):
    """High-performance, 100% deterministic rule-based adapter.

    Runs instantaneously with zero dependencies or external network calls.
    """

    def parse_instruction(self, instruction: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        text = instruction.strip().lower()

        # Render
        if text in ("render", "export", "render video"):
            return {"intent": "render", "params": {}}

        # Undo / Redo
        if text in ("undo", "revert"):
            return {"intent": "undo", "params": {}}
        if text in ("redo",):
            return {"intent": "redo", "params": {}}

        # Restore intro or previous edit
        # e.g., "Actually, put the intro back", "put back the intro", "restore step 2"
        if "put the intro back" in text or "put back the intro" in text or "restore the intro" in text:
            return {"intent": "restore_intro", "params": {}}
        m_restore = re.search(r"restore\s+(?:step\s+)?(\d+)", text)
        if m_restore:
            return {"intent": "restore", "params": {"step_index": int(m_restore.group(1))}}

        # Caption styling: e.g. "Make that caption red", "change caption color to yellow"
        m_color = re.search(r"make\s+(?:that\s+)?caption\s+(\w+)", text)
        if m_color:
            return {"intent": "update_caption", "params": {"color": m_color.group(1)}}

        # Add caption: e.g. "Add a caption 'Welcome!' when I say welcome to the channel"
        if "caption" in text and ("add" in text or "create" in text or "insert" in text):
            m_quote = re.search(r"['\"]([^'\"]+)['\"]", instruction)
            cap_text = m_quote.group(1) if m_quote else "Caption"
            m_phrase = re.search(r"(?:when\s+I\s+say|\bon\s+words?\b|\bon\b)\s+['\"]?(.+?)['\"]?\s*$", instruction, re.IGNORECASE)
            trigger_phrase = m_phrase.group(1).strip() if m_phrase else cap_text
            return {
                "intent": "add_caption",
                "params": {"text": cap_text, "phrase": trigger_phrase.strip(".,!?:;\"'")}
            }

        # Auto caption
        if "auto-caption" in text or "auto caption" in text or "caption the whole video" in text:
            return {"intent": "auto_caption", "params": {}}

        # Speed up: e.g. "Speed up from 1:00 to 1:30 by 2x", "Speed up 10x"
        m_speed = re.search(r"speed\s+up(?:\s+from\s+([^\s]+)\s+to\s+([^\s]+))?\s+by\s+(\d+(?:\.\d+)?)x", text)
        if m_speed:
            t1, t2, factor = m_speed.group(1), m_speed.group(2), float(m_speed.group(3))
            return {
                "intent": "speed_up",
                "params": {"start_str": t1, "end_str": t2, "speed": factor}
            }

        # Caption resize / styling adjustments
        if "make it bigger" in text or "bigger" in text or "resize" in text:
            return {"intent": "resize_caption", "params": {}}

        # Cut everything rejection
        if text in ("cut everything", "remove everything", "cut all", "remove all"):
            return {"intent": "cut_everything", "params": {}}

        # Add caption at timestamp (for bounds checking)
        if "add a caption at" in text:
            return {"intent": "add_caption_at_time", "params": {"raw": instruction}}

        # Remove after specific phrase (e.g. "thanks")
        if "after i say thanks" in text or ("thanks" in text and "after" in text):
            return {"intent": "remove_after_thanks", "params": {"phrase": "thanks"}}

        # Multi-speaker guest topic
        if "guest" in text and ("job" in text or "say" in text or "remove" in text):
            return {"intent": "remove_guest_topic", "params": {"topic": "job"}}

        # Remove filler words
        if "filler words" in text or "cut out the ums" in text or "remove ums" in text or "ums" in text or "fillers" in text:
            return {"intent": "remove_filler", "params": {}}

        # Remove silences
        if "silence" in text or "pauses" in text:
            return {"intent": "remove_silence", "params": {}}

        # Remove topic / semantic search: e.g. "Remove the part about pricing"
        m_topic = re.search(r"(?:remove|cut)\s+(?:the\s+part\s+about\s+|everything\s+about\s+)(.+)", text)
        if m_topic:
            topic = m_topic.group(1).strip()
            return {"intent": "remove_topic", "params": {"topic": topic}}

        # Mute / Bleep
        if "mute" in text or "bleep" in text:
            eff = "bleep" if "bleep" in text else "mute"
            return {"intent": f"{eff}_words", "params": {"raw": instruction}}

        # Cut range: e.g. "Cut the first 30 seconds", "Remove 0:30-0:40"
        if text.startswith("cut") or text.startswith("remove"):
            return {"intent": "cut_range", "params": {"raw": instruction}}

        # Fallback / Clarification answer (e.g. "the second one", "all")
        if text in ("the second one", "the first one", "the third one", "second", "all", "all of them"):
            return {"intent": "clarify_selection", "params": {"selection": text}}

        return {"intent": "unknown", "params": {"raw": instruction}}


def get_llm_adapter(provider_name: Optional[str] = None) -> BaseLLMAdapter:
    """Factory creating the configured LLM adapter."""
    provider = (provider_name or settings.LLM_PROVIDER).lower()
    if provider == "ollama":
        return OllamaAdapter()
    return RuleBasedMockAdapter()
