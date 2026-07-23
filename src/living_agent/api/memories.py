"""Scoped memory candidate and owner management API."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status

from living_agent.api.dependencies import get_authority, get_memory_service
from living_agent.memory.repository import MemoryNotFoundError, MemoryVersionConflictError
from living_agent.memory.service import MemoryAccessError, MemoryService
from living_agent.models.events import AuthorityLevel, TrustedEvent
from living_agent.models.memory import (
    CandidateStatus,
    MemoryCandidate,
    MemoryCandidateCreate,
    MemoryCommitResult,
    MemoryEmbeddingStatus,
    MemoryMergeRequest,
    MemoryNode,
    MemoryReindexResult,
    MemorySplitRequest,
    MemoryStatus,
    MemoryUpdate,
    MemoryUsage,
    MemoryVersion,
)
from living_agent.trust.authority import AuthorityResolver

router = APIRouter(prefix="/v1/memories", tags=["memories"])

ActorHeader = Annotated[str, Header(alias="X-Actor-ID")]
ConversationHeader = Annotated[str | None, Header(alias="X-Conversation-ID")]
AuthorityDependency = Annotated[AuthorityResolver, Depends(get_authority)]
MemoryDependency = Annotated[MemoryService, Depends(get_memory_service)]


def _owner(actor_id: str, authority: AuthorityResolver) -> bool:
    return authority.resolve(actor_id, authenticated=True) is AuthorityLevel.OWNER


def _require_owner(actor_id: str, authority: AuthorityResolver) -> None:
    if not _owner(actor_id, authority):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="owner authority required"
        )


def _translate_error(exc: Exception) -> HTTPException:
    if isinstance(exc, MemoryNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, MemoryAccessError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="memory scope denied")
    if isinstance(exc, MemoryVersionConflictError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="memory operation failed")


async def _accessible(
    memory_id: str,
    *,
    actor_id: str,
    conversation_id: str | None,
    authority: AuthorityResolver,
    memories: MemoryService,
) -> MemoryNode:
    try:
        return await memories.get_accessible(
            memory_id,
            actor_id=actor_id,
            conversation_id=conversation_id,
            owner=_owner(actor_id, authority),
        )
    except (MemoryNotFoundError, MemoryAccessError) as exc:
        raise _translate_error(exc) from exc


@router.post("/candidates", response_model=MemoryCandidate, status_code=status.HTTP_201_CREATED)
async def create_candidate(
    candidate: MemoryCandidateCreate,
    actor_id: ActorHeader,
    memories: MemoryDependency,
) -> MemoryCandidate:
    try:
        return await memories.create_candidate(candidate, proposer_id=actor_id)
    except Exception as exc:
        raise _translate_error(exc) from exc


@router.get("/candidates", response_model=list[MemoryCandidate])
async def list_candidates(
    actor_id: ActorHeader,
    authority: AuthorityDependency,
    memories: MemoryDependency,
    candidate_status: Annotated[CandidateStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[MemoryCandidate]:
    _require_owner(actor_id, authority)
    return await memories.candidates(status=candidate_status, limit=limit)


@router.post("/candidates/{candidate_id}/commit", response_model=MemoryCommitResult)
async def commit_candidate(
    candidate_id: str,
    actor_id: ActorHeader,
    authority: AuthorityDependency,
    memories: MemoryDependency,
) -> MemoryCommitResult:
    _require_owner(actor_id, authority)
    try:
        return await memories.commit_candidate(candidate_id, actor_id=actor_id)
    except (MemoryNotFoundError, MemoryVersionConflictError) as exc:
        raise _translate_error(exc) from exc


@router.post("/candidates/{candidate_id}/reject", response_model=MemoryCandidate)
async def reject_candidate(
    candidate_id: str,
    actor_id: ActorHeader,
    authority: AuthorityDependency,
    memories: MemoryDependency,
) -> MemoryCandidate:
    _require_owner(actor_id, authority)
    try:
        return await memories.reject_candidate(candidate_id, actor_id=actor_id)
    except (MemoryNotFoundError, MemoryVersionConflictError) as exc:
        raise _translate_error(exc) from exc


@router.get("", response_model=list[MemoryNode])
async def search_memories(
    actor_id: ActorHeader,
    authority: AuthorityDependency,
    memories: MemoryDependency,
    conversation_id: ConversationHeader = None,
    query: str = Query(default="", max_length=500),
    include_deleted: bool = False,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[MemoryNode]:
    return await memories.search(
        actor_id=actor_id,
        conversation_id=conversation_id,
        owner=_owner(actor_id, authority),
        query=query,
        include_deleted=include_deleted,
        limit=limit,
    )


@router.post("/merge", response_model=MemoryNode)
async def merge_memories(
    request: MemoryMergeRequest,
    actor_id: ActorHeader,
    authority: AuthorityDependency,
    memories: MemoryDependency,
) -> MemoryNode:
    _require_owner(actor_id, authority)
    try:
        return await memories.merge(request, actor_id=actor_id)
    except (MemoryNotFoundError, MemoryVersionConflictError) as exc:
        raise _translate_error(exc) from exc


@router.get("/embedding-status", response_model=MemoryEmbeddingStatus)
async def memory_embedding_status(
    actor_id: ActorHeader,
    authority: AuthorityDependency,
    memories: MemoryDependency,
) -> MemoryEmbeddingStatus:
    _require_owner(actor_id, authority)
    return await memories.embedding_status()


@router.post("/reindex", response_model=MemoryReindexResult)
async def reindex_memories(
    actor_id: ActorHeader,
    authority: AuthorityDependency,
    memories: MemoryDependency,
) -> MemoryReindexResult:
    _require_owner(actor_id, authority)
    return await memories.reindex_embeddings(actor_id=actor_id)


@router.get("/{memory_id}", response_model=MemoryNode)
async def get_memory(
    memory_id: str,
    actor_id: ActorHeader,
    authority: AuthorityDependency,
    memories: MemoryDependency,
    conversation_id: ConversationHeader = None,
) -> MemoryNode:
    return await _accessible(
        memory_id,
        actor_id=actor_id,
        conversation_id=conversation_id,
        authority=authority,
        memories=memories,
    )


@router.patch("/{memory_id}", response_model=MemoryNode)
async def update_memory(
    memory_id: str,
    update: MemoryUpdate,
    actor_id: ActorHeader,
    authority: AuthorityDependency,
    memories: MemoryDependency,
) -> MemoryNode:
    _require_owner(actor_id, authority)
    try:
        return await memories.update(memory_id, update, actor_id=actor_id)
    except (MemoryNotFoundError, MemoryVersionConflictError) as exc:
        raise _translate_error(exc) from exc


@router.delete("/{memory_id}", response_model=MemoryNode)
async def delete_memory(
    memory_id: str,
    actor_id: ActorHeader,
    authority: AuthorityDependency,
    memories: MemoryDependency,
    expected_version: int = Query(ge=1),
) -> MemoryNode:
    _require_owner(actor_id, authority)
    try:
        return await memories.change_status(
            memory_id,
            expected_version=expected_version,
            status=MemoryStatus.DELETED,
            actor_id=actor_id,
        )
    except (MemoryNotFoundError, MemoryVersionConflictError) as exc:
        raise _translate_error(exc) from exc


@router.post("/{memory_id}/restore", response_model=MemoryNode)
async def restore_memory(
    memory_id: str,
    actor_id: ActorHeader,
    authority: AuthorityDependency,
    memories: MemoryDependency,
    expected_version: int = Query(ge=1),
) -> MemoryNode:
    _require_owner(actor_id, authority)
    try:
        return await memories.change_status(
            memory_id,
            expected_version=expected_version,
            status=MemoryStatus.ACTIVE,
            actor_id=actor_id,
        )
    except (MemoryNotFoundError, MemoryVersionConflictError) as exc:
        raise _translate_error(exc) from exc


@router.post("/{memory_id}/split", response_model=list[MemoryNode])
async def split_memory(
    memory_id: str,
    request: MemorySplitRequest,
    actor_id: ActorHeader,
    authority: AuthorityDependency,
    memories: MemoryDependency,
) -> list[MemoryNode]:
    _require_owner(actor_id, authority)
    try:
        return await memories.split(memory_id, request, actor_id=actor_id)
    except (MemoryNotFoundError, MemoryVersionConflictError) as exc:
        raise _translate_error(exc) from exc


@router.get("/{memory_id}/versions", response_model=list[MemoryVersion])
async def memory_versions(
    memory_id: str,
    actor_id: ActorHeader,
    authority: AuthorityDependency,
    memories: MemoryDependency,
    conversation_id: ConversationHeader = None,
) -> list[MemoryVersion]:
    await _accessible(
        memory_id,
        actor_id=actor_id,
        conversation_id=conversation_id,
        authority=authority,
        memories=memories,
    )
    try:
        return await memories.versions(memory_id)
    except MemoryNotFoundError as exc:
        raise _translate_error(exc) from exc


@router.get("/{memory_id}/sources", response_model=list[TrustedEvent])
async def memory_sources(
    memory_id: str,
    actor_id: ActorHeader,
    authority: AuthorityDependency,
    memories: MemoryDependency,
    conversation_id: ConversationHeader = None,
) -> list[TrustedEvent]:
    await _accessible(
        memory_id,
        actor_id=actor_id,
        conversation_id=conversation_id,
        authority=authority,
        memories=memories,
    )
    return await memories.sources(memory_id)


@router.get("/{memory_id}/usages", response_model=list[MemoryUsage])
async def memory_usages(
    memory_id: str,
    actor_id: ActorHeader,
    authority: AuthorityDependency,
    memories: MemoryDependency,
    conversation_id: ConversationHeader = None,
) -> list[MemoryUsage]:
    await _accessible(
        memory_id,
        actor_id=actor_id,
        conversation_id=conversation_id,
        authority=authority,
        memories=memories,
    )
    return await memories.usages(memory_id)
