"""
Natural Language Understanding and LLM Adapter integration for IncuBrix.
Produces schema-validated IntentProposals that our deterministic editing engine validates and executes.
"""

from __future__ import annotations
import os
import json
import re
from typing import Optional, Dict, Any, List, Literal
from pydantic import BaseModel, Field, ConfigDict


class IntentProposal(BaseModel):
    model_config = ConfigDict(extra="ignore")
    intent_type: Literal[
        "add_automatic_captions",
        "add_custom_caption",
        "edit_caption",
        "cut_range",
        "speed_range",
        "remove_filler_words",
        "remove_silence",
        "add_music",
        "mute_words",
        "bleep_words",
        "restore_transaction",
        "undo",
        "redo",
        "query_change",
        "clarification_response",
        "unrecognized",
    ]
    parameters: Dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    raw_prompt: str = ""
    explanation: Optional[str] = None


class BaseLLMAdapter:
    """Base interface for NLU adapters."""

    @property
    def provider_name(self) -> str:
        raise NotImplementedError

    @property
    def is_connected(self) -> bool:
        raise NotImplementedError

    def parse_instruction(
        self,
        text: str,
        conversation_context: Optional[Dict[str, Any]] = None,
    ) -> IntentProposal:
        raise NotImplementedError


class SemanticRuleAdapter(BaseLLMAdapter):
    """
    High-accuracy deterministic semantic interpreter.
    Interprets natural language, follow-ups, paraphrases, and context-anchored references.
    """

    @property
    def provider_name(self) -> str:
        return "semantic_rule_engine"

    @property
    def is_connected(self) -> bool:
        return True

    def parse_instruction(
        self,
        text: str,
        conversation_context: Optional[Dict[str, Any]] = None,
    ) -> IntentProposal:
        ctx = conversation_context or {}
        raw = text.strip()
        lower = raw.lower()

        # 1. Undo / Redo
        if lower in ("undo", "undo that", "revert", "step back", "undo last edit"):
            return IntentProposal(intent_type="undo", raw_prompt=raw)
        if lower in ("redo", "redo that", "step forward"):
            return IntentProposal(intent_type="redo", raw_prompt=raw)

        # 2. Querying changes ("what did you change?", "show changes", "what was changed")
        if re.search(r"what\s+(?:did\s+you\s+change|was\s+changed|changes\s+were\s+made)|show\s+(?:edits|history|changes)", lower):
            return IntentProposal(intent_type="query_change", raw_prompt=raw)

        # 3. Clarification responses (when context has pending clarification)
        if ctx.get("pending_clarification"):
            if re.search(r"\b(?:first|1st|1)\b", lower):
                return IntentProposal(intent_type="clarification_response", parameters={"choice": 0, "text": raw}, raw_prompt=raw)
            if re.search(r"\b(?:second|2nd|2)\b", lower):
                return IntentProposal(intent_type="clarification_response", parameters={"choice": 1, "text": raw}, raw_prompt=raw)
            if re.search(r"\b(?:third|3rd|3)\b", lower):
                return IntentProposal(intent_type="clarification_response", parameters={"choice": 2, "text": raw}, raw_prompt=raw)
            if re.search(r"\b(?:fourth|4th|4)\b", lower):
                return IntentProposal(intent_type="clarification_response", parameters={"choice": 3, "text": raw}, raw_prompt=raw)
            if re.search(r"\b(?:all|both|everything)\b", lower):
                return IntentProposal(intent_type="clarification_response", parameters={"choice": -1, "text": raw}, raw_prompt=raw)
            if re.search(r"\b(?:cancel|abort|leave\s+it)\b", lower):
                return IntentProposal(intent_type="clarification_response", parameters={"choice": "cancel", "text": raw}, raw_prompt=raw)

        # 4. Automatic captioning paraphrases
        # "Add captions to the video", "Subtitle the whole clip", "Show the spoken words as captions", "Can you caption everything?", "auto caption"
        auto_cap_patterns = [
            r"^(?:add\s+)?captions?(?:\s+to\s+the\s+video|\s+to\s+video)?$",
            r"^(?:can\s+you\s+)?(?:subtitle|caption)\s+(?:the\s+whole\s+clip|everything|the\s+video|all)$",
            r"^show\s+(?:the\s+)?spoken\s+words\s+as\s+captions$",
            r"^(?:auto\s*caption|auto\s*subtitles?|generate\s+captions?)$",
            r"^add\s+subtitles?(?:\s+to\s+the\s+video)?$",
        ]
        if any(re.search(pat, lower) for pat in auto_cap_patterns):
            return IntentProposal(
                intent_type="add_automatic_captions",
                parameters={"color": "white", "position": "bottom", "font_size": 36},
                raw_prompt=raw,
            )

        # 5. Caption modification follow-ups:
        # "Make them bigger", "Make it bigger", "Increase caption size", "Make that caption bigger", "Make them smaller"
        m_bigger = re.search(r"(?:make\s+(?:them|it|that|captions?)\s+|increase\s+(?:the\s+)?(?:caption\s+)?font\s+size\s+by\s+)?(bigger|larger|smaller)", lower)
        if m_bigger or "make them bigger" in lower or "make it bigger" in lower:
            delta = 8 if (not m_bigger or m_bigger.group(1) in ("bigger", "larger")) else -6
            target = "them" if "them" in lower or "captions" in lower else "active"
            return IntentProposal(
                intent_type="edit_caption",
                parameters={"target": target, "font_size_delta": delta},
                raw_prompt=raw,
            )

        # Exact font size: "make caption size 48", "set font size to 42"
        m_size = re.search(r"(?:font\s+size\s+(?:to\s+)?|size\s+)([0-9]{2})", lower)
        if m_size:
            target = "them" if "them" in lower or "captions" in lower else "active"
            return IntentProposal(
                intent_type="edit_caption",
                parameters={"target": target, "font_size": int(m_size.group(1))},
                raw_prompt=raw,
            )

        # Color changes: "Now change it to red", "Make them yellow", "Change them to yellow", "Change caption to blue"
        m_color = re.search(r"(?:(?:make|change)\s+(?:them|it|that|captions?)\s+(?:to\s+)?|color\s+(?:to\s+)?)(red|yellow|blue|green|white|black|cyan|magenta)", lower)
        if m_color:
            target = "them" if "them" in lower or "captions" in lower else "active"
            return IntentProposal(
                intent_type="edit_caption",
                parameters={"target": target, "color": m_color.group(1)},
                raw_prompt=raw,
            )

        # 6. Custom caption overlay: "Add a caption 'Welcome!' when I say welcome to the channel"
        m_custom_cap = re.search(r"caption\s+['\"]([^'\"]+)['\"](?:\s+(?:when\s+I\s+say|over|at)\s+([a-z0-9\s]+))?", raw, re.IGNORECASE)
        if m_custom_cap:
            return IntentProposal(
                intent_type="add_custom_caption",
                parameters={
                    "text": m_custom_cap.group(1),
                    "anchor_phrase": m_custom_cap.group(2) if m_custom_cap.group(2) else None,
                },
                raw_prompt=raw,
            )

        # 7. Speed adjustment: "Speed up from 1:00 to 1:30 by 2x"
        m_speed = re.search(r"speed\s+up\s+(?:from\s+)?([0-9:apm\s]+?)\s+to\s+([0-9:apm\s]+?)\s+by\s+([0-9]+(?:\.[0-9]+)?x?)", lower)
        if m_speed:
            return IntentProposal(
                intent_type="speed_range",
                parameters={
                    "start": m_speed.group(1).strip(),
                    "end": m_speed.group(2).strip(),
                    "ratio": m_speed.group(3).strip().rstrip("x"),
                },
                raw_prompt=raw,
            )

        # 8. Selective restore: "put the intro back", "restore the first 30 seconds", "restore transaction #1"
        m_restore = re.search(r"(?:put\s+(?:back\s+)?|restore\s+)(?:the\s+)?([a-z0-9\s#]+?)(?:\s+back)?$", lower)
        if "put" in lower or "restore" in lower or "bring that section back" in lower:
            target_desc = m_restore.group(1).strip() if m_restore else raw
            return IntentProposal(
                intent_type="restore_transaction",
                parameters={"target": target_desc},
                raw_prompt=raw,
            )

        # 9. Cut ranges / sections: "Cut the first 30 seconds", "Remove the first 10 seconds", "cut from 1:00 to 1:30"
        m_cut_range = re.search(r"(?:cut|remove|trim|delete)\s+(?:from\s+)?([0-9:apm\s]+?)\s+to\s+([0-9:apm\s]+)", lower)
        if m_cut_range:
            return IntentProposal(
                intent_type="cut_range",
                parameters={"start": m_cut_range.group(1).strip(), "end": m_cut_range.group(2).strip()},
                raw_prompt=raw,
            )

        m_cut_first = re.search(r"(?:cut|remove|trim|delete)\s+(?:the\s+)?(?:first|intro)\s+([0-9]+(?:\s*(?:seconds?|secs?|s|minutes?|mins?|m))?)", lower)
        if m_cut_first:
            dur_expr = m_cut_first.group(1).strip() or "30s"
            return IntentProposal(
                intent_type="cut_range",
                parameters={"start": "0:00", "end": dur_expr, "target_name": "intro"},
                raw_prompt=raw,
            )

        # 10. Clean up / Filler / Silence
        if "filler" in lower or "um" in lower or "uh" in lower:
            return IntentProposal(intent_type="remove_filler_words", raw_prompt=raw)
        if "silence" in lower or "pauses" in lower:
            return IntentProposal(intent_type="remove_silence", raw_prompt=raw)

        # 11. Keyword removal: "Remove the part about pricing" / "Cut thanks"
        m_keyword = re.search(r"(?:remove|cut)\s+(?:the\s+part\s+about\s+|everything\s+after\s+I\s+say\s+)?([a-z0-9\s]+)", lower)
        if m_keyword:
            kw = re.sub(r"^(?:the\s+part\s+about\s+|everything\s+after\s+i\s+say\s+)", "", m_keyword.group(1)).strip()
            return IntentProposal(
                intent_type="cut_range",
                parameters={"keyword": kw},
                raw_prompt=raw,
            )

        return IntentProposal(intent_type="unrecognized", raw_prompt=raw)


