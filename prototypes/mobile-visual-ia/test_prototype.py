#!/usr/bin/env python3
"""Real-browser checks for the #75 mobile visual / IA prototype.

What this proves: the three variants of one information architecture meet the
geometry, accessibility and hygiene floor that plan/32 asks of them, in a real
Chromium, over synthetic data. What it cannot prove: anything about iOS Safari,
Android Chrome, a real software keyboard, safe areas, IME, VoiceOver/TalkBack
or the production Vue console. Those are UAT items (plan/32/05).
"""

from __future__ import annotations

import argparse
import contextlib
import json
import re
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import Browser, Page, sync_playwright

HERE = Path(__file__).resolve().parent
VARIANTS = ["a", "b", "c"]
SIZES = [(360, 800), (390, 844), (430, 932), (844, 390)]
ZOOM_200 = (195, 422)  # 390x844 at 200% browser zoom
TOUCH = 44
DETAIL_SCENARIOS = [
    "terminal", "menu", "viewer", "viewer-locked", "posture", "shell",
    "reconnecting", "disconnected", "gap", "exited", "activity", "await",
    "events-gap", "unsupported", "files", "keyboard",
]
ALL_SCENARIOS = [
    "list", "list-empty", "create", *DETAIL_SCENARIOS, "load-error",
    "forbidden", "preview", "preview-denied",
]
# Internal scrollers that may legitimately hold content wider than the screen
# (terminal and code are never rewrapped; breadcrumbs scroll sideways).
INTERNAL_SCROLLERS = ".terminal, .code, .crumbs"


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, _format: str, *_args: object) -> None:
        return


@contextlib.contextmanager
def local_server(directory: Path):
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(directory)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


# ---------------------------------------------------------------- static checks

