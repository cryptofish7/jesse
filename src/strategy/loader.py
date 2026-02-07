"""Strategy discovery and loading — scan directories for Strategy subclasses."""

from __future__ import annotations

import importlib
import importlib.util
import inspect
import logging
import sys
from pathlib import Path

from src.strategy.base import Strategy

logger = logging.getLogger(__name__)

# Directories to scan for user strategies (relative to project root)
_STRATEGY_DIRS = [
    Path("strategies"),
    Path("src/strategy/examples"),
]


def discover_strategies() -> dict[str, type[Strategy]]:
    """Scan strategy directories and return a mapping of name -> class.

    Scans both ``strategies/`` (user strategies) and
    ``src/strategy/examples/`` (built-in examples). Each ``.py`` file is
    imported and inspected for concrete ``Strategy`` subclasses.

    Returns:
        Dict mapping class name (e.g., ``"MACrossover"``) to the class object.
    """
    found: dict[str, type[Strategy]] = {}

    for directory in _STRATEGY_DIRS:
        if not directory.exists():
            continue

        for py_file in sorted(directory.glob("*.py")):
            if py_file.name.startswith("_"):
                continue

            classes = _import_strategies_from_file(py_file)
            for cls in classes:
                if cls.__name__ in found:
                    logger.warning(
                        "Duplicate strategy name '%s' — %s overrides %s",
                        cls.__name__,
                        py_file,
                        found[cls.__name__],
                    )
                found[cls.__name__] = cls

    return found


def load_strategy(name: str) -> Strategy:
    """Load and instantiate a strategy by class name.

    Discovers all available strategies and looks up the given name.
    Raises ``ValueError`` if the strategy is not found.

    Args:
        name: The class name of the strategy (e.g., ``"MACrossover"``).

    Returns:
        An instantiated Strategy object.
    """
    strategies = discover_strategies()

    if name not in strategies:
        available = sorted(strategies.keys())
        available_str = ", ".join(available) if available else "(none found)"
        raise ValueError(f"Strategy '{name}' not found. Available strategies: {available_str}")

    cls = strategies[name]
    logger.info("Loading strategy: %s", name)
    return cls()


def _import_strategies_from_file(file_path: Path) -> list[type[Strategy]]:
    """Import a Python file and return all concrete Strategy subclasses found in it.

    Uses importlib to dynamically import the module, then inspects its
    members for classes that are subclasses of Strategy but not Strategy
    itself, and are not abstract.
    """
    module_name = f"_jesse_strategy_{file_path.stem}"

    try:
        spec = importlib.util.spec_from_file_location(module_name, file_path)
        if spec is None or spec.loader is None:
            logger.debug("Could not create module spec for %s", file_path)
            return []

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)  # type: ignore[union-attr]

    except Exception:
        logger.warning("Failed to import strategy file %s", file_path, exc_info=True)
        return []

    classes: list[type[Strategy]] = []
    for _name, obj in inspect.getmembers(module, inspect.isclass):
        if issubclass(obj, Strategy) and obj is not Strategy and not inspect.isabstract(obj):
            classes.append(obj)

    if classes:
        logger.debug(
            "Found %d strategy class(es) in %s: %s",
            len(classes),
            file_path,
            [c.__name__ for c in classes],
        )

    return classes
