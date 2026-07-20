"""Owner-controlled embedding API with brokered external data transfer."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status

from living_agent.api.dependencies import (
    get_authority,
    get_embedding_service,
)
from living_agent.api.management import require_owner
from living_agent.providers.embeddings import (
    EmbeddingLimitError,
    EmbeddingPermissionError,
    EmbeddingProviderError,
    EmbeddingRequest,
    EmbeddingResult,
    EmbeddingService,
    EmbeddingStatus,
)
from living_agent.trust.authority import AuthorityResolver

router = APIRouter(prefix="/v1/embeddings", tags=["embeddings"])

ActorHeader = Annotated[str, Header(alias="X-Actor-ID")]
AuthorityDependency = Annotated[AuthorityResolver, Depends(get_authority)]
EmbeddingDependency = Annotated[EmbeddingService, Depends(get_embedding_service)]


def _provider_http_error(exc: EmbeddingProviderError) -> HTTPException:
    if exc.code == "provider_timeout":
        return HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="embedding provider timed out",
        )
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail="embedding provider request failed",
    )


@router.get("/status", response_model=EmbeddingStatus)
async def embedding_status(
    actor_id: ActorHeader,
    authority: AuthorityDependency,
    embeddings: EmbeddingDependency,
) -> EmbeddingStatus:
    require_owner(actor_id, authority)
    return embeddings.status()


@router.post("", response_model=EmbeddingResult)
async def generate_embeddings(
    request: EmbeddingRequest,
    actor_id: ActorHeader,
    authority: AuthorityDependency,
    embeddings: EmbeddingDependency,
) -> EmbeddingResult:
    require_owner(actor_id, authority)
    try:
        return await embeddings.generate(request.input, actor_id=actor_id)
    except EmbeddingLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    except EmbeddingPermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="embedding capability denied",
        ) from exc
    except EmbeddingProviderError as exc:
        raise _provider_http_error(exc) from exc
