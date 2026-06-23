import asyncio
import time
import os
import aiofiles

async def background_task(delays):
    while True:
        start = time.perf_counter()
        await asyncio.sleep(0.005)
        end = time.perf_counter()
        delays.append(end - start - 0.005)

def sync_read(file_path):
    # Try to block the loop
    time.sleep(1) # simulate slow I/O
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()

async def async_read(file_path):
    await asyncio.sleep(1) # simulate slow I/O without blocking
    async with aiofiles.open(file_path, "r", encoding="utf-8", errors="replace") as f:
        return await f.read()

async def to_thread_read(file_path):
    def read_func():
        time.sleep(1)
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    return await asyncio.to_thread(read_func)


async def main():
    file_path = "large_text.txt"

    delays = []
    bg_task = asyncio.create_task(background_task(delays))
    start_time = time.perf_counter()
    res = sync_read(file_path)
    end_time = time.perf_counter()
    bg_task.cancel()
    print(f"Sync - Read time: {end_time - start_time:.4f}s, Max event loop delay: {max(delays) if delays else 0:.4f}s")

    # Try with aiofiles if available, or asyncio.to_thread
    try:
        import aiofiles
        has_aiofiles = True
    except ImportError:
        has_aiofiles = False

    if has_aiofiles:
        delays.clear()
        bg_task = asyncio.create_task(background_task(delays))
        start_time = time.perf_counter()
        res = await async_read(file_path)
        end_time = time.perf_counter()
        bg_task.cancel()
        print(f"aiofiles - Read time: {end_time - start_time:.4f}s, Max event loop delay: {max(delays) if delays else 0:.4f}s")

    delays.clear()
    bg_task = asyncio.create_task(background_task(delays))
    start_time = time.perf_counter()
    res = await to_thread_read(file_path)
    end_time = time.perf_counter()
    bg_task.cancel()
    print(f"to_thread - Read time: {end_time - start_time:.4f}s, Max event loop delay: {max(delays) if delays else 0:.4f}s")

if __name__ == "__main__":
    asyncio.run(main())
