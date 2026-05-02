import pytest
from unittest.mock import MagicMock, patch
from src.llm.llama_cpp import LlamaCppProvider, ModelManager


@pytest.fixture
def mock_llama():
    with patch("src.llm.llama_cpp.Llama") as mock:
        # Mock the context params
        mock.return_value.context_params.n_ctx = 4096
        yield mock


@pytest.fixture
def mock_psutil():
    with patch("src.llm.llama_cpp.psutil") as mock:
        yield mock


def test_llama_cpp_provider_init(mock_llama):
    # Mock os.path.exists to return True so it doesn't try to download
    with patch("os.path.exists", return_value=True):
        provider = LlamaCppProvider(model_path="mock_model.gguf")
        assert provider.llm is not None
        mock_llama.assert_called_once()


@pytest.mark.asyncio
async def test_llama_cpp_provider_generate(mock_llama):
    with patch("os.path.exists", return_value=True):
        provider = LlamaCppProvider(model_path="mock_model.gguf")

        # Mock create_chat_completion
        mock_llama.return_value.create_chat_completion.return_value = {
            "choices": [{"message": {"content": "Hello world"}}]
        }

        response = await provider.generate("Hi")
        assert response == "Hello world"


def test_model_manager_get_provider(mock_llama):
    ModelManager._cache.clear()
    with patch("os.path.exists", return_value=True):
        provider = ModelManager.get_provider(model_path="mock_model.gguf")
        assert isinstance(provider, LlamaCppProvider)
        assert "mock_model.gguf" in ModelManager._cache


def test_model_manager_lru_eviction(mock_llama, mock_psutil):
    ModelManager._cache.clear()

    # Mock low memory
    mock_psutil.virtual_memory.return_value.available = 1 * 1024**3  # 1GB

    with patch("os.path.exists", return_value=True):
        # Load two models
        _m1 = ModelManager.get_provider(model_path="model1.gguf")
        _m2 = ModelManager.get_provider(model_path="model2.gguf")

        # Now get a third model, it should trigger eviction if memory is low
        # Actually _ensure_memory is called BEFORE loading the new one
        # So when loading m2, m1 might be evicted if memory is low

        ModelManager._cache.clear()
        ModelManager._cache["model1.gguf"] = MagicMock()

        ModelManager._ensure_memory()
        assert "model1.gguf" not in ModelManager._cache
