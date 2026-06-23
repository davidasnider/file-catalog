import asyncio
import time
import os
from src.plugins.text_extractor import TextExtractorPlugin

async def ping(delays):
    # Continuously run a tight loop that yields often and measures the time it gets blocked
    while True:
        start = time.perf_counter()
        await asyncio.sleep(0) # yield
        end = time.perf_counter()
        delays.append(end - start)

async def measure(func, file_path):
    delays = []
    bg_task = asyncio.create_task(ping(delays))

    # give it a moment to start
    await asyncio.sleep(0.05)

    # clear initial delays
    delays.clear()

    start_time = time.perf_counter()
    await func(file_path)
    end_time = time.perf_counter()

    bg_task.cancel()

    max_delay = max(delays) if delays else 0
    total_delay = sum(delays)

    print(f"Extraction time: {end_time - start_time:.4f} seconds")
    print(f"Max event loop blockage: {max_delay:.4f} seconds")

async def main():
    file_path = "large_text.txt"

    plugin = TextExtractorPlugin()

    print("--- Original Sync Read (Blocking) ---")
    async def run_sync(fp):
        await plugin.analyze(fp, "text/plain", {})
    await measure(run_sync, file_path)

    # 2. Let's patch the plugin to use asyncio.to_thread and try again
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
