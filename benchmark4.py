import asyncio
import time
import os
import threading
from src.plugins.text_extractor import TextExtractorPlugin

async def monitor_event_loop(delays):
    # This runs continuously and records the exact time difference
    # between when a sleep wakes up vs when it was scheduled.
    while True:
        start = time.perf_counter()
        await asyncio.sleep(0.001)
        end = time.perf_counter()
        delays.append(end - start - 0.001)

async def main():
    file_path = "large_text.txt"

    plugin = TextExtractorPlugin()

    # Run original synchronous blocking read (through the plugin directly)
    print("--- Original Sync Read ---")
    delays = []
    monitor_task = asyncio.create_task(monitor_event_loop(delays))

    start_time = time.perf_counter()
    res = await plugin.analyze(file_path, "text/plain", {})
    end_time = time.perf_counter()

    monitor_task.cancel()

    max_delay = max(delays) if delays else 0
    print(f"Extraction time: {end_time - start_time:.4f} seconds")
    print(f"Max event loop blocked for: {max_delay:.4f} seconds")

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
    delays = []
    monitor_task = asyncio.create_task(monitor_event_loop(delays))

    start_time = time.perf_counter()
    res = await plugin_async.analyze(file_path, "text/plain", {})
    end_time = time.perf_counter()

    monitor_task.cancel()

    max_delay = max(delays) if delays else 0
    print(f"Extraction time: {end_time - start_time:.4f} seconds")
    print(f"Max event loop blocked for: {max_delay:.4f} seconds")

if __name__ == "__main__":
    asyncio.run(main())