class GeminiLLMAdapter(BaseLLMAdapter):
    """Real inference adapter using Google Gemini API."""

    def __init__(self, api_key: Optional[str] = None, model: str = "gemini-1.5-flash"):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        self.model = model

    @property
    def provider_name(self) -> str:
        return "gemini"

    @property
    def is_connected(self) -> bool:
        return bool(self.api_key)

    def parse_instruction(
        self,
        text: str,
        conversation_context: Optional[Dict[str, Any]] = None,
    ) -> IntentProposal:
        if not self.is_connected:
            raise RuntimeError("GEMINI_API_KEY is not configured for real inference.")

        import httpx
        prompt = (
            "You are an AI video editing assistant. Given the user's instruction and conversation context, "
            "return a JSON object with schema: "
            "{'intent_type': 'add_automatic_captions'|'add_custom_caption'|'edit_caption'|'cut_range'|'speed_range'|'restore_transaction'|'undo'|'redo'|'query_change'|'clarification_response'|'unrecognized', "
            "'parameters': dict, 'explanation': str}."
            f"\nContext: {json.dumps(conversation_context or {})}"
            f"\nUser instruction: {text}"
        )

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"response_mime_type": "application/json"},
        }

        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.post(url, json=payload)
                if resp.status_code != 200:
                    raise RuntimeError(f"Gemini API returned status {resp.status_code}: {resp.text}")
                data = resp.json()
                content = data["candidates"][0]["content"]["parts"][0]["text"]
                parsed = json.loads(content)
                parsed["raw_prompt"] = text
                return IntentProposal(**parsed)
        except Exception as e:
            raise RuntimeError(f"Gemini inference failed: {str(e)}")


