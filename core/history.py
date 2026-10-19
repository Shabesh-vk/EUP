"""
Transactional history and undo/redo/restore management for the IncuBrix Editing Engine.
"""

from __future__ import annotations
import copy
import re
from typing import List, Optional, Tuple, Dict, Any
from .schema import Timeline, TransactionRecord, ClipSegment


class HistoryManager:
    """
    Manages atomic transactions, linear undo/redo, and targeted selective restore.
    """

    def __init__(self, timeline: Timeline):
        self.timeline = timeline
        self._redo_stack: List[TransactionRecord] = []

    @property
    def transactions(self) -> List[TransactionRecord]:
        return self.timeline.transactions

    @property
    def redo_stack(self) -> List[TransactionRecord]:
        return self._redo_stack

    def clear_redo(self) -> None:
        """A new successful edit clears the redo stack."""
        self._redo_stack.clear()

    def record_transaction(
        self,
        instruction: str,
        operation_type: str,
        before_segments: List[ClipSegment],
        after_segments: List[ClipSegment],
        details: Dict[str, Any],
        affected_effect_ids: Optional[List[str]] = None,
    ) -> TransactionRecord:
        """
        Record a newly applied transaction and clear the redo stack.
        """
        tx_id = f"tx_{len(self.timeline.transactions) + 1}_{operation_type}"
        tx = TransactionRecord(
            id=tx_id,
            instruction=instruction,
            operation_type=operation_type,
            status="applied",
            applied_at_step=len(self.timeline.transactions) + 1,
            details=details,
            inverse_segments=copy.deepcopy(before_segments),
            applied_segments=copy.deepcopy(after_segments),
            affected_effect_ids=affected_effect_ids or [],
        )
        self.timeline.transactions.append(tx)
        self.clear_redo()
        return tx

    def undo(self) -> Tuple[bool, str, Optional[TransactionRecord]]:
        """
        Undo the most recent applied transaction.
        One instruction = one undo.
        """
        # Find the last applied transaction
        applied_txs = [tx for tx in self.timeline.transactions if tx.status == "applied"]
        if not applied_txs:
            return False, "Nothing to undo.", None

        last_tx = applied_txs[-1]
        if last_tx.inverse_segments is not None:
            self.timeline.segments = copy.deepcopy(last_tx.inverse_segments)

        # Handle effects if modified
        if last_tx.operation_type in ("add_caption", "auto_caption"):
            cap_id = last_tx.details.get("caption_id")
            cap_ids = last_tx.details.get("caption_ids", [])
            remove_ids = set(cap_ids)
            if cap_id:
                remove_ids.add(cap_id)
            if remove_ids:
                self.timeline.effects.captions = [
                    c for c in self.timeline.effects.captions if c.id not in remove_ids
                ]
        elif last_tx.operation_type == "edit_caption":
            if last_tx.details.get("is_group"):
                prev_colors = last_tx.details.get("previous_colors", {})
                prev_sizes = last_tx.details.get("previous_font_sizes", {})
                for c in self.timeline.effects.captions:
                    if c.id in prev_colors:
                        c.color = prev_colors[c.id]
                    if c.id in prev_sizes:
                        c.font_size = prev_sizes[c.id]
            else:
                prev_color = last_tx.details.get("previous_color")
                prev_size = last_tx.details.get("previous_font_size")
                cap_id = last_tx.details.get("caption_id")
                for c in self.timeline.effects.captions:
                    if c.id == cap_id:
                        if prev_color:
                            c.color = prev_color
                        if prev_size:
                            c.font_size = prev_size
        elif last_tx.operation_type == "add_music":
            mus_id = last_tx.details.get("music_id")
            if mus_id:
                self.timeline.effects.music = [
                    m for m in self.timeline.effects.music if m.id != mus_id
                ]
        elif last_tx.operation_type == "auto_edit_cleanup":
            added_cap_ids = set(last_tx.details.get("added_caption_ids", []))
            if added_cap_ids:
                self.timeline.effects.captions = [c for c in self.timeline.effects.captions if c.id not in added_cap_ids]
            added_music_ids = set(last_tx.details.get("added_music_ids", []))
            if added_music_ids:
                self.timeline.effects.music = [m for m in self.timeline.effects.music if m.id not in added_music_ids]

        last_tx.status = "undone"
        self._redo_stack.append(last_tx)
        return True, f"Undid: {last_tx.instruction}", last_tx

    def redo(self) -> Tuple[bool, str, Optional[TransactionRecord]]:
        """
        Redo the most recently undone transaction.
        """
        if not self._redo_stack:
            return False, "Nothing to redo.", None

        tx = self._redo_stack.pop()
        if tx.applied_segments is not None:
            self.timeline.segments = copy.deepcopy(tx.applied_segments)

        # Re-apply effect additions
        if tx.operation_type == "edit_caption":
            if tx.details.get("is_group"):
                new_color = tx.details.get("new_color")
                new_size = tx.details.get("new_font_size")
                cap_ids = set(tx.details.get("caption_ids", []))
                for c in self.timeline.effects.captions:
                    if c.id in cap_ids:
                        if new_color:
                            c.color = new_color
                        if new_size:
                            c.font_size = new_size
            else:
                new_color = tx.details.get("new_color")
                new_size = tx.details.get("new_font_size")
                cap_id = tx.details.get("caption_id")
                for c in self.timeline.effects.captions:
                    if c.id == cap_id:
                        if new_color:
                            c.color = new_color
                        if new_size:
                            c.font_size = new_size

        tx.status = "applied"
        return True, f"Redid: {tx.instruction}", tx

    def selective_restore(
        self, target_tx_query: str
    ) -> Tuple[bool, str, Optional[TransactionRecord]]:
        """
        Selectively restore a specific earlier edit without rolling back unrelated later edits.
        
        Example: "put the intro back" restores the cut of the first 30 seconds,
        while retaining later pricing cuts and speed changes.
        """
        # Find the target cut transaction
        target_tx: Optional[TransactionRecord] = None
        target_query_strip = target_tx_query.strip()
        target_query_lower = target_query_strip.lower()

        # Direct match by stable transaction ID (e.g. "tx_001")
        for tx in self.timeline.transactions:
            if tx.id == target_query_strip:
                target_tx = tx
                break

        # Match by explicit index (e.g. "#1", "transaction #1", "transaction 1") or standalone integer ("1")
        if not target_tx:
            m_num = re.search(r"(?:transaction\s*#?|#)(\d+)\b", target_query_lower)
            if not m_num and target_query_lower.strip().isdigit():
                m_num = re.search(r"(\d+)", target_query_lower)

            if m_num:
                t_idx = int(m_num.group(1)) - 1
                if 0 <= t_idx < len(self.timeline.transactions):
                    target_tx = self.timeline.transactions[t_idx]

        if not target_tx:
            for tx in reversed(self.timeline.transactions):
                if tx.status == "applied" and tx.operation_type in ("cut_range", "remove_silence", "remove_filler_words"):
                    if target_query_lower in tx.instruction.lower() or (
                        "intro" in target_query_lower and ("first" in tx.instruction.lower() or "intro" in tx.instruction.lower())
                    ):
                        target_tx = tx
                        break

        if not target_tx:
            return False, f"Could not find an active earlier edit matching '{target_tx_query}' to restore.", None

        before_segments = copy.deepcopy(self.timeline.segments)

        # Handle speed_range or reorder_segments reversion
        if target_tx.operation_type in ("speed_range", "reorder_segments"):
            if target_tx.inverse_segments is not None:
                self.timeline.segments = copy.deepcopy(target_tx.inverse_segments)
                target_tx.status = "undone"
                restore_tx = self.record_transaction(
                    instruction=f"Revert earlier edit: {target_tx.instruction}",
                    operation_type="restore_transaction",
                    before_segments=before_segments,
                    after_segments=self.timeline.segments,
                    details={"reverted_tx_id": target_tx.id},
                )
                return True, f"Reverted earlier edit: '{target_tx.instruction}'", restore_tx

        cut_source_ranges = target_tx.details.get("cut_source_ranges", [])
        if not cut_source_ranges:
            return False, f"Transaction '{target_tx.id}' did not record any cut source ranges to restore.", None

        before_segments = copy.deepcopy(self.timeline.segments)

        # Re-splice the cut source segments back into active segments in source order
        restored_segments: List[ClipSegment] = []
        seg_counter = len(self.timeline.segments) + 1

        for r_start, r_end, r_speed in cut_source_ranges:
            # Check if this range is already present
            restored_segments.append(
                ClipSegment(
                    segment_id=f"seg_restored_{seg_counter}",
                    source_start_ticks=r_start,
                    source_end_ticks=r_end,
                    speed_ratio=r_speed,
                )
            )
            seg_counter += 1

        # Merge active segments with restored segments and sort by source start time
        all_segments = copy.deepcopy(self.timeline.segments) + restored_segments
        all_segments.sort(key=lambda s: s.source_start_ticks)
        self.timeline.segments = all_segments


        # Record this restore as its own undoable transaction
        restore_tx = self.record_transaction(
            instruction=f"Restore earlier edit: {target_tx.instruction}",
            operation_type="restore_transaction",
            before_segments=before_segments,
            after_segments=self.timeline.segments,
            details={
                "restored_tx_id": target_tx.id,
                "restored_ranges": cut_source_ranges,
            },
        )

        return True, f"Restored content from earlier edit: '{target_tx.instruction}'", restore_tx
