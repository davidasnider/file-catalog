import pytest
from src.core.plugin_registry import AnalyzerBase, register_analyzer, ANALYZER_REGISTRY


@pytest.fixture(autouse=True)
def reset_registry():
    """Clear the global registry before and after tests."""
    ANALYZER_REGISTRY.clear()
    yield
    ANALYZER_REGISTRY.clear()


def test_register_valid_analyzer():
    @register_analyzer(name="TestAnalyzer", depends_on=["extractor"])
    class TestAnalyzer(AnalyzerBase):
        async def analyze(self, file_path, mime_type, context):
            return {"status": "ok"}

    assert "TestAnalyzer" in ANALYZER_REGISTRY
    assert issubclass(ANALYZER_REGISTRY["TestAnalyzer"], AnalyzerBase)
    assert ANALYZER_REGISTRY["TestAnalyzer"]._depends_on == ["extractor"]


def test_register_invalid_analyzer():
    # Should raise TypeError if it doesn't inherit from AnalyzerBase
    with pytest.raises(TypeError):

        @register_analyzer(name="BadAnalyzer")
        class BadAnalyzer:
            pass

    assert "BadAnalyzer" not in ANALYZER_REGISTRY