class OllamaLLMAdapter(BaseLLMAdapter):
    """Local inference adapter using Ollama with Qwen or other open-weight models."""

    def __init__(self, host: str = "http://localhost:11434", model: Optional[str] = None):
        self.host = os.environ.get("OLLAMA_HOST", host).rstrip("/")
        requested_model = model or os.environ.get("OLLAMA_MODEL")
        if requested_model:
            self.model = requested_model
        else:
            # Auto-select installed Qwen model or fallback
            available = self.list_available_models()
            qwen_models = [m for m in available if "qwen" in m.lower()]
            if qwen_models:
                self.model = qwen_models[0]
            elif available:
                self.model = available[0]
            else:
                self.model = "qwen2.5:1.5b"

    @property
    def provider_name(self) -> str:
        return f"ollama_{self.model}"

    @property
    def is_connected(self) -> bool:
        try:
            import httpx
            with httpx.Client(timeout=1.0) as client:
                res = client.get(f"{self.host}/api/tags")
                return res.status_code == 200
        except Exception:
            return False

    def list_available_models(self) -> List[str]:
        try:
            import httpx
            with httpx.Client(timeout=2.0) as client:
                res = client.get(f"{self.host}/api/tags")
                if res.status_code == 200:
                    data = res.json()
                    return [m["name"] for m in data.get("models", [])]
        except Exception:
            pass
        return []

    def parse_instruction(
        self,
        text: str,
        conversation_context: Optional[Dict[str, Any]] = None,
    ) -> IntentProposal:
        import httpx

        # Verify active model is installed, or pick available
        available = self.list_available_models()
        active_model = self.model
        if available and active_model not in available:
            # Check for variant match
            matching = [m for m in available if active_model.split(":")[0] in m]
            if matching:
                active_model = matching[0]
            elif any("qwen" in m.lower() for m in available):
                active_model = [m for m in available if "qwen" in m.lower()][0]
            else:
                active_model = available[0]

        system_prompt = (
            "You are an expert AI video editing assistant for IncuBrix.\n"
            "Your task is to parse the user's natural language video editing command into a structured JSON operation.\n\n"
            "Supported intent_type options:\n"
            "- 'add_automatic_captions': For requests like 'add captions to the video', 'subtitle the clip', 'show captions'. Parameters: {}\n"
            "- 'add_custom_caption': For specific text overlays like 'add Welcome at 5s'. Parameters: {'text': str, 'start': float, 'end': float, 'color': str, 'font_size': int}\n"
            "- 'edit_caption': For follow-up edits like 'make them bigger', 'change them to yellow', 'move to top'. Parameters: {'target': 'them'|'all', 'color': str, 'font_size': int, 'font_size_delta': int (e.g. +6 or -6), 'position': 'bottom'|'top'}\n"
            "- 'cut_range': For removing sections, e.g. 'cut the first 30 seconds', 'remove intro', 'cut from 1:00 to 1:30'. Parameters: {'start': str/float, 'end': str/float, 'target_name': str}\n"
            "- 'speed_range': For speed changes like 'speed up clip to 1.5x', 'slow down'. Parameters: {'speed_ratio': float, 'start': float, 'end': float}\n"
            "- 'remove_filler_words': For 'remove filler words', 'clean up ums and uhs'. Parameters: {}\n"
            "- 'remove_silence': For 'trim pauses', 'cut silence'. Parameters: {'min_duration_s': float}\n"
            "- 'restore_transaction': For 'bring that section back', 'put the intro back', 'restore transaction #1'. Parameters: {'target': str}\n"
            "- 'undo': For 'undo', 'undo that change', 'revert'. Parameters: {}\n"
            "- 'redo': For 'redo', 'redo that'. Parameters: {}\n"
            "- 'query_change': For questions like 'what did you change?', 'show edit history'. Parameters: {}\n"
            "- 'clarification_response': For user answering an ambiguity question, e.g. 'the second one', '1:05', 'all'. Parameters: {'choice': int|str}\n"
            "- 'unrecognized': If unrelated to video editing.\n\n"
            "Rules for conversation follow-ups:\n"
            "1. 'make them bigger' -> intent_type: 'edit_caption', parameters: {'font_size_delta': 6}\n"
            "2. 'change them to yellow' -> intent_type: 'edit_caption', parameters: {'color': 'yellow'}\n"
            "3. 'undo that color change' -> intent_type: 'undo', parameters: {}\n"
            "4. 'leave the intro alone' -> intent_type: 'restore_transaction', parameters: {'target': 'intro'}\n"
            "5. 'what did you change?' -> intent_type: 'query_change', parameters: {}\n\n"
            "Respond ONLY with a valid JSON object matching: "
            '{"intent_type": str, "parameters": dict, "explanation": str}'
        )

        user_content = (
            f"Active Project Context:\n{json.dumps(conversation_context or {}, indent=2)}\n\n"
            f"User Command: {text}"
        )

        payload = {
            "model": active_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "format": "json",
            "stream": False,
            "options": {
                "temperature": 0.1,
            },
        }

        try:
            with httpx.Client(timeout=30.0) as client:
                resp = client.post(f"{self.host}/api/chat", json=payload)
                if resp.status_code != 200:
                    raise RuntimeError(f"Ollama returned HTTP {resp.status_code}: {resp.text}")
                data = resp.json()
                raw_json = data.get("message", {}).get("content", "{}")
                parsed = json.loads(raw_json)
                parsed["raw_prompt"] = text
                return IntentProposal(**parsed)
        except Exception as e:
            raise RuntimeError(f"Ollama inference failed ({active_model}): {str(e)}")


