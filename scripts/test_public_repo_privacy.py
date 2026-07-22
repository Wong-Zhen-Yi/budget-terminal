"""Fail when the public repository contains personal data or live credentials."""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path, PurePosixPath


REPO_ROOT = Path(__file__).resolve().parents[1]

DISALLOWED_BASENAMES = {
    ".env",
    "budget_terminal_cards.json",
    "credentials.json",
    "legacy_user_data.json",
    "net_worth.json",
    "options_tracker.json",
    "portfolio.json",
    "portfolio_tracker.json",
    "portfolios.json",
    "secrets.json",
    "user_data.json",
}

DISALLOWED_FILE_PATTERNS = (
    re.compile(r"(?i)^(?:paper|virtual)_trading.*\.(?:db|json|sqlite\d*)$"),
    re.compile(r"(?i)^budgetterminal_backup_.*\.(?:json|zip)$"),
    re.compile(r"(?i).+\.(?:key|p12|pem|pfx)$"),
)

CONTENT_PATTERNS = (
    ("personal Windows home path", re.compile(r"(?i)\b[A-Z]:[\\/]Users[\\/][^\\/\r\n]+")),
    ("personal Unix home path", re.compile(r"(?i)(?:^|[\s'\"])/(?:home|Users)/[^/\s'\"]+")),
    ("email address", re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")),
    ("known personal identifier", re.compile(r"(?i)Wong[\s_-]*Zhen[\s_-]*Yi|wongzhenyibusiness")),
    ("private key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("GitHub token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,})\b")),
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("OpenAI-style secret key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
)

ALLOWED_EMAILS = {
    "maintainers@budget-terminal.invalid",
}

ALLOWED_PUBLIC_IDENTIFIERS = {
    "https://api.github.com/repos/Wong-Zhen-Yi/budget-terminal/",
    "https://github.com/Wong-Zhen-Yi/budget-terminal/",
}

GENERIC_COMMIT_NAME = "Budget Terminal Maintainers"
GENERIC_COMMIT_EMAIL = "maintainers@budget-terminal.invalid"


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout


def _tracked_files() -> list[str]:
    return [path for path in _git("ls-files").splitlines() if path]


def _scan_filename(path: str) -> list[str]:
    normalized = PurePosixPath(path)
    basename = normalized.name.lower()
    errors: list[str] = []
    if basename in DISALLOWED_BASENAMES:
        errors.append(f"tracked personal-data filename: {path}")
    if any(pattern.fullmatch(normalized.name) for pattern in DISALLOWED_FILE_PATTERNS):
        errors.append(f"tracked sensitive artifact: {path}")
    if any(part.lower() in {"backups", "exports", "logs", "screenshots"} for part in normalized.parts):
        errors.append(f"tracked runtime-output directory: {path}")
    return errors


def _scan_content(path: str) -> list[str]:
    file_path = REPO_ROOT / Path(path)
    try:
        content = file_path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return []

    errors: list[str] = []
    for label, pattern in CONTENT_PATTERNS:
        for match in pattern.finditer(content):
            value = match.group(0)
            if label == "email address" and value.lower() in ALLOWED_EMAILS:
                continue
            line = content.count("\n", 0, match.start()) + 1
            line_text = content.splitlines()[line - 1]
            if label == "known personal identifier":
                if path == "scripts/test_public_repo_privacy.py":
                    continue
                if any(allowed in line_text for allowed in ALLOWED_PUBLIC_IDENTIFIERS):
                    continue
            errors.append(f"{path}:{line}: {label}")
    return errors


def _scan_head_metadata() -> list[str]:
    try:
        metadata = _git("show", "-s", "--format=%an%n%ae%n%cn%n%ce", "HEAD").splitlines()
    except subprocess.CalledProcessError:
        return []
    expected = [GENERIC_COMMIT_NAME, GENERIC_COMMIT_EMAIL] * 2
    if metadata != expected:
        return ["HEAD commit must use the generic public-repository author and committer identity"]
    if _git("rev-list", "--count", "HEAD").strip() != "1":
        return ["public main must contain exactly one root commit"]
    return []


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--tree-only",
        action="store_true",
        help="Scan the staged/working tree without requiring final commit metadata.",
    )
    args = parser.parse_args()

    errors: list[str] = []
    for path in _tracked_files():
        errors.extend(_scan_filename(path))
        errors.extend(_scan_content(path))
    if not args.tree_only:
        errors.extend(_scan_head_metadata())

    if errors:
        print("Public repository privacy check failed:")
        for error in sorted(set(errors)):
            print(f"- {error}")
        return 1
    print("public repository privacy check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
