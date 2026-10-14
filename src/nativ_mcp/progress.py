"""Keep opted-in MCP clients informed while long tools are running."""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import suppress

logger = logging.getLogger(__name__)
PROGRESS_INTERVAL_SECONDS = 15


async def tool_progress(context, call_next):
    """Send elapsed-time progress without changing tool inputs or results."""
    if context.method != "tools/call":
        return await call_next(context)

    tool = (context.params or {}).get("name", "unknown")
    started = time.monotonic()
    logger.info("event=mcp_tool_start tool=%s", tool)

    async def report():
        try:
            while True:
                # This counts elapsed seconds, not percent complete: providers
                # do not expose reliable completion estimates.
                await context.session.report_progress(
                    time.monotonic() - started,
                    message="Nativ is still processing this request.",
                )
                await asyncio.sleep(PROGRESS_INTERVAL_SECONDS)
        except Exception as exc:
            # A disconnected client must not turn completed localization into
            # a tool failure. The request's normal cancellation still applies.
            logger.info("event=mcp_progress_stopped error_type=%s", type(exc).__name__)

    # ServerSession makes progress a no-op when not requested. Direct (local)
    # dispatch keeps its callback outside wire metadata, so report on both
    # transports rather than gating on a JSON-RPC progress token.
    heartbeat = asyncio.create_task(report())
    try:
        return await call_next(context)
    finally:
        heartbeat.cancel()
        with suppress(asyncio.CancelledError):
            await heartbeat
        logger.info("event=mcp_tool_end tool=%s elapsed_s=%.3f", tool, time.monotonic() - started)
