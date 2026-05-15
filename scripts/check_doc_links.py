#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from pathlib import Path


LINK_RE = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
SKIP_PREFIXES = ("http://", "https://", "mailto:", "#")


def should_skip(target: str) -> bool:
    t = target.strip()
    if not t:
        return True
    return t.startswith(SKIP_PREFIXES)


def clean_target(target: str) -> str:
    t = target.strip()
    if "#" in t:
        t = t.split("#", 1)[0]
    return t.strip()


def iter_markdown_files(roots: list[Path]) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        if root.is_file() and root.suffix.lower() == ".md":
            files.append(root)
            continue
        if root.is_dir():
            files.extend(sorted(root.rglob("*.md")))
    return sorted(set(files))


def check_file(md_path: Path) -> list[str]:
    errors: list[str] = []
    text = md_path.read_text(encoding="utf-8")
    for idx, line in enumerate(text.splitlines(), start=1):
        for m in LINK_RE.finditer(line):
            raw = m.group(1).strip()
            if should_skip(raw):
                continue
            cleaned = clean_target(raw)
            if not cleaned:
                continue
            if cleaned.startswith("/"):
                target = Path(cleaned)
            else:
                target = (md_path.parent / cleaned).resolve()
            if not target.exists():
                errors.append(f"{md_path}:{idx} -> missing: {raw}")
    return errors


def main(argv: list[str]) -> int:
    roots = [Path(p).resolve() for p in argv] if argv else [Path.cwd()]
    md_files = iter_markdown_files(roots)
    if not md_files:
        print("No markdown files found.")
        return 0

    all_errors: list[str] = []
    for md in md_files:
        all_errors.extend(check_file(md))

    if all_errors:
        print("Broken markdown links found:")
        for err in all_errors:
            print(f"- {err}")
        return 1

    print(f"OK: checked {len(md_files)} markdown files, no broken local links.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
