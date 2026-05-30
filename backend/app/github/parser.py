from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class PullRequestRef:
    owner: str
    repo: str
    number: int


def parse_pr_url(pr_url: str) -> PullRequestRef:
    parsed = urlparse(pr_url.strip())
    if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() != "github.com":
        raise ValueError("Only GitHub pull request URLs are supported.")

    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) != 4 or parts[2] != "pull":
        raise ValueError("Expected URL format: https://github.com/{owner}/{repo}/pull/{number}")

    try:
        number = int(parts[3])
    except ValueError as exc:
        raise ValueError("Pull request number must be an integer.") from exc

    if number <= 0:
        raise ValueError("Pull request number must be positive.")

    return PullRequestRef(owner=parts[0], repo=parts[1], number=number)
