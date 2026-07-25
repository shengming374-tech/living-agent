"""Local lexical ranking after repository-enforced memory scope filtering."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass

from living_agent.models.memory import MemoryFactuality, MemoryLayer, MemoryNode

_TOKEN_PATTERN = re.compile(r"[a-z0-9_]+|[\u4e00-\u9fff]+", re.IGNORECASE)
_STOP_FEATURES = {
    "about",
    "that",
    "this",
    "what",
    "when",
    "where",
    "which",
    "with",
    "什么",
    "他们",
    "你们",
    "我们",
    "可以",
    "怎么",
    "记得",
    "这个",
    "那个",
}
_REALITY_FACTUALITIES = {
    MemoryFactuality.VERIFIED,
    MemoryFactuality.REPORTED,
    MemoryFactuality.INFERRED,
}


@dataclass(frozen=True, slots=True)
class RankedMemory:
    memory: MemoryNode
    lexical_score: float
    semantic_score: float | None
    final_score: float


class MemoryRecallService:
    def rank(
        self,
        query: str,
        memories: list[MemoryNode],
        *,
        limit: int,
        semantic_scores: dict[str, float] | None = None,
        min_score: float = 0.0,
        context_bonus: float = 0.0,
    ) -> list[MemoryNode]:
        return [
            item.memory
            for item in self.rank_with_scores(
                query,
                memories,
                limit=limit,
                semantic_scores=semantic_scores,
                min_score=min_score,
                context_bonus=context_bonus,
            )
        ]

    def rank_with_scores(
        self,
        query: str,
        memories: list[MemoryNode],
        *,
        limit: int,
        semantic_scores: dict[str, float] | None = None,
        min_score: float = 0.0,
        context_bonus: float = 0.0,
    ) -> list[RankedMemory]:
        query_features = self._features(query)
        if not query_features:
            return []
        ranked: list[RankedMemory] = []
        normalized_query = self._normalize(query)
        for memory in memories:
            if memory.factuality not in _REALITY_FACTUALITIES:
                continue
            if memory.memory_layer is MemoryLayer.FACT:
                continue
            searchable = f"{memory.subject} {self._content_text(memory)}"
            memory_features = self._features(searchable)
            overlap = query_features.intersection(memory_features)
            semantic = (semantic_scores or {}).get(memory.id)
            if not overlap and semantic is None:
                continue
            lexical = (
                len(overlap) / math.sqrt(len(query_features) * len(memory_features))
                if overlap and memory_features
                else 0.0
            )
            normalized_memory = self._normalize(searchable)
            exact_bonus = 0.15 if normalized_query in normalized_memory else 0.0
            if semantic is None:
                score = lexical * 0.7 + memory.importance * 0.2 + memory.confidence * 0.1
            else:
                score = (
                    semantic * 0.65
                    + lexical * 0.2
                    + memory.importance * 0.1
                    + memory.confidence * 0.05
                )
            final_score = score + exact_bonus + context_bonus
            if final_score < min_score:
                continue
            ranked.append(
                RankedMemory(
                    memory=memory,
                    lexical_score=lexical,
                    semantic_score=semantic,
                    final_score=final_score,
                )
            )
        ranked.sort(
            key=lambda item: (item.final_score, item.memory.updated_at),
            reverse=True,
        )
        return ranked[:limit]

    @classmethod
    def _features(cls, text: str) -> set[str]:
        features: set[str] = set()
        for token in _TOKEN_PATTERN.findall(cls._normalize(text)):
            if cls._is_cjk(token):
                if len(token) <= 2:
                    features.add(token)
                else:
                    features.update(
                        token[index : index + 2] for index in range(len(token) - 1)
                    )
            elif len(token) >= 2:
                features.add(token)
        return features - _STOP_FEATURES

    @staticmethod
    def _content_text(memory: MemoryNode) -> str:
        if isinstance(memory.content, str):
            return memory.content
        return json.dumps(memory.content, ensure_ascii=False, sort_keys=True)

    @staticmethod
    def _normalize(text: str) -> str:
        return " ".join(text.casefold().split())

    @staticmethod
    def _is_cjk(token: str) -> bool:
        return bool(token) and all("\u4e00" <= character <= "\u9fff" for character in token)
