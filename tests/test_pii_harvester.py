import pytest
from src.plugins.pii_harvester import PIIHarvesterPlugin
from src.plugins.text_extractor import TEXT_EXTRACTOR_NAME


def test_pii_harvester_should_run():
    harvester = PIIHarvesterPlugin()

    # Should skip media
    assert not harvester.should_run(
        "/a.jpg", "image/jpeg", {"Router": {"category": "Image"}}
    )

    # Should skip text without enough content
    assert not harvester.should_run(
        "/a.txt", "text/plain", {TEXT_EXTRACTOR_NAME: {"text": "short"}}
    )

    # Should run on long text
    assert harvester.should_run(
        "/a.txt", "text/plain", {TEXT_EXTRACTOR_NAME: {"text": "a" * 100}}
    )


@pytest.mark.asyncio
async def test_pii_harvester_json_cleanup(monkeypatch):
    harvester = PIIHarvesterPlugin()

    class MockLLM:
        async def generate(self, prompt, **kwargs):
            return '```json\n{"names": ["John Doe"], "emails": [], "addresses": [], "secrets": []}\n```'

    monkeypatch.setattr(
        "src.plugins.pii_harvester.get_llm_provider", lambda **kwargs: MockLLM()
    )

    context = {TEXT_EXTRACTOR_NAME: {"text": "John Doe was here." * 10}}
    res = await harvester.analyze("/doc.txt", "text/plain", context)

    assert res["skipped"] is False
    assert res["method"] == "llm_json_expert"
    assert "John Doe" in res["pii"]["names"]
