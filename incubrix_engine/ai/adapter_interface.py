"""
Abstract Adapter Interface for LLM Video Brain.
Allows swappable LLM backends (OpenAI, Gemini, Anthropic, Ollama, and Mock).
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from ..core.models import Transcript, StepResponse


class BaseLLMAdapter(ABC):
    @abstractmethod
    def translate_instruction(
        self,
        instruction: str,
        transcript: Transcript,
        history_summary: List[Dict[str, Any]],
        pending_clarification: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> StepResponse:
        """
        Translates user instruction into a structured StepResponse
        containing status (applied, needs_clarification, rejected),
        operations list, and clarification/rejection details.
        """
        pass
