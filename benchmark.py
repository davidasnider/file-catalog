import asyncio
import time
import os
from src.plugins.text_extractor import TextExtractorPlugin

async def background_task(delays):
    while True:
        start = time.perf_counter()
        await asyncio.sleep(0.01)
        end = time.perf_counter()
        delays.append(end - start - 0.01)

async def main():
    file_path = "large_text.txt"
    if not os.path.exists(file_path):
        print("Creating large text file...")
        with open(file_path, "w") as f:
            f.write("This is a large text file. " * 5000000)

    plugin = TextExtractorPlugin()

    print("Running TextExtractorPlugin.analyze...")
    delays = []
    bg_task = asyncio.create_task(background_task(delays))

    # Let the background task run a bit
    await asyncio.sleep(0.05)

    start_time = time.perf_counter()
    res = await plugin.analyze(file_path, "text/plain", {})
    end_time = time.perf_counter()

    bg_task.cancel()

    max_delay = max(delays) if delays else 0
    print(f"Extraction time: {end_time - start_time:.4f} seconds")
    print(f"Max event loop delay: {max_delay:.4f} seconds")
    print(f"Extracted length: {len(res['text'])}")

if __name__ == "__main__":
    asyncio.run(main())
