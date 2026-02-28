import os
from typing import Dict, Type, Any, List
from abc import ABC, abstractmethod

# Global registry dict to hold all registered analyzers
ANALYZER_REGISTRY: Dict[str, Type["AnalyzerBase"]] = {}


class AnalyzerBase(ABC):
    """
    Base class for all file analyzers.
    Every plugin must inherit from this class and implement the `analyze` method.
    """

    def __init__(self, **kwargs: Any):
        self.config = kwargs

    @abstractmethod
    async def analyze(
        self, file_path: str, mime_type: str, context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Perform analysis on the given file.

        Args:
            file_path: The absolute path to the file.
            mime_type: The detected MIME type of the file.
            context: A dictionary containing results from previous analyzers and global config.

        Returns:
            Dict containing the analysis results.
        """
        pass


def register_analyzer(name: str, depends_on: List[str] = None, version: str = "1.0"):
    """
    Decorator to register an analyzer class in the global registry.

    Args:
        name: A unique string identifier for this analyzer.
        depends_on: A list of names of other analyzers this depends on.
        version: The version string for this plugin logic (e.g "1.0").
    """

    def decorator(cls: Type[AnalyzerBase]):
        if not issubclass(cls, AnalyzerBase):
            raise TypeError(
                f"Registered class {cls.__name__} must inherit from AnalyzerBase"
            )

        cls._analyzer_name = name
        cls._depends_on = depends_on or []
        cls._analyzer_version = version
        ANALYZER_REGISTRY[name] = cls
        return cls

    return decorator


def get_ordered_analyzers() -> List[tuple]:
    """
    Returns a list of (name, class) tuples sorted topologically
    based on their depends_on definitions.
    """
    ordered = []
    visited = set()
    visiting = set()

    def visit(name: str):
        if name in visited:
            return
        if name in visiting:
            raise ValueError(f"Circular dependency detected involving {name}")
        visiting.add(name)

        cls = ANALYZER_REGISTRY.get(name)
        if cls:
            for dep in getattr(cls, "_depends_on", []):
                if dep in ANALYZER_REGISTRY:
                    visit(dep)

        visiting.remove(name)
        visited.add(name)
        if cls:
            ordered.append((name, cls))

    for name in sorted(ANALYZER_REGISTRY.keys()):
        visit(name)

    return ordered


def load_plugins(plugin_dir: str):
    """
    Dynamically discover and import all Python files in the given directory.
    This triggers the @register_analyzer decorators in those files.

    Args:
        plugin_dir: The directory containing plugin modules.
    """
    if not os.path.exists(plugin_dir):
        return

    for filename in os.listdir(plugin_dir):
        if filename.endswith(".py") and not filename.startswith("__"):
            module_name = filename[:-3]
            # Assuming plugin_dir is relative to the project root, or we need to construct the full module path
            # For a standard install, assuming src.plugins is the package
            # A more robust approach might be needed depending on package structure
            # if we just want to import it to trigger decorators, we can dynamically load it from path

            import importlib.util

            module_path = os.path.join(plugin_dir, filename)
            spec = importlib.util.spec_from_file_location(
                f"plugins.{module_name}", module_path
            )
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
