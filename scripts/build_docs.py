"""Render docs/ into a static site, with the contents page at the root.

WHY THIS EXISTS. The docs used to be published by committing hand-maintained
HTML alongside the Markdown. They drifted, badly and silently: the published
file-format reference held 64% of the words in its source and the modding
history 47%, because the Markdown got 33 commits and its render got 5. Nobody
was going to keep doing that by hand, and nobody noticed they had stopped.

So HTML is a build artifact now, generated here and never committed -- the same
rule this repo already applied to other generated files.

ANCHORS MUST MATCH GITHUB'S. The documents deep-link into each other's sections
(`file-formats.md#how-a-track-is-actually-built`) and those same files are also
read on github.com. If the renderer slugged headings its own way, every deep
link would work in one place and 404 in the other. `slug()` here implements
GitHub's rule and check_docs_links.py imports it, so the checker validates
exactly what the builder will produce rather than a second opinion about it.

    python scripts/build_docs.py [-o site]
"""
from __future__ import annotations

import argparse
import html
import re
import shutil
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"

REPO = "https://github.com/HerbFargus/viper-racing-modding"
GALLERY = "https://herbfargus.github.io/viper-racing-gallery/"

# The three groups, in reading order, with what each is FOR. The blurbs are the
# whole point of a contents page: a list of five filenames tells a visitor
# nothing they could not get from the repo listing.
GROUPS = [
    ("reference", "The reference", "What the game <em>is</em> — the reverse "
     "engineering, on three axes. Headings carry their evidence: "
     "<b>CONFIRMED</b> where something was read out of the binary or the file, "
     "<b>MEASURED</b> where it was observed in game."),
    ("history", "The history", "What people <em>did</em> with it — the tools "
     "the community built between roughly 1999 and 2010, who wrote them, and "
     "how that work compares to doing the same jobs now."),
    ("archive", "The archive", "Rescued primary sources, not our writing: "
     "community material from sites that no longer exist, preserved as it was."),
]

# Per-document blurbs, keyed by path under docs/. Kept here rather than parsed
# out of each file's first paragraph, which is written for a reader who has
# already opened it and reads badly in a list.
TITLE = {
    "reference/file-formats.md": "File formats",
    "reference/asset-tree.md": "Asset tree",
    "reference/runtime.md": "Runtime behaviour",
    "history/modding-history.md": "Modding history",
    "history/workflow-comparison.md": "Workflow comparison",
    "archive/wrxds-car-tutorial/README.md": "Wrxds’s car tutorial",
}

BLURB = {
    "reference/file-formats.md": (
        "The <b>bytes</b>", "The layout of every resource type the game ships — "
        "the 0SER container, the package layer, and a per-type catalogue down to "
        "individual struct fields."),
    "reference/asset-tree.md": (
        "The <b>structure</b>", "What is actually inside a car or a track, and "
        "where every texture and model it references resolves at runtime — "
        "including the shared <code>.res</code> bundles an asset reaches into."),
    "reference/runtime.md": (
        "The <b>behaviour</b>", "What the game does when it runs: which detail "
        "level you see per camera view, how the AI reacts to other cars, the "
        "engine's command-line parameters, and what the exit panic is reporting."),
    "history/modding-history.md": (
        "Who built what", "The people, the one-off utilities they wrote, and how "
        "the formats came to be understood — most of it from tools that survive "
        "only as a binary, on sites that are gone."),
    "history/workflow-comparison.md": (
        "Then and now", "The old toolchain against <code>vrmod</code>, job by "
        "job — building a track, converting a car — and what still needs the "
        "old tools."),
    "archive/wrxds-car-tutorial/README.md": (
        "Community tutorial", "Building a car for Viper Racing, step by step, "
        "with its original screenshots — plus where it came from and when it "
        "was captured."),
}

