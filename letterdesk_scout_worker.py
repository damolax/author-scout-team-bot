"""Background research worker for Letter Desk Phase 3, never an email worker.

Only enabled with LETTERDESK_SCOUT_WRITE_ENABLED=true on isolated staging.
Claims one queued job at a time; all runs are bounded and deduplicated in Neon.
"""
import asyncio
import os

from letterdesk_scout_api import restore_stale_jobs, run_next_queued_job


async def letterdesk_discovery_worker(engine, poll_seconds=7):
    if os.getenv("LETTERDESK_STAGING_ISOLATED","false").lower() not in {"true","yes","1"}:
        raise RuntimeError("Phase 3 discovery worker requires isolated staging")
    if os.getenv("LETTERDESK_SCOUT_WRITE_ENABLED","false").lower() not in {"true","yes","1"}:
        return
    try:
        await asyncio.to_thread(restore_stale_jobs,engine)
    except Exception as e:
        print("LETTERDESK_SCOUT_RECOVERY_ERROR="+type(e).__name__)
    while True:
        try:
            worked=await asyncio.to_thread(run_next_queued_job,engine)
            if not worked:await asyncio.sleep(max(5,poll_seconds))
            else:await asyncio.sleep(1)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print("LETTERDESK_SCOUT_WORKER_ERROR="+type(e).__name__)
            await asyncio.sleep(max(10,poll_seconds))
