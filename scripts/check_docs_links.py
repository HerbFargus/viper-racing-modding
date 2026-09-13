"""Every relative link in the docs resolves to something that exists.

WHY THIS EXISTS. The documents cross-reference each other heavily -- the asset
tree calls itself "the companion to file-formats", the workflow comparison sends
you to the modding history for who wrote what -- and those links are relative
paths. Moving the files into reference/, history/ and archive/ broke all sixteen
of them at once, and a broken relative link says nothing: it renders as ordinary
link text and only fails when a reader clicks it, by which time nobody
remembers the reorganisation.

Anchors are checked too, because a heading that gets reworded silently
invalidates every deep link into it, and four of the links here point at
specific sections rather than whole files.

Skips http(s) links: this is about the repo being internally consistent, not
about the rest of the internet still being up.

    python scripts/check_docs_links.py
"""
from __future__ import annotations

import re
import sys
import unicodedata
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*$", re.M)


def slug(text: str) -> str:
    """GitHub's heading -> anchor rule, near enough for our own headings.

    Lowercase, strip anything that is not a word character, space or hyphen,
    then spaces to hyphens. Emoji and the tick marks these headings use
    (`## 2. The universal container ... CONFIRMED`) fall out under the same
    rule GitHub applies.
    """
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = "".join(c for c in unicodedata.normalize("NFKD", text)
                   if not unicodedata.combining(c))
    text = re.sub(r"[^\w\s-]", "", text.lower())
    # One hyphen per whitespace CHARACTER, not per run. "vrTrackMaker — the
    # driving model" drops the em-dash and leaves two spaces, which GitHub
    # turns into two hyphens; collapsing them reported a live anchor as dead.
    return re.sub(r"\s", "-", text.strip())


def anchors(path: Path) -> set[str]:
    if path.suffix.lower() != ".md":
        return set()
    body = path.read_text(encoding="utf-8", errors="replace")
    found: set[str] = set()
    counts: dict[str, int] = {}
    for _, text in HEADING.findall(body):
        base = slug(text)
        n = counts.get(base, 0)
        counts[base] = n + 1
        found.add(base if n == 0 else f"{base}-{n}")
    # Explicit <a name="..."> / id="..." anchors, which some of these use.
    found |= set(re.findall(r'<a\s+(?:name|id)="([^"]+)"', body))
    return found


def main() -> int:
    if not DOCS.is_dir():
        print(f"  no docs/ at {DOCS}")
        return 0
    files = sorted(p for p in DOCS.rglob("*.md"))
    files += [ROOT / "README.md"]
    bad: list[str] = []
    checked = 0

    for f in files:
        if not f.is_file():
            continue
        body = f.read_text(encoding="utf-8", errors="replace")
        for raw in LINK.findall(body):
            if raw.startswith(("http://", "https://", "mailto:")):
                continue
            target, _, anchor = raw.partition("#")
            target = unquote(target)
            here = f.relative_to(ROOT).as_posix()
            checked += 1
            if not target:                      # a link within this same file
                dest = f
            else:
                dest = (f.parent / target).resolve()
                if not dest.exists():
                    bad.append(f"{here}: no such target: {raw}")
                    continue
            if anchor and dest.is_file():
                have = anchors(dest)
                if have and unquote(anchor).lower() not in have:
                    bad.append(f"{here}: #{anchor} is not a heading in "
                               f"{dest.relative_to(ROOT).as_posix()}")

    print(f"  {checked} relative link(s) across {len(files)} file(s)")
    for b in bad:
        print(f"  BROKEN  {b}")
    print(f"\n{checked - len(bad)}/{checked} resolve")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