_active_adapter: Optional[BaseLLMAdapter] = None


def get_llm_adapter() -> BaseLLMAdapter:
    global _active_adapter
    if _active_adapter is None:
        provider = os.environ.get("NLU_PROVIDER", "").lower()
        gemini_key = os.environ.get("GEMINI_API_KEY")

        if provider == "ollama" or os.environ.get("OLLAMA_MODEL"):
            _active_adapter = OllamaLLMAdapter()
        elif (provider == "gemini" or gemini_key) and gemini_key:
            _active_adapter = GeminiLLMAdapter(api_key=gemini_key)
        else:
            # Auto-detect local Ollama if running
            ollama = OllamaLLMAdapter()
            if ollama.is_connected:
                _active_adapter = ollama
            else:
                _active_adapter = SemanticRuleAdapter()

    return _active_adapter


def set_active_llm_adapter(provider: str, model: Optional[str] = None) -> BaseLLMAdapter:
    global _active_adapter
    provider = provider.lower()
    if provider == "ollama":
        _active_adapter = OllamaLLMAdapter(model=model or "qwen2.5:1.5b")
    elif provider == "gemini":
        gemini_key = os.environ.get("GEMINI_API_KEY")
        _active_adapter = GeminiLLMAdapter(api_key=gemini_key, model=model or "gemini-1.5-flash")
    else:
        _active_adapter = SemanticRuleAdapter()
    return _active_adapter


def get_model_status() -> Dict[str, Any]:
    adapter = get_llm_adapter()
    is_real = isinstance(adapter, (GeminiLLMAdapter, OllamaLLMAdapter))
    provider_type = (
        "ollama" if isinstance(adapter, OllamaLLMAdapter)
        else ("gemini" if isinstance(adapter, GeminiLLMAdapter) else "semantic_rule")
    )

    available_models: List[str] = []
    current_model = getattr(adapter, "model", None)
    if isinstance(adapter, OllamaLLMAdapter):
        available_models = adapter.list_available_models()

    return {
        "connected": adapter.is_connected,
        "provider": adapter.provider_name,
        "active_provider": provider_type,
        "model": current_model or ("gemini-1.5-flash" if provider_type == "gemini" else "rule_engine"),
        "available_models": available_models,
        "is_real_llm": is_real,
        "api_key_configured": bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("OPENAI_API_KEY") or isinstance(adapter, OllamaLLMAdapter)),
        "clock_policy": "current_edited_time",
    }
