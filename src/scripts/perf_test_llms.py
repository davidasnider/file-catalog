import argparse
import asyncio
import os
import time
import psutil
from pathlib import Path

# To run this script, use: python -m src.scripts.perf_test_llms

from src.core.config import config
from src.llm.factory import get_llm_provider
from src.plugins.text_extractor import TextExtractorPlugin


def get_memory_usage():
    """Returns current memory usage of the process in MB."""
    process = psutil.Process(os.getpid())
    return process.memory_info().rss / (1024 * 1024)


async def run_benchmark(root_dir: Path):
    sample_files = []

    if not root_dir.exists():
        print(f"Error: {root_dir} does not exist.")
        return

    # Find a few sample text/markdown/python files
    for path in root_dir.rglob("*"):
        if path.is_file() and path.suffix in [".txt", ".md", ".py"]:
            sample_files.append(path)
            if len(sample_files) >= 5:
                break

    if not sample_files:
        print(f"No text files found in {root_dir}")
        return

    print(f"Found {len(sample_files)} sample files for testing.")

    # Extract text to use as prompts
    extractor = TextExtractorPlugin()
    prompts = []
    for file_path in sample_files:
        # Simplistic mime type guess for the plugin
        mime = (
            "text/plain"
            if file_path.suffix == ".txt"
            else "text/x-python"
            if file_path.suffix == ".py"
            else "text/plain"
        )

        try:
            res = await extractor.analyze(str(file_path), mime, {})
            text = res.get("text", "")
            if len(text) > 2000:
                text = text[:2000]  # Cap prompt size for realistic summary test

            prompt = f"Summarize the following text:\n\n{text}"
            prompts.append(prompt)
        except Exception as e:
            print(f"Failed to extract {file_path}: {e}")

    if not prompts:
        print("Failed to generate any prompts.")
        return

    results = []

    # Configure Providers to Test (Defaults to current config)
    providers_to_test = [
        {"name": config.llm_provider, "model_path": config.llm_model_path},
        {"name": config.vision_provider, "model_path": config.vision_model_path},
    ]

    for p in providers_to_test:
        provider_name = p["name"]
        model_path = p["model_path"]

        print("\n=============================================")
        print(f"Testing Provider: {provider_name.upper()}")
        print(f"Model: {model_path}")
        print("=============================================")

        config.llm_provider = provider_name
        config.llm_model_path = model_path

        # Measure Load Time and Mem
        mem_before = get_memory_usage()
        t0 = time.time()

        provider = get_llm_provider()

        t1 = time.time()
        mem_after = get_memory_usage()

        load_time = t1 - t0
        peak_mem_load = mem_after - mem_before
        print(f"  Load Time: {load_time:.2f} s")
        print(f"  Mem Used by Load: {peak_mem_load:.2f} MB")

        if isinstance(provider, str) or provider is None:
            print(f"  Failed to initialize {provider_name}: {provider}")
            continue

        total_inference_time = 0
        total_tokens_generated = 0

        for i, prompt in enumerate(prompts):
            print(f"\n  Running prompt {i+1}/{len(prompts)} ({len(prompt)} chars)...")

            t_inf_start = time.time()
            try:
                # 256 max tokens matching our summarizer chunk size
                response = await provider.generate(
                    prompt, max_tokens=256, temperature=0.7
                )
                t_inf_end = time.time()

                duration = t_inf_end - t_inf_start
                # Simple approximation: 1 token ~ 4 chars for output
                approx_tokens = len(response) / 4.0
                tps = approx_tokens / duration

                print(
                    f"    Response length: {len(response)} chars (~{int(approx_tokens)} tokens)"
                )
                print(f"    Inference time: {duration:.2f} s")
                print(f"    Speed: {tps:.2f} tokens/s (approx)")

                total_inference_time += duration
                total_tokens_generated += approx_tokens

            except Exception as e:
                print(f"    Inference failed: {e}")

        # Try to cleanup provider to prep for next
        if hasattr(provider, "close"):
            provider.close()
        elif hasattr(provider, "model"):
            del provider.model
            if hasattr(provider, "tokenizer"):
                del provider.tokenizer

        import gc

        gc.collect()

        avg_tps = (
            total_tokens_generated / total_inference_time
            if total_inference_time > 0
            else 0
        )

        results.append(
            {
                "provider": provider_name,
                "avg_tps": avg_tps,
                "load_time": load_time,
                "total_time": total_inference_time,
            }
        )

    print("\n\n=============================================")
    print("FINAL BENCHMARK RESULTS")
    print("=============================================")
    for r in results:
        print(f"{r['provider'].upper()}:")
        print(f"  Load Time:     {r['load_time']:.2f} s")
        print(f"  Total Inf Time:{r['total_time']:.2f} s")
        print(f"  Avg Speed:     {r['avg_tps']:.2f} tokens/s (approx estimated)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Performance benchmark for LLMs.")
    parser.add_argument(
        "--dir",
        type=Path,
        default=Path.cwd(),
        help="Root directory to search for sample text files.",
    )
    args = parser.parse_args()
    asyncio.run(run_benchmark(args.dir))
