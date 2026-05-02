import pytest
from src.plugins.deep_summarizer import DeepSummarizerPlugin
from src.core.analyzer_names import TEXT_EXTRACTOR_NAME


@pytest.mark.asyncio
async def test_deep_summarizer_map_reduce(monkeypatch):
    summarizer = DeepSummarizerPlugin()

    class MockLLM:
        def __init__(self):
            self.call_count = 0

        async def generate(self, prompt, **kwargs):
            self.call_count += 1
            if "TEXT CHUNK" in prompt:
                if self.call_count == 2:
                    raise Exception("Simulated map error")
                return f"Summary of chunk {self.call_count}"
            elif "FINAL EXTENSIVE SUMMARY" in prompt:
                return "Final Synthesis"
            return ""

    mock_llm = MockLLM()
    monkeypatch.setattr(
        "src.plugins.deep_summarizer.get_llm_provider", lambda **kwargs: mock_llm
    )

    # 3 chunks worth of text
    large_text = "A" * 40000
    context = {TEXT_EXTRACTOR_NAME: {"text": large_text}}

    res = await summarizer.analyze("/large.txt", "text/plain", context)

    assert res["skipped"] is False
    # chunks_processed should be 2 because 1 failed
    assert res["chunks_processed"] == 2
    assert res["extensive_summary"] == "Final Synthesis"
