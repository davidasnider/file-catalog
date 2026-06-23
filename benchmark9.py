import asyncio
import time
import os
from src.plugins.text_extractor import TextExtractorPlugin

async def monitor_event_loop(delays):
    while True:
        start = time.perf_counter()
        await asyncio.sleep(0.01)
        end = time.perf_counter()
        delays.append(end - start)

async def measure(func, file_path):
    delays = []
    bg_task = asyncio.create_task(monitor_event_loop(delays))

    await asyncio.sleep(0.05)
    delays.clear()

    start_time = time.perf_counter()
    await func(file_path)
    end_time = time.perf_counter()

    bg_task.cancel()

    max_blockage = max(delays) if delays else 0
    # when the loop is blocked, the background task doesn't get to run,
    # so there won't be any delays recorded during the blockage.
    # To properly measure blockage, if there are 0 delays, it means the whole time was blocked.
    # If there are delays, we take the max of the intervals minus the expected interval (0.01)

    actual_blockage = max_blockage
    if len(delays) == 0:
        actual_blockage = end_time - start_time

    print(f"Extraction time: {end_time - start_time:.4f} seconds")
    print(f"Max event loop blockage: {actual_blockage:.4f} seconds")
    print(f"Event loop iterations: {len(delays)}")

async def main():
    file_path = "large_text.txt"

    plugin = TextExtractorPlugin()

    print("--- Original Sync Read (Blocking) ---")
    async def run_sync(fp):
        await plugin.analyze(fp, "text/plain", {})
    await measure(run_sync, file_path)

    class AsyncTextExtractorPlugin(TextExtractorPlugin):
        async def analyze(self, file_path, mime_type, context):
            if mime_type == "text/plain":
                def sync_read():
                    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                        return f.read()

                extracted_text = await asyncio.to_thread(sync_read)
                return {"text": extracted_text, "extracted": True, "source": "TextExtractorPlugin"}
            return await super().analyze(file_path, mime_type, context)

    plugin_async = AsyncTextExtractorPlugin()

    print("\n--- Async Read (to_thread) ---")
    async def run_async(fp):
        await plugin_async.analyze(fp, "text/plain", {})
    await measure(run_async, file_path)

if __name__ == "__main__":
    asyncio.run(main())