CSS = """
:root{
  --bg:#fbfaf7; --panel:#ffffff; --edge:#e3ded3; --fg:#23201b; --dim:#6d675d;
  --acc:#8a3a2c; --acc-soft:#f3e7e3; --code-bg:#f4f1ea; --ok:#3f6b4a;
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --bg:#17171a; --panel:#1e1e22; --edge:#32323a; --fg:#e8e5df; --dim:#9c968b;
    --acc:#e0947a; --acc-soft:#2e2320; --code-bg:#232329; --ok:#7fb08c;
  }
}
:root[data-theme="dark"]{
  --bg:#17171a; --panel:#1e1e22; --edge:#32323a; --fg:#e8e5df; --dim:#9c968b;
  --acc:#e0947a; --acc-soft:#2e2320; --code-bg:#232329; --ok:#7fb08c;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
     font:16px/1.65 "Iowan Old Style","Palatino Linotype",Palatino,Georgia,serif;
     -webkit-font-smoothing:antialiased}
a{color:var(--acc)}
header.top{border-bottom:1px solid var(--edge);background:var(--panel)}
header.top .in{max-width:64rem;margin:0 auto;padding:14px 24px;display:flex;
               gap:18px;align-items:baseline;flex-wrap:wrap}
header.top .name{font-weight:700;letter-spacing:-.01em}
header.top nav{margin-left:auto;display:flex;gap:16px;font-size:14px}
header.top nav a{color:var(--dim);text-decoration:none}
header.top nav a:hover{color:var(--acc)}
main{max-width:64rem;margin:0 auto;padding:34px 24px 80px}
h1{font-size:2.1rem;line-height:1.15;margin:.2em 0 .1em;text-wrap:balance}
.tagline{color:var(--dim);font-size:1.05rem;margin:0 0 2.4em}
.group{margin:0 0 3rem}
.group > h2{font-size:1.35rem;margin:0 0 .3em}
.group > p{color:var(--dim);margin:0 0 1.2em;max-width:60ch}
.cards{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(260px,1fr))}
.card{display:block;text-decoration:none;color:inherit;background:var(--panel);
      border:1px solid var(--edge);border-radius:10px;padding:16px 18px}
.card:hover{border-color:var(--acc)}
.card .kicker{font-size:12px;text-transform:uppercase;letter-spacing:.09em;
              color:var(--acc);font-weight:600;font-family:system-ui,sans-serif}
.card h3{margin:.35em 0 .3em;font-size:1.05rem}
.card p{margin:0;color:var(--dim);font-size:14.5px;line-height:1.5}
.card .meta{margin-top:.7em;font-size:12.5px;color:var(--dim);
            font-family:system-ui,sans-serif}
article{max-width:none}
article h1{margin-top:0}
article h2{margin:2.2em 0 .5em;padding-top:.3em;border-top:1px solid var(--edge);
           font-size:1.5rem}
article h3{margin:1.8em 0 .4em;font-size:1.2rem}
article h4{margin:1.5em 0 .3em;font-size:1.05rem}
article p,article li{max-width:70ch}
article img{max-width:100%}
code,pre{font-family:ui-monospace,"SF Mono",Menlo,Consolas,monospace;font-size:.88em}
code{background:var(--code-bg);padding:.12em .38em;border-radius:4px}
pre{background:var(--code-bg);border:1px solid var(--edge);border-radius:8px;
    padding:14px 16px;overflow-x:auto}
pre code{background:none;padding:0}
table{border-collapse:collapse;margin:1.2em 0;font-size:14.5px;
      font-family:system-ui,sans-serif;display:block;overflow-x:auto;
      max-width:100%}
th,td{border:1px solid var(--edge);padding:7px 11px;text-align:left;
      vertical-align:top}
th{background:var(--code-bg);font-weight:600}
blockquote{margin:1.2em 0;padding:.1em 1.1em;border-left:3px solid var(--acc);
           color:var(--dim)}
hr{border:0;border-top:1px solid var(--edge);margin:2.4em 0}
.layout{display:grid;gap:40px;grid-template-columns:1fr}
@media(min-width:1080px){
  .layout{grid-template-columns:minmax(0,1fr) 15rem}
  .toc{position:sticky;top:24px;align-self:start;max-height:calc(100vh - 48px);
       overflow-y:auto}
}
.toc{font-family:system-ui,sans-serif;font-size:13.5px;line-height:1.45}
.toc .h{font-size:11px;text-transform:uppercase;letter-spacing:.09em;
        color:var(--dim);font-weight:700;margin-bottom:.7em}
.toc ul{list-style:none;margin:0;padding:0}
.toc li{margin:.42em 0}
.toc li.l3{padding-left:.9em;font-size:12.8px}
.toc a{color:var(--dim);text-decoration:none}
.toc a:hover{color:var(--acc)}
.back{font-family:system-ui,sans-serif;font-size:13.5px;margin-bottom:1.4em}
.grade{font-family:system-ui,sans-serif;font-size:11px;font-weight:700;
       letter-spacing:.07em;color:var(--ok);border:1px solid currentColor;
       border-radius:99px;padding:1px 7px;vertical-align:.18em;
       margin-left:.5em;white-space:nowrap}
footer{max-width:64rem;margin:0 auto;padding:0 24px 60px;color:var(--dim);
       font-size:13px;font-family:system-ui,sans-serif}
"""


