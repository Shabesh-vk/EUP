"""
AI Video Editing Brain orchestrator.
Selects adapter based on configuration and coordinates with TimelineEngine.
"""

from __future__ import annotations
import os
from typing import Dict, Any, List, Optional, Tuple
from .adapter_interface import BaseLLMAdapter
from .mock_adapter import MockLLMAdapter
from .llm_adapter import LiveLLMAdapter
from ..core.models import Transcript, StepResponse
from ..core.timeline_engine import TimelineEngine


class VideoEditingBrain:
    def __init__(self, adapter: Optional[BaseLLMAdapter] = None):
        if adapter is not None:
            self.adapter = adapter
        else:
            provider = os.getenv("LLM_PROVIDER", "mock").lower()
            if provider in ["mock", "none", "test"]:
                self.adapter = MockLLMAdapter()
            else:
                self.adapter = LiveLLMAdapter()

    def process_instruction(
        self,
        instruction: str,
        engine: TimelineEngine,
        answer: Optional[str] = None,
        pending_clarification: Optional[Dict[str, Any]] = None,
    ) -> StepResponse:
        """
        Translates human instruction to structured ops, then applies them
        to the deterministic timeline engine.
        """
        # Prepare context from history
        history_summary = [
            {
                "step_id": rec.step_id,
                "instruction": rec.instruction,
                "summary": rec.summary,
                "operations": [op.model_dump() for op in rec.operations],
                "is_undone": rec.is_undone,
            }
            for rec in engine.history
        ]

        # If user provided a follow-up answer to a pending question:
        effective_input = answer if answer and pending_clarification else instruction

        # 1. Translate instruction via LLM Brain adapter
        response = self.adapter.translate_instruction(
            instruction=effective_input,
            transcript=engine.transcript,
            history_summary=history_summary,
            pending_clarification=pending_clarification,
            context={"current_duration": engine.get_current_duration()},
        )

        # 2. If status is applied, execute operations deterministically on TimelineEngine
        if response.status == "applied":
            if any(op.op == "undo" for op in response.operations):
                step_res = engine.undo()
                step_res.summary = response.summary or step_res.summary
                return step_res
            elif any(op.op == "redo" for op in response.operations):
                step_res = engine.redo()
                step_res.summary = response.summary or step_res.summary
                return step_res
            elif any(op.op == "restore_edit" for op in response.operations):
                restore_op = next(op for op in response.operations if op.op == "restore_edit")
                target_id = restore_op.params.get("target_step_id", 2)
                step_res = engine.restore_specific_edit(target_id)
                step_res.summary = response.summary or step_res.summary
                return step_res
            else:
                applied_res = engine.apply_step(
                    instruction=instruction,
                    operations=response.operations,
                    summary=response.summary,
                )
                return applied_res

        # For needs_clarification or rejected, attach current timeline hash & duration
        response.timeline_hash = engine.get_timeline_hash()
        response.duration_s = engine.get_current_duration()
        return response
