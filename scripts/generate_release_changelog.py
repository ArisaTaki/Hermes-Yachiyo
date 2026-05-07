#!/usr/bin/env python3
"""Generate release changelog data from git commits."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any


CATEGORY_ORDER = [
    "新增/改进",
    "修复",
    "工程/发布",
    "文档",
    "测试",
    "重构/优化",
    "其他",
]

CATEGORY_BY_KIND = {
    "add": "新增/改进",
    "feat": "新增/改进",
    "feature": "新增/改进",
    "fix": "修复",
    "hotfix": "修复",
    "bugfix": "修复",
    "ci": "工程/发布",
    "build": "工程/发布",
    "chore": "工程/发布",
    "release": "工程/发布",
    "docs": "文档",
    "doc": "文档",
    "test": "测试",
    "tests": "测试",
    "refactor": "重构/优化",
    "perf": "重构/优化",
    "style": "重构/优化",
}


def git(*args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", *args],
        check=check,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return result.stdout.strip()


def pick_previous_tag(channel: str, current_tag: str) -> str | None:
    pattern = f"{channel}-v*"
    tags = git("tag", "--merged", "HEAD", "--list", pattern, "--sort=-creatordate", check=False)
    for tag in tags.splitlines():
        candidate = tag.strip()
        if candidate and candidate != current_tag:
            return candidate
    return None


def commit_url(repository: str, commit: str) -> str | None:
    if not repository:
        return None
    return f"https://github.com/{repository}/commit/{commit}"


def compare_url(repository: str, previous_tag: str | None, current_tag: str) -> str | None:
    if not repository or not previous_tag:
        return None
    return f"https://github.com/{repository}/compare/{previous_tag}...{current_tag}"


def commit_category(subject: str) -> str:
    match = re.match(r"^([A-Za-z]+)(?:\([^)]+\))?[：:]", subject.strip())
    if not match:
        return "其他"
    return CATEGORY_BY_KIND.get(match.group(1).lower(), "其他")


def read_commits(previous_tag: str | None, limit: int, repository: str) -> list[dict[str, Any]]:
    range_ref = f"{previous_tag}..HEAD" if previous_tag else "HEAD"
    args = [
        "log",
        "--no-merges",
        f"--max-count={limit}",
        "--format=%H%x1f%h%x1f%an%x1f%aI%x1f%s%x1e",
        range_ref,
    ]
    output = git(*args, check=False)
    if not output:
        output = git(
            "log",
            f"--max-count={limit}",
            "--format=%H%x1f%h%x1f%an%x1f%aI%x1f%s%x1e",
            range_ref,
            check=False,
        )
    commits: list[dict[str, Any]] = []
    for record in output.split("\x1e"):
        record = record.strip()
        if not record:
            continue
        parts = record.split("\x1f")
        if len(parts) < 5:
            continue
        commit, short_sha, author, authored_at, subject = parts[:5]
        category = commit_category(subject)
        commits.append(
            {
                "commit": commit,
                "short_commit": short_sha,
                "author": author,
                "authored_at": authored_at,
                "subject": subject,
                "category": category,
                "url": commit_url(repository, commit),
            }
        )
    return commits


def build_sections(commits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {category: [] for category in CATEGORY_ORDER}
    for commit in commits:
        grouped.setdefault(commit["category"], []).append(
            {
                "commit": commit["commit"],
                "short_commit": commit["short_commit"],
                "subject": commit["subject"],
                "url": commit["url"],
            }
        )
    return [
        {"title": category, "items": items}
        for category in CATEGORY_ORDER
        if (items := grouped.get(category))
    ]


def write_markdown(path: Path, payload: dict[str, Any]) -> None:
    lines = ["## 更新日志", ""]
    previous_tag = payload.get("previous_tag")
    if previous_tag:
        lines.append(f"- 基线：`{previous_tag}`")
    else:
        lines.append("- 基线：当前渠道首次可用 release")
    if payload.get("compare_url"):
        lines.append(f"- 提交对比：{payload['compare_url']}")
    lines.append("")

    sections = payload.get("sections") or []
    if not sections:
        lines.extend(["暂无可展示的 commit 变更。", ""])
    for section in sections:
        lines.extend([f"### {section['title']}", ""])
        for item in section.get("items", []):
            lines.append(f"- `{item['short_commit']}` {item['subject']}")
        lines.append("")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channel", required=True, help="Release channel prefix, e.g. stable or experimental")
    parser.add_argument("--tag", required=True, help="Current release tag")
    parser.add_argument("--repository", default="", help="GitHub repository, e.g. owner/repo")
    parser.add_argument("--limit", type=int, default=30, help="Maximum commit count")
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-markdown", required=True)
    args = parser.parse_args()

    previous_tag = pick_previous_tag(args.channel, args.tag)
    previous_commit = git("rev-list", "-n", "1", previous_tag, check=False) if previous_tag else ""
    commits = read_commits(previous_tag, max(1, args.limit), args.repository)
    payload = {
        "generated_from": "git",
        "previous_tag": previous_tag,
        "previous_commit": previous_commit or None,
        "current_tag": args.tag,
        "compare_url": compare_url(args.repository, previous_tag, args.tag),
        "commit_count": len(commits),
        "commits": commits,
        "sections": build_sections(commits),
        "summary": [commit["subject"] for commit in commits[:8]],
    }

    output_json = Path(args.output_json)
    output_markdown = Path(args.output_markdown)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_markdown.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_markdown(output_markdown, payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
