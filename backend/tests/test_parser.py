import pytest

from app.github.parser import parse_pr_url


def test_parse_valid_github_pr_url():
    ref = parse_pr_url("https://github.com/openai/codex/pull/123")
    assert ref.owner == "openai"
    assert ref.repo == "codex"
    assert ref.number == 123


@pytest.mark.parametrize(
    "url",
    [
        "https://gitlab.com/openai/codex/pull/123",
        "https://github.com/openai/codex/issues/123",
        "https://github.com/openai/codex/pull/nope",
    ],
)
def test_parse_rejects_invalid_pr_urls(url):
    with pytest.raises(ValueError):
        parse_pr_url(url)