def slug(text: str) -> str:
    """GitHub's heading -> anchor rule.

    Lowercase, drop anything that is not a word character, space or hyphen,
    then ONE hyphen per whitespace character -- not per run. A heading with an
    em-dash ("vrTrackMaker — the driving model") loses the dash and keeps both
    surrounding spaces, so GitHub emits two hyphens. Collapsing them is what
    made the link checker report a live anchor as dead.
    """
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = "".join(c for c in unicodedata.normalize("NFKD", text)
                   if not unicodedata.combining(c))
    text = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"\s", "-", text.strip())


def page(title: str, body: str, *, depth: int, active: str = "") -> str:
    up = "../" * depth
    nav = [("Docs", f"{up}index.html"), ("Mods", GALLERY), ("Repo", REPO)]
    links = "".join(f'<a href="{h}">{html.escape(t)}</a>' for t, h in nav)
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{html.escape(title)}</title><style>{CSS}</style></head><body>'
            f'<header class="top"><div class="in">'
            f'<span class="name">Viper Racing modding</span>'
            f'<nav>{links}</nav></div></header>{body}'
            f'<footer>Generated from the Markdown in '
            f'<a href="{REPO}/tree/main/docs">docs/</a>. '
            f'{html.escape(active)}</footer></body></html>')


