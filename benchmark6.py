import asyncio
import time
import os

async def background_task(delays):
    while True:
        start = time.perf_counter()
        await asyncio.sleep(0.01)
        end = time.perf_counter()
        # record how late it woke up
        delays.append(end - start - 0.01)

def do_sync_read(file_path):
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()

async def block_loop(file_path):
    do_sync_read(file_path)

async def non_block_loop(file_path):
    await asyncio.to_thread(do_sync_read, file_path)

async def measure(func, file_path):
    delays = []
    bg_task = asyncio.create_task(background_task(delays))

    # give it a moment to start
    await asyncio.sleep(0.05)

    # clear initial delays
    delays.clear()

    start_time = time.perf_counter()
    await func(file_path)
    end_time = time.perf_counter()

    bg_task.cancel()

    # Calculate the max delay and total delay
    max_delay = max(delays) if delays else 0
    total_delay = sum(d for d in delays if d > 0)

    # If the function blocks the event loop completely, the background task
    # won't run until after the function finishes, so there might only be 1 delay
    # recorded, which will be the entire duration of the block.
    # However, if it yields, there will be multiple small delays.

    print(f"Time: {end_time - start_time:.4f} seconds")
    print(f"Max event loop blocked for: {max_delay:.4f} seconds")
    print(f"Delays count: {len(delays)}")

async def main():
    file_path = "large_text.txt"

    print("--- Original Sync Read (Blocking) ---")
    await measure(block_loop, file_path)

    print("\n--- Async Read (to_thread) ---")
    await measure(non_block_loop, file_path)

if __name__ == "__main__":
    asyncio.run(main())
