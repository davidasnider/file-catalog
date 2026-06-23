import asyncio
import time
import os
import random

async def background_task(delays):
    while True:
        start = time.perf_counter()
        await asyncio.sleep(0.01)
        end = time.perf_counter()
        delays.append(end - start - 0.01)

def sync_read(file_path):
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()

async def to_thread_read(file_path):
    return await asyncio.to_thread(sync_read, file_path)

async def main():
    file_path = "large_text.txt"
    if not os.path.exists(file_path):
        with open(file_path, "w") as f:
            f.write("This is a large text file. " * 5000000)

    # 1. Benchmark synchronous read
    print("--- Synchronous I/O ---")
    delays = []
    bg_task = asyncio.create_task(background_task(delays))
    await asyncio.sleep(0.05)

    start_time = time.perf_counter()
    res = sync_read(file_path)
    end_time = time.perf_counter()
    bg_task.cancel()

    max_delay_sync = max(delays) if delays else 0
    print(f"Read time: {end_time - start_time:.4f} seconds")
    print(f"Max event loop delay: {max_delay_sync:.4f} seconds")

    await asyncio.sleep(0.1)

    # 2. Benchmark to_thread
    print("--- Async I/O (to_thread) ---")
    delays = []
    bg_task = asyncio.create_task(background_task(delays))
    await asyncio.sleep(0.05)

    start_time = time.perf_counter()
    res2 = await to_thread_read(file_path)
    end_time = time.perf_counter()
    bg_task.cancel()

    max_delay_async = max(delays) if delays else 0
    print(f"Read time: {end_time - start_time:.4f} seconds")
    print(f"Max event loop delay: {max_delay_async:.4f} seconds")

if __name__ == "__main__":
    asyncio.run(main())
