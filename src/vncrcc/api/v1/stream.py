"""Server-Sent Events streaming endpoint for real-time dashboard updates."""
import logging
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from ...broadcast import BROADCASTER
from ...rate_limit import limiter

logger = logging.getLogger("vncrcc.api.stream")

router = APIRouter(prefix="/stream")


@router.get("")
@limiter.exempt
async def stream_dashboard(request: Request) -> StreamingResponse:
    """SSE endpoint for real-time dashboard updates.

    Connect with EventSource('/api/v1/stream') to receive push updates.
    Each 'update' event contains the full dashboard JSON payload.
    """
    async def event_generator():
        yield "retry: 3000\n\n"

        async for message in BROADCASTER.subscribe():
            if await request.is_disconnected():
                break
            yield message

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )
