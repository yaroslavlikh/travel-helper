import ast
from pathlib import Path

FORBIDDEN_IMPORTS = {
    "openai",
    "anthropic",
    "langchain",
    "langgraph",
    "transformers",
    "sentence_transformers",
    "litellm",
}
PRICING_ROOT = Path(__file__).resolve().parents[2] / "app" / "pricing"


def test_pricing_package_has_no_ai_imports() -> None:
    violations: list[str] = []
    for path in sorted(PRICING_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.append(node.module)
            for module in modules:
                root = module.split(".", 1)[0]
                if root in FORBIDDEN_IMPORTS:
                    violations.append(f"{path.relative_to(PRICING_ROOT)}: {module}")

    assert violations == []