def render(md_path: Path) -> tuple[str, str, list[tuple[int, str, str]]]:
    """(title, html body, [(level, anchor, text)]) for one document."""
    import markdown as md

    text = md_path.read_text(encoding="utf-8")
    m = re.search(r"^#\s+(.*)$", text, re.M)
    title = m.group(1).strip() if m else md_path.stem

    # Collect headings from the SOURCE, so the contents list and the anchors
    # agree with GitHub rather than with the renderer's own slugifier.
    # EVERY level, not just the ones the contents list shows. Four links point
    # at #### headings ("vrTrackMaker -- the driving model, not the track"), and
    # anchoring only h2/h3 left those dead in the rendered site while working
    # fine on github.com -- the exact split this is supposed to prevent.
    heads: list[tuple[int, str, str]] = []
    seen: dict[str, int] = {}
    for hm in re.finditer(r"^(#{2,6})\s+(.*?)\s*$", text, re.M):
        level, raw = len(hm.group(1)), hm.group(2)
        base = slug(raw)
        n = seen.get(base, 0)
        seen[base] = n + 1
        heads.append((level, base if n == 0 else f"{base}-{n}", raw))

    body = md.markdown(text, extensions=["tables", "fenced_code", "attr_list",
                                         "sane_lists", "md_in_html"])

    # Anchors: replace the renderer's headings with ours, in document order.
    order = iter([h for h in heads])

    def anchor(match):
        tag, inner = match.group(1), match.group(2)
        if tag in ("h2", "h3", "h4", "h5", "h6"):
            try:
                _, a, _ = next(order)
            except StopIteration:
                return match.group(0)
            return f'<{tag} id="{a}">{inner}</{tag}>'
        return match.group(0)

    body = re.sub(r"<(h[1-6])>(.*?)</\1>", anchor, body, flags=re.S)

    # The evidence grades are the most useful thing in these headings and read
    # as noise inline; lift them out as a badge.
    body = re.sub(r"(✅|❌|⚠️?)\s*([A-Z][A-Z ]{2,})",
                  lambda m: f'<span class="grade">{html.escape(m.group(2).strip())}</span>',
                  body)

    # .md links point at the rendered pages once published.
    body = re.sub(r'href="([^"]+)\.md(#[^"]*)?"',
                  lambda m: f'href="{m.group(1)}.html{m.group(2) or ""}"', body)
    return title, body, heads


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("-o", "--out", type=Path, default=ROOT / "site")
    args = ap.parse_args()
    out = args.out
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    built: dict[str, tuple[str, int]] = {}
    for md_path in sorted(DOCS.rglob("*.md")):
        rel = md_path.relative_to(DOCS)
        title, body, heads = render(md_path)
        dest = out / rel.with_suffix(".html")
        dest.parent.mkdir(parents=True, exist_ok=True)
        toc = "".join(
            f'<li class="l{lvl}"><a href="#{a}">{html.escape(re.sub(r"[✅❌⚠️]", "", t).strip())}</a></li>'
            for lvl, a, t in heads if lvl <= 3)
        aside = (f'<aside class="toc"><div class="h">On this page</div>'
                 f'<ul>{toc}</ul></aside>') if len(heads) > 2 else ""
        depth = len(rel.parts) - 1
        inner = (f'<main><div class="layout"><article>'
                 f'<p class="back"><a href="{"../" * depth}index.html">'
                 f'&larr; All documentation</a></p>{body}</article>'
                 f'{aside}</div></main>')
        dest.write_text(page(title, inner, depth=depth), encoding="utf-8")
        built[rel.as_posix()] = (title, len(heads))
        print(f"  {rel.as_posix():42s} -> {dest.relative_to(out).as_posix():42s} "
              f"{len(heads):>3} sections")

    # Everything that is not Markdown (the archive's .htm pages, its images)
    # is copied verbatim: it is a preserved artifact, not something to restyle.
    copied = 0
    for src in sorted(DOCS.rglob("*")):
        if src.is_dir() or src.suffix.lower() == ".md":
            continue
        dest = out / src.relative_to(DOCS)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        copied += 1
    print(f"  {copied} archive file(s) copied verbatim")

    # ---- the contents page ------------------------------------------------
    sections = []
    for folder, heading, blurb in GROUPS:
        cards = []
        order = list(TITLE)
        for rel, (title, nheads) in sorted(
                built.items(),
                key=lambda kv: (order.index(kv[0]) if kv[0] in order else 99,
                                kv[0])):
            if not rel.startswith(folder + "/"):
                continue
            kicker, desc = BLURB.get(rel, ("", ""))
            words = len((DOCS / rel).read_text(encoding="utf-8").split())
            shown = TITLE.get(rel, title)
            meta = f"{words:,} words · {nheads} sections"
            steps = sorted({re.sub(r"[a-z]$", "", p.stem[5:])
                            for p in (DOCS / rel).parent.glob("step_*.htm")})
            if steps:
                meta = f"{len(steps)} steps · as published"
            cards.append(
                f'<a class="card" href="{rel[:-3]}.html">'
                f'{f"<div class=kicker>{kicker}</div>" if kicker else ""}'
                f'<h3>{html.escape(shown)}</h3><p>{desc}</p>'
                f'<div class="meta">{meta}</div></a>')
        if cards:
            sections.append(f'<section class="group"><h2>{heading}</h2>'
                            f'<p>{blurb}</p><div class="cards">'
                            + "".join(cards) + "</div></section>")

    index = (f'<main><h1>Viper Racing, documented</h1>'
             f'<p class="tagline">Everything learned about the file formats and '
             f'runtime of <i>Viper Racing</i> (MGI/Sierra, 1998) while building '
             f'<a href="{REPO}">vrmod</a> — plus the history of the people who '
             f'worked it out first.</p>' + "".join(sections) + "</main>")
    (out / "index.html").write_text(page("Viper Racing, documented", index,
                                         depth=0), encoding="utf-8")
    print(f"\n  wrote {out / 'index.html'} ({len(built)} documents)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
