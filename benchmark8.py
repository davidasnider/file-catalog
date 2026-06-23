import asyncio
import time
import os
import threading

def sync_read():
    # simulate file I/O
    time.sleep(1)

async def block_loop():
    sync_read()

async def non_block_loop():
    await asyncio.to_thread(sync_read)

async def monitor_event_loop(delays):
    # measure time between loop iterations
    while True:
        start = time.perf_counter()
        await asyncio.sleep(0.01) # Try to wake up every 10ms
        end = time.perf_counter()
        # record how long the interval was
        delays.append(end - start)

async def measure(func):
    delays = []
    bg_task = asyncio.create_task(monitor_event_loop(delays))

    await asyncio.sleep(0.05)
    delays.clear()

    start_time = time.perf_counter()
    await func()
    end_time = time.perf_counter()

    bg_task.cancel()

    # We expected ~0.01s between wakeups. Any value significantly higher
    # means the event loop was blocked.
    # The max value indicates the longest single blockage.
    max_blockage = max(delays) if delays else 0
    print(f"Total time: {end_time - start_time:.4f} seconds")
    print(f"Max loop blockage (interval): {max_blockage:.4f} seconds (expected ~0.01)")
    print(f"Loop iterations during task: {len(delays)}")

async def main():
    print("--- Sync Read (Blocking) ---")
    await measure(block_loop)

    print("\n--- Async Read (to_thread) ---")
    await measure(non_block_loop)

if __name__ == "__main__":
    asyncio.run(main())
