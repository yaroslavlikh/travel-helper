from scripts.check_docs import validate_links


def test_repository_markdown_links_are_valid() -> None:
    assert validate_links() == []
