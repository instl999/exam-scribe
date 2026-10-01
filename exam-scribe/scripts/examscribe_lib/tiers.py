"""Model tiers.

Every tier runs the SAME checks: quotes verified against the book, numbers
recomputed, independent verification with planted false claims (canaries),
blind re-solving of answer keys, and coverage against the inventory. What
changes is how much work one task contains and how much creative freedom the
writer gets. Weaker models get smaller tasks, more canaries per batch, more
attempts, and no AI-invented extras beyond mnemonics.
"""
from __future__ import annotations

from .common import ESError

TIERS: dict[str, dict] = {
    "strict": {
        "summary": "Default. Small or local models, or any model you have not tested: one section per task, "
                   "small batches, 3 canaries per 12 claims, only mnemonics as AI extras.",
        "max_source_tokens": 3500,
        "questions_per_section": 4,
        "max_short_per_section": 1,
        "verify_batch": 12,
        "canaries_per_batch": 3,
        "solve_batch": 6,
        "reconcile_canaries": 1,
        "max_attempts": 4,
        "ai_fields": ("ai-mnemonic",),
        "max_skip_ratio": 0.25,
        "max_unsure_ratio": 0.30,
        "require_covers": True,
        "quote_min_words": 4,
        "quote_max_words": 45,
        "definition_max_words": 70,
        "approx_match": 0.94,
        "whole_chapter_tasks": False,
    },
    "standard": {
        "summary": "Capable mid-size models: larger sections per task, 3 canaries per 20 claims, analogies and "
                   "exam tips allowed (labeled as AI-added).",
        "max_source_tokens": 9000,
        "questions_per_section": 5,
        "max_short_per_section": 2,
        "verify_batch": 20,
        "canaries_per_batch": 3,
        "solve_batch": 12,
        "reconcile_canaries": 1,
        "max_attempts": 3,
        "ai_fields": ("ai-mnemonic", "ai-analogy", "ai-tip"),
        "max_skip_ratio": 0.35,
        "max_unsure_ratio": 0.40,
        "require_covers": True,
        "quote_min_words": 4,
        "quote_max_words": 50,
        "definition_max_words": 80,
        "approx_match": 0.92,
        "whole_chapter_tasks": False,
    },
    "frontier": {
        "summary": "Frontier models: whole chapters per task when they fit, 3 canaries per 30 claims, all "
                   "labeled AI extras allowed. The checks stay the same.",
        "max_source_tokens": 30000,
        "questions_per_section": 6,
        "max_short_per_section": 3,
        "verify_batch": 30,
        "canaries_per_batch": 3,
        "solve_batch": 20,
        "reconcile_canaries": 1,
        "max_attempts": 3,
        "ai_fields": ("ai-mnemonic", "ai-analogy", "ai-tip", "ai-example"),
        "max_skip_ratio": 0.40,
        "max_unsure_ratio": 0.50,
        "require_covers": True,
        "quote_min_words": 4,
        "quote_max_words": 60,
        "definition_max_words": 90,
        "approx_match": 0.92,
        "whole_chapter_tasks": True,
    },
}

AI_FIELD_LABELS = {
    "ai-mnemonic": "Memory aid",
    "ai-analogy": "Analogy",
    "ai-tip": "Exam tip",
    "ai-example": "Extra example",
}


def tier_params(tier: str) -> dict:
    if tier not in TIERS:
        raise ESError(f"Unknown tier '{tier}'.", f"Use one of: {', '.join(TIERS)}")
    return TIERS[tier]