COLOUR = re.compile(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(")
NAMED = re.compile(r":\s*[^;{}]*\b(white|black|red|green|blue|gray|grey|orange|yellow|purple|pink)\b", re.I)


def strip_comments(text: str, kind: str) -> str:
    text = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)
    if kind == "js":
        text = re.sub(r"(^|\s)//[^\n]*", r"\1", text)
    if kind == "html":
        text = re.sub(r"<!--.*?-->", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)
    return text


def check_literal_colours() -> str:
    css = (HERE / "style.css").read_text(encoding="utf-8")
    start, end = css.index("/* @tokens:start */"), css.index("/* @tokens:end */")
    outside = {
        "style.css": strip_comments(css[:start] + css[end:], "css"),
        "app.js": strip_comments((HERE / "app.js").read_text(encoding="utf-8"), "js"),
        "index.html": strip_comments((HERE / "index.html").read_text(encoding="utf-8"), "html"),
    }
    hits = []
    for name, text in outside.items():
        for number, line in enumerate(text.splitlines(), 1):
            if COLOUR.search(line):
                hits.append(f"{name}:{number}: {line.strip()[:90]}")
            if name == "style.css" and NAMED.search(re.sub(r"var\([^)]*\)|--[a-z0-9-]+", "", line)):
                hits.append(f"{name}:{number} (named colour): {line.strip()[:90]}")
    expect(not hits, "literal colours outside the token block:\n" + "\n".join(hits))
    return "no literal colours outside the token block (css/js/html)"


def tokens() -> dict[str, str]:
    css = (HERE / "style.css").read_text(encoding="utf-8")
    block = css[css.index("/* @tokens:start */"): css.index("/* @tokens:end */")]
    return dict(re.findall(r"--([a-z0-9-]+):\s*(#[0-9a-fA-F]{6})\s*;", block))


def luminance(hex_colour: str) -> float:
    channels = [int(hex_colour[i: i + 2], 16) / 255 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(fg: str, bg: str) -> float:
    hi, lo = sorted([luminance(fg), luminance(bg)], reverse=True)
    return (hi + 0.05) / (lo + 0.05)


# Every foreground/background pair the prototype actually paints text with.
TEXT_PAIRS = [
    *[("text-primary", s) for s in ("surface-default", "surface-canvas", "surface-raised")],
    *[("text-secondary", s) for s in ("surface-default", "surface-canvas", "surface-raised")],
    ("accent-strong", "surface-default"), ("accent-strong", "surface-canvas"),
    ("accent-strong", "accent-subtle"), ("text-on-accent", "accent-strong"),
    ("danger-fg", "danger-bg"), ("status-error-fg", "surface-default"),
    *[(f"status-{t}-fg", f"status-{t}-bg") for t in ("success", "warning", "error", "info", "neutral")],
    *[(f"status-{t}-fg", "surface-default") for t in ("success", "warning", "info", "neutral")],
    ("terminal-foreground", "terminal-background"), ("terminal-input", "terminal-background"),
    ("text-on-terminal-dim", "terminal-background"),
    *[(f"ansi-{c}", "terminal-background") for c in ("black", "red", "green", "yellow", "blue", "magenta", "cyan", "bright-black")],
]
# Non-text: 3:1 (focus ring, control borders, disabled labels, the dim ANSI end).
NON_TEXT_PAIRS = [
    ("focus-ring", "surface-default"), ("focus-ring", "surface-canvas"), ("focus-ring", "surface-raised"),
    ("border-control", "surface-default"), ("border-control", "surface-canvas"), ("border-control", "surface-raised"),
    ("text-disabled", "surface-default"), ("text-disabled", "surface-raised"),
    ("ansi-white", "terminal-background"),
]


def check_contrast() -> tuple[str, list[dict]]:
    table = tokens()
    report, failures = [], []
    for pairs, floor in ((TEXT_PAIRS, 4.5), (NON_TEXT_PAIRS, 3.0)):
        for fg, bg in pairs:
            ratio = contrast(table[fg], table[bg])
            report.append({"fg": fg, "bg": bg, "fg_value": table[fg], "bg_value": table[bg], "ratio": round(ratio, 2), "floor": floor})
            if ratio < floor:
                failures.append(f"{fg} {table[fg]} on {bg} {table[bg]}: {ratio:.2f} < {floor}")
    expect(not failures, "contrast failures:\n" + "\n".join(failures))
    return f"{len(report)} token pairs meet contrast (text >= 4.5, non-text >= 3)", report


REAL_DATA = [
    (re.compile(r"/Users/|/home/(?!demo)|C:\\\\Users", re.I), "home directory"),
    (re.compile(r"\b[\w.+-]+@[\w-]+\.(com|net|org|io|dev|tw|ai)\b", re.I), "e-mail address"),
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "IPv4 address"),
    (re.compile(r"\b(sk-[A-Za-z0-9]{8,}|ghp_[A-Za-z0-9]{8,}|xox[bp]-|AKIA[0-9A-Z]{12})"), "credential shape"),
    (re.compile(r"BEGIN [A-Z ]*PRIVATE KEY"), "private key"),
    (re.compile(r"https?://(?!127\.0\.0\.1)[^\s\"')]+"), "external URL"),
]


def check_real_data() -> str:
    hits = []
    for name in ("index.html", "style.css", "app.js"):
        text = (HERE / name).read_text(encoding="utf-8")
        for pattern, label in REAL_DATA:
            for match in pattern.finditer(text):
                hits.append(f"{name}: {label}: {match.group(0)[:60]}")
    js = (HERE / "app.js").read_text(encoding="utf-8")
    names = re.findall(r'id: "(?:sess|node)-[^"]+", name: "([^"]+)"', js)
    expect(names and all(n.startswith("demo-") for n in names), f"fixture names must be demo-*: {names}")
    expect(not hits, "real-data markers found:\n" + "\n".join(hits))
    return "no real-data markers; every fixture name is demo-*"


# ---------------------------------------------------------------- browser checks

def load(page: Page, base: str, variant: str, scenario: str) -> None:
    page.goto(f"{base}?v={variant}&s={scenario}", wait_until="domcontentloaded")
    page.wait_for_selector("#app > *")


def undersized(page: Page) -> list[str]:
    return page.evaluate(
        """(min) => [...document.querySelectorAll('button, input, select, a[href], [role="tab"]')]
          .filter((el) => {
            const s = getComputedStyle(el); const r = el.getBoundingClientRect();
            if (s.display === 'none' || s.visibility === 'hidden' || r.width === 0 || r.height === 0) return false;
            if (r.bottom <= 0 || r.top >= innerHeight || r.right <= 0 || r.left >= innerWidth) return false;
            // A radio is operated through its 44px label.
            if (el.type === 'radio') { const l = el.closest('label').getBoundingClientRect(); return l.height + 0.5 < min; }
            return r.width + 0.5 < min || r.height + 0.5 < min;
          })
          .map((el) => `${el.tagName.toLowerCase()}[${(el.getAttribute('aria-label') || el.textContent || el.id).trim().slice(0, 20)}] ` +
                       `${Math.round(el.getBoundingClientRect().width)}x${Math.round(el.getBoundingClientRect().height)}`)""",
        TOUCH,
    )


def overflow(page: Page) -> list[str]:
    return page.evaluate(
        """(scrollers) => {
          const out = [];
          const root = document.documentElement;
          if (root.scrollWidth > root.clientWidth + 1) out.push(`document ${root.scrollWidth}>${root.clientWidth}`);
          for (const el of document.querySelectorAll('#app *')) {
            if (el.closest(scrollers) && !el.matches(scrollers)) continue;
            const s = getComputedStyle(el); if (s.display === 'none' || s.position === 'fixed') continue;
            const r = el.getBoundingClientRect();
            if (r.width === 0) continue;
            // Clipped by an ancestor that itself fits (an intentional ellipsis): not overflow.
            let clipped = false;
            for (let a = el.parentElement; a && a.id !== 'app'; a = a.parentElement) {
              const ov = getComputedStyle(a).overflowX;
              if (ov !== 'visible') { const ar = a.getBoundingClientRect(); clipped = ar.right <= innerWidth + 1 && ar.left >= -1; break; }
            }
            if (clipped) continue;
            if (r.right > innerWidth + 1 || r.left < -1) out.push(`${el.tagName}.${el.className} ${Math.round(r.left)}..${Math.round(r.right)}`);
          }
          return out.slice(0, 6);
        }""",
        INTERNAL_SCROLLERS,
    )


def geometry_suite(browser: Browser, base: str, passed) -> dict:
    counts = {"pages": 0}
    for width, height in [*SIZES, ZOOM_200]:
        context = browser.new_context(viewport={"width": width, "height": height}, is_mobile=True, has_touch=True)
        page = context.new_page()
        for variant in VARIANTS:
            for scenario in ALL_SCENARIOS:
                load(page, base, variant, scenario)
                label = f"{variant}/{scenario} @{width}x{height}"
                bad = overflow(page)
                expect(not bad, f"{label}: horizontal overflow {bad}")
                if (width, height) != ZOOM_200:
                    small = undersized(page)
                    expect(not small, f"{label}: touch targets under {TOUCH}px {small}")
                counts["pages"] += 1
        context.close()
    passed(f"no horizontal overflow at 360/390/430/844x390 and 200% zoom (195x422); 44px targets at every size ({counts['pages']} page loads)")
    return counts


def ia_invariants_suite(browser: Browser, base: str, passed) -> None:
    for width, height in ((390, 844), (844, 390)):
        context = browser.new_context(viewport={"width": width, "height": height}, is_mobile=True, has_touch=True)
        page = context.new_page()
        for variant in VARIANTS:
            for scenario in DETAIL_SCENARIOS:
                load(page, base, variant, scenario)
                label = f"{variant}/{scenario} @{width}x{height}"
                if scenario in ("menu",):
                    page.keyboard.press("Escape")
                # Which session, and the three separate facts, are always on screen.
                expect(page.locator(".sbar h1").is_visible(), f"{label}: session name hidden")
                line = page.locator(".state-line")
                expect(line.is_visible(), f"{label}: state line hidden")
                text = line.inner_text()
                expect(page.locator(".state-line .cell").count() == 3, f"{label}: state line must keep 3 separate cells")
                # Files and the native terminal are one tap away from every detail view.
                expect(page.get_by_role("tab", name="檔案").is_visible(), f"{label}: files entry not visible")
                expect(page.get_by_role("tab", name="終端機").is_visible(), f"{label}: native terminal not one tap away")
                if scenario in ("posture", "shell"):
                    posture = page.locator(".posture-line")
                    expect(posture.is_visible(), f"{label}: node posture hidden")
                    expect("可提權" in posture.inner_text() and "沙箱停用" in posture.inner_text(), f"{label}: posture words missing")
                if scenario == "viewer":
                    expect(page.get_by_role("button", name="取得控制權").is_visible(), f"{label}: takeover not offered")
                    expect("唯讀" in text, f"{label}: viewer not stated in words")
                if scenario == "disconnected":
                    expect(page.get_by_role("button", name="重新連線").is_visible(), f"{label}: reconnect not offered")
                if scenario == "shell":
                    tab = page.locator('[role="tab"][data-shell]')
                    expect(tab.is_visible() and "系統" in tab.inner_text(), f"{label}: system shell tab not distinct")
                    expect(page.locator(".terminal[data-shell]").count() == 1, f"{label}: shell pane not marked")
        context.close()
    passed("every detail state shows session name, 3 separate state cells, files + native terminal tabs; posture/takeover/reconnect/shell distinct (390x844 and 844x390)")


def behaviour_suite(browser: Browser, base: str, passed) -> None:
    context = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
    page = context.new_page()
    load(page, base, "a", "list")
    page.get_by_role("button", name=re.compile("開啟 demo-web-refactor")).click()
    expect(page.locator(".sbar h1").inner_text() == "demo-web-refactor", "list did not open the exact session")
    page.get_by_role("tab", name="終端機").focus()
    page.keyboard.press("ArrowRight")
    expect(page.get_by_role("tab", name="檔案").get_attribute("aria-selected") == "true", "arrow key tab navigation failed")
    page.locator('[data-dir="src"]').first.click()
    page.locator('[data-path="src/router.ts"]').click()
    expect(page.locator(".pbar h1").inner_text() == "router.ts", "preview did not open")
    expect("唯讀" in page.locator(".pbar .sub").inner_text(), "preview does not say read-only")
    page.keyboard.press("Escape")
    active = page.evaluate("document.activeElement && document.activeElement.id")
    expect(active == "f-src-router-ts", f"focus did not return to the opening row: {active}")
    passed("list -> exact session -> files -> preview -> Escape returns focus to the row")

    menu = page.get_by_role("button", name="Session 選單與資訊")
    menu.click()
    expect(page.get_by_role("dialog").is_visible(), "menu sheet did not open")
    expect("sess-7f2a-demo" in page.get_by_role("dialog").inner_text(), "full session id not reachable")
    page.keyboard.press("Escape")
    expect(page.get_by_role("dialog").count() == 0, "Escape did not close the sheet")
    expect(page.evaluate("document.activeElement.getAttribute('aria-label')") == "Session 選單與資訊", "focus not returned to menu button")
    passed("menu sheet exposes the full session id; Escape closes and returns focus")

    load(page, base, "a", "activity")
    page.get_by_role("button", name="終端機").last.click()
    expect(page.get_by_role("tab", name="終端機").get_attribute("aria-selected") == "true", "activity -> terminal is not one tap")
    load(page, base, "a", "unsupported")
    expect(page.get_by_role("button", name="開啟終端機").is_visible(), "unsupported runtime has no terminal fallback")
    load(page, base, "a", "await")
    expect(page.get_by_role("button", name=re.compile("批准|允許|approve", re.I)).count() == 0, "activity must never offer an approve button")
    passed("activity (hypothesis): terminal one tap away, unsupported -> native fallback, no approve control")

    # Visible focus: the first Tab lands on a control with a 3px focus outline.
    load(page, base, "b", "terminal")
    for _ in range(6):
        page.keyboard.press("Tab")
        if page.evaluate("!!document.activeElement.closest('#app')"):
            break
    ring = page.evaluate("(() => { const s = getComputedStyle(document.activeElement); return [s.outlineStyle, s.outlineWidth, document.activeElement.tagName]; })()")
    expect(ring[0] == "solid" and ring[1] == "3px", f"focus ring not visible: {ring}")
    passed(f"keyboard focus is visible (outline {ring[1]} {ring[0]} on {ring[2]})")

    storage = page.evaluate("[localStorage.length, sessionStorage.length]")
    expect(storage == [0, 0], f"prototype wrote browser storage: {storage}")
    passed("no localStorage/sessionStorage use")
    context.close()


FIT_SIZES = [(360, 800), (390, 844), (430, 932), (844, 390), ZOOM_200]
FIT_PROBE = """() => {
  const rect = (el) => el && el.getBoundingClientRect();
  const overlap = (a, b) => a && b && Math.max(0, Math.min(a.right, b.right) - Math.max(a.left, b.left)) *
                                       Math.max(0, Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top));
  const out = { terminal: [], title: [], collide: [], cells: [], rules: [] };
  for (const t of document.querySelectorAll('.terminal')) {
    if (t.scrollWidth > t.clientWidth + 1) out.terminal.push(`${t.scrollWidth}>${t.clientWidth}`);
    if (t.textContent.includes('demo agent cli')) {
      const inner = t.clientWidth - parseFloat(getComputedStyle(t).paddingLeft) - parseFloat(getComputedStyle(t).paddingRight);
      const rules = [...t.querySelectorAll('.rule')];
      if (!rules.length) out.rules.push('no fluid divider/input lines');
      for (const r of rules) {
        const w = r.getBoundingClientRect().width;
        if (w < inner * 0.85 || w > inner + 1) out.rules.push(`${Math.round(w)} vs ${Math.round(inner)}`);
      }
    }
  }
  for (const el of document.querySelectorAll('.sbar h1, .sbar .sub')) {
    const truncated = el.scrollWidth > el.clientWidth + 1;
    if (truncated && el.getAttribute('title') !== el.textContent.trim()) out.title.push(el.textContent.trim().slice(0, 30));
  }
  const top = document.querySelector('.detail-top');
  if (top) {
    const parts = ['.sbar', '.state-line', '.posture-line', '.tabs'].map((s) => [s, top.querySelector(s)]).filter(([, e]) => e);
    for (let i = 0; i < parts.length; i++) for (let j = i + 1; j < parts.length; j++) {
      if (overlap(rect(parts[i][1]), rect(parts[j][1])) > 2) out.collide.push(`${parts[i][0]}×${parts[j][0]}`);
    }
    const line = top.querySelector('.state-line');
    for (const c of top.querySelectorAll('.state-line .cell')) {
      const lr = rect(line), cr = rect(c);
      if (cr.right > lr.right + 1 || cr.left < lr.left - 1 || c.scrollWidth > c.clientWidth + 1) out.cells.push(c.textContent.trim().slice(0, 20));
    }
  }
  return out;
}"""


def c_direction_suite(browser: Browser, base: str, passed) -> None:
    """plan/32 v0.2: fixes made when the owner chose C. Failures are collected per fix."""
    fails: dict[str, list[str]] = {"F1": [], "F2": [], "F3": [], "F4": []}
    context = browser.new_context(viewport={"width": 390, "height": 844})
    page = context.new_page()
    page.goto(base, wait_until="domcontentloaded")
    page.wait_for_selector("#app > *")
    chosen = page.evaluate("[document.documentElement.dataset.variant, document.querySelector('#variant-select').value]")
    if chosen != ["c", "c"]:
        fails["F4"].append(f"default variant without ?v= is {chosen}, expected C")
    page.goto(f"{base}?v=a&s=terminal", wait_until="domcontentloaded")
    if page.evaluate("document.documentElement.dataset.variant") != "a":
        fails["F4"].append("?v=a no longer selects A")
    context.close()

    for width, height in FIT_SIZES:
        context = browser.new_context(viewport={"width": width, "height": height}, is_mobile=True, has_touch=True)
        page = context.new_page()
        for variant in VARIANTS:
            for scenario in DETAIL_SCENARIOS:
                load(page, base, variant, scenario)
                label = f"{variant}/{scenario}@{width}x{height}"
                r = page.evaluate(FIT_PROBE)
                for key in ("terminal", "title", "collide", "cells"):
                    fails["F1"] += [f"{label} {key}: {x}" for x in r[key]]
                fails["F3"] += [f"{label}: {x}" for x in r["rules"]]
                if scenario in ("viewer", "viewer-locked"):
                    text = page.locator(".terminal").first.inner_text()
                    if "╭" in text or "│ >" in text:
                        fails["F2"].append(f"{label}: viewer sees a terminal input box")
                    if scenario == "viewer" and variant == "c":
                        # "Full width" = fills the content box of the foot that replaces the input.
                        box = page.evaluate("""() => { const b = [...document.querySelectorAll('.pane .term-foot button')].find((x) => x.textContent.includes('取得控制權'));
                                                       if (!b || !b.offsetParent) return 0; const f = b.parentElement, cs = getComputedStyle(f);
                                                       const inner = f.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
                                                       return b.getBoundingClientRect().width / inner; }""")
                        if box < 0.99:
                            fails["F2"].append(f"{label}: no full-width 取得控制權 in place of the input (ratio {box:.2f})")
        context.close()
    report = {k: v[:4] + ([f"... +{len(v) - 4} more"] if len(v) > 4 else []) for k, v in fails.items() if v}
    expect(not report, "C-direction fixes failing:\n" + json.dumps(report, ensure_ascii=False, indent=1))
    passed("C direction: default ?v=c; header/terminal fit without collision or silent truncation at 360/390/430/844x390/200%; "
           "fluid divider and input lines; Viewer has no input box and C offers a full-width 取得控制權")


def motion_suite(browser: Browser, base: str, passed) -> None:
    durations = {}
    for mode in ("no-preference", "reduce"):
        context = browser.new_context(viewport={"width": 390, "height": 844}, reduced_motion=mode)
        page = context.new_page()
        load(page, base, "c", "menu")
        durations[mode] = page.evaluate("getComputedStyle(document.querySelector('.sheet')).animationDuration")
        context.close()
    expect(durations["no-preference"] == "0.18s", f"variant C sheet motion missing: {durations}")
    expect(durations["reduce"] == "0s", f"reduced motion not respected: {durations}")
    passed(f"reduced motion respected (sheet {durations['no-preference']} -> {durations['reduce']})")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--chromium", type=Path, help="Chromium executable; omit to use Playwright-managed Chromium")
    parser.add_argument("--evidence-dir", type=Path, help="optional directory for a JSON result file (outside the repo)")
    args = parser.parse_args()

    lines: list[str] = []

    def passed(message: str) -> None:
        lines.append(f"PASS {message}")
        print(f"PASS {message}", flush=True)

    passed(check_literal_colours())
    message, contrast_report = check_contrast()
    passed(message)
    passed(check_real_data())

    page_errors: list[str] = []
    requests: list[str] = []
    with local_server(HERE) as base, sync_playwright() as playwright:
        options = {"headless": True}
        if args.chromium:
            options["executable_path"] = str(args.chromium)
        browser = playwright.chromium.launch(**options)
        try:
            probe = browser.new_context()
            page = probe.new_page()
            page.on("pageerror", lambda error: page_errors.append(str(error)))
            page.on("request", lambda request: requests.append(request.url))
            for variant in VARIANTS:
                for scenario in ALL_SCENARIOS:
                    load(page, base, variant, scenario)
            probe.close()
            geometry_suite(browser, base, passed)
            ia_invariants_suite(browser, base, passed)
            behaviour_suite(browser, base, passed)
            c_direction_suite(browser, base, passed)
            motion_suite(browser, base, passed)
        finally:
            browser.close()
        external = sorted({url for url in requests if not url.startswith(base)})
        unexpected = sorted({url.split("?")[0] for url in requests if url.startswith(base)} - {base, f"{base}style.css", f"{base}app.js"})
    expect(not page_errors, f"page errors: {page_errors}")
    expect(not external and not unexpected, f"unexpected requests: {external + unexpected}")
    passed("no page errors, external requests, API calls or WebSockets")

    if args.evidence_dir:
        args.evidence_dir.mkdir(parents=True, exist_ok=True)
        (args.evidence_dir / "mobile-visual-ia-test.json").write_text(
            json.dumps({"result": "PASS", "checks": lines, "contrast": contrast_report}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(f"RESULT PASS ({len(lines)} checks)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
