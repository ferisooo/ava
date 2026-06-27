"""Core logic for deleting all messages authored by a specific user.

Discord has no single API call for "delete everything this user posted", so we
walk channel history, match by author, and delete. Two wrinkles drive the
design:

* Bulk deletion (``delete_messages``) only works for messages **younger than 14
  days** and only in batches of up to 100. Older messages must be deleted one
  at a time.
* We want this to be safe to run against a whole guild, so the work is reported
  back per channel via a small result object.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

import discord

# Messages strictly older than this cannot be bulk-deleted by Discord. We use a
# small safety margin so messages right on the boundary don't fail a bulk call.
BULK_DELETE_MAX_AGE = timedelta(days=14) - timedelta(minutes=1)
BULK_DELETE_CHUNK = 100


@dataclass
class ChannelPurgeResult:
    channel: discord.abc.GuildChannel
    deleted: int = 0
    failed: int = 0


@dataclass
class PurgeSummary:
    user_id: int
    results: list[ChannelPurgeResult]

    @property
    def total_deleted(self) -> int:
        return sum(r.deleted for r in self.results)

    @property
    def total_failed(self) -> int:
        return sum(r.failed for r in self.results)

    @property
    def channels_touched(self) -> int:
        return sum(1 for r in self.results if r.deleted or r.failed)


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def purge_user_in_channel(
    channel: "discord.abc.Messageable",
    user: discord.abc.Snowflake,
    *,
    limit: Optional[int] = None,
    before: Optional[datetime] = None,
    after: Optional[datetime] = None,
) -> ChannelPurgeResult:
    """Delete messages authored by ``user`` in a single channel.

    ``limit`` caps how many *of the user's* messages are deleted (not how many
    are scanned). ``None`` means "all of them".
    """
    result = ChannelPurgeResult(channel=channel)  # type: ignore[arg-type]
    cutoff = _now() - BULK_DELETE_MAX_AGE

    recent_batch: list[discord.Message] = []

    async def flush_recent() -> None:
        nonlocal recent_batch
        if not recent_batch:
            return
        batch, recent_batch = recent_batch, []
        try:
            # delete_messages handles batches of up to 100 recent messages.
            await channel.delete_messages(batch)  # type: ignore[attr-defined]
            result.deleted += len(batch)
        except discord.HTTPException:
            # Fall back to deleting the batch one by one.
            for message in batch:
                await _delete_one(message, result)

    # We scan newest-first. ``limit=None`` on history() means scan everything.
    async for message in channel.history(limit=None, before=before, after=after):
        if message.author.id != user.id:
            continue

        if message.created_at > cutoff:
            recent_batch.append(message)
            if len(recent_batch) >= BULK_DELETE_CHUNK:
                await flush_recent()
        else:
            # Too old for bulk deletion; flush whatever recent ones we have so
            # ordering stays predictable, then delete this one individually.
            await flush_recent()
            await _delete_one(message, result)

        if limit is not None and (result.deleted + len(recent_batch)) >= limit:
            break

    await flush_recent()
    return result


async def _delete_one(message: discord.Message, result: ChannelPurgeResult) -> None:
    try:
        await message.delete()
        result.deleted += 1
        # Be gentle with the per-message delete rate limit.
        await asyncio.sleep(0.35)
    except discord.NotFound:
        # Already gone — nothing to do.
        pass
    except discord.HTTPException:
        result.failed += 1


async def purge_user_in_guild(
    channels: Iterable["discord.abc.Messageable"],
    user: discord.abc.Snowflake,
    *,
    limit_per_channel: Optional[int] = None,
) -> PurgeSummary:
    """Run :func:`purge_user_in_channel` across many channels."""
    results: list[ChannelPurgeResult] = []
    for channel in channels:
        result = await purge_user_in_channel(channel, user, limit=limit_per_channel)
        results.append(result)
    return PurgeSummary(user_id=user.id, results=results)
