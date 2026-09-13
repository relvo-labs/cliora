#!/usr/bin/env python3
"""Real-browser checks for the fixture-only mobile session prototype."""

from __future__ import annotations

import argparse
import contextlib
import json
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable

from playwright.sync_api import Page, sync_playwright


VERIFIED_CHROMIUM = Path(
    "/opt/hermes/.playwright/chromium_headless_shell-1243/"
    "chrome-headless-shell-linux64/chrome-headless-shell"
)
VIEWPORTS = [
    (360, 844),
    (390, 844),
    (430, 932),
    (844, 390),
    (768, 844),
    (1024, 768),
    (1100, 800),
    (1440, 900),
]


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, _format: str, *_args: object) -> None:
        return


@contextlib.contextmanager
def local_server(directory: Path):
    handler = partial(QuietHandler, directory=str(directory))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
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


def open_session(page: Page, name: str = "web / Claude") -> None:
    page.get_by_role("button", name=f"開啟 {name}", exact=False).click()


def open_files(page: Page) -> None:
    page.get_by_role("tab", name="Files").click()
    page.locator("#file-search-input").wait_for()


def choose_fixture(page: Page, value: str) -> None:
    page.locator("#fixture-select").select_option(value)


def assert_no_document_overflow(page: Page, label: str) -> None:
    metrics = page.evaluate(
        """() => ({
          html: [document.documentElement.scrollWidth, document.documentElement.clientWidth],
          body: [document.body.scrollWidth, document.body.clientWidth]
        })"""
    )
    expect(metrics["html"][0] <= metrics["html"][1] + 1, f"{label}: html overflow {metrics}")
    expect(metrics["body"][0] <= metrics["body"][1] + 1, f"{label}: body overflow {metrics}")


def assert_touch_targets(page: Page, label: str) -> None:
    failures = page.evaluate(
        """() => [...document.querySelectorAll('button,input,select')]
          .filter((el) => {
            const r = el.getBoundingClientRect();
            const s = getComputedStyle(el);
            return s.visibility !== 'hidden' && s.display !== 'none' &&
              r.right > 0 && r.bottom > 0 && r.left < innerWidth && r.top < innerHeight;
          })
          .map((el) => {
            const r = el.getBoundingClientRect();
            return {name: el.getAttribute('aria-label') || el.textContent.trim() || el.id,
                    width: r.width, height: r.height};
          })
          .filter((box) => box.width < 44 || box.height < 44)"""
    )
    expect(not failures, f"{label}: touch targets below 44px: {failures}")


def behavior_suite(page: Page, base_url: str, passed: Callable[[str], None]) -> None:
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(base_url, wait_until="networkidle")
    page.get_by_role("heading", name="回到工作現場").wait_for()
    passed("session-first list renders")

    open_session(page)
    expect(page.locator(".context-item").nth(0).inner_text().endswith("sess-web-7f2a"), "exact session id missing")
    context = page.locator(".context-grid").inner_text()
    for value in ("lab-tpe", "Claude", "~/workspace/web"):
        expect(value in context, f"session context missing {value}")
    expect(page.get_by_role("tab", name="Terminal").get_attribute("aria-selected") == "true", "terminal not selected")
    expect("合成 stdout" in page.locator(".terminal-bar").inner_text(), "terminal not labeled synthetic")
    expect(page.locator("input").count() == 0, "terminal unexpectedly exposes input")
    passed("exact session and synthetic terminal contract")

    page.get_by_role("tab", name="Terminal").press("ArrowRight")
    page.locator("#file-search-input").wait_for()
    expect(page.get_by_role("tab", name="Files").get_attribute("aria-selected") == "true", "tab keyboard navigation failed")

    page.locator('[data-path="src"]').click()
    expect(page.locator("#file-region").get_attribute("data-dir") == "src", "folder browse failed")
    page.locator('[data-path="src/components"]').click()
    expect(page.locator("#file-region").get_attribute("data-dir") == "src/components", "nested browse failed")
    page.get_by_role("button", name="src", exact=True).click()
    expect(page.locator("#file-region").get_attribute("data-dir") == "src", "breadcrumb failed")
    page.get_by_role("button", name="上一層").click()
    expect(page.locator("#file-region").get_attribute("data-dir") == ".", "up navigation failed")
    passed("folder browse, up, and breadcrumb")

    page.locator('[data-path="src"]').click()
    page.locator("#file-search-input").fill("mobile-guide")
    page.locator("#file-search-input").press("Enter")
    expect(page.locator('[data-path="docs/mobile-guide.md"]').count() == 1, "search did not cover whole workspace")
    expect("整個工作區" in page.locator(".scope-note").inner_text(), "search scope label missing")
    page.locator("#file-search-input").press("Escape")
    expect(page.locator("#file-search-input").input_value() == "", "search Escape did not clear")
    expect(page.locator("#file-region").get_attribute("data-dir") == "src", "search clear lost folder")
    passed("whole-workspace filename substring search")

    page.get_by_role("button", name="web").click()
    region = page.locator("#file-region")
    region.evaluate("el => { el.scrollTop = 360; }")
    page.locator('[data-path="notes-04.md"]').click()
    viewer = page.locator("#code-viewer")
    viewer.wait_for()
    viewer.evaluate("el => { el.scrollTop = 520; }")
    page.keyboard.press("Escape")
    expect(region.evaluate("el => el.scrollTop") > 0, "file-list scroll was not restored")
    active_id = page.evaluate("document.activeElement && document.activeElement.id")
    expect("notes-04-md" in active_id, f"preview focus did not return: {active_id}")
    page.locator('[data-path="notes-04.md"]').click()
    expect(viewer.evaluate("el => el.scrollTop") >= 500, "preview nonzero scroll was not restored")
    passed("preview/list scroll restoration, focus return, and Escape")

    page.get_by_role("button", name="回到工作階段清單").click()
    open_session(page, "api / Codex")
    expect("sess-api-31bc" in page.locator(".context-grid").inner_text(), "session did not switch")
    expect(page.locator("text=notes-04.md").count() == 0, "old preview leaked after session switch")
    open_files(page)
    expect(page.locator("#file-search-input").input_value() == "", "old search leaked after session switch")
    expect(page.locator("#file-region").get_attribute("data-dir") == ".", "old path leaked after session switch")
    passed("session switch wipes preview, path, search, and scroll state")

    choose_fixture(page, "forbidden")
    page.get_by_role("heading", name="403 · 無法存取目前工作區").wait_for()
    page.get_by_role("button", name="回到工作階段清單").click()
    open_session(page)
    open_files(page)
    expect(page.locator("#file-region").count() == 1, "403 state leaked into next session")
    passed("session switch while 403 clears denial state")

    choose_fixture(page, "failure")
    page.get_by_role("heading", name="暫時載入失敗").wait_for()
    page.get_by_role("button", name="重試合成載入").click()
    expect("未連線任何服務" in page.locator(".notice").inner_text(), "retry was not honestly labeled")
    choose_fixture(page, "empty")
    page.get_by_role("heading", name="這個資料夾是空的").wait_for()
    choose_fixture(page, "ended")
    page.get_by_role("heading", name="Session 已結束，檔案瀏覽不可用").wait_for()
    passed("failure retry, empty folder, and ended-session states")

    choose_fixture(page, "unsupported")
    page.get_by_role("heading", name="不支援此檔案的預覽").wait_for()
    expect("不是圖片檢視器" in page.locator(".notice").inner_text(), "image refusal contract missing")
    page.keyboard.press("Escape")
    choose_fixture(page, "too-large")
    page.get_by_role("heading", name="檔案過大，拒絕預覽").wait_for()
    expect("2 MiB" in page.locator(".notice").inner_text(), "large-file bound missing")
    page.keyboard.press("Escape")
    passed("binary/image refusal and too-large denial")

    for value, reason in (
        ("partial-results", "results"),
        ("partial-depth", "depth"),
        ("partial-scanned", "scanned"),
        ("partial-timeout", "timeout"),
    ):
        choose_fixture(page, value)
        note = page.locator("[data-stop-reason]")
        expect(note.get_attribute("data-stop-reason") == reason, f"partial reason {reason} missing")
        expect("已掃描" in note.inner_text(), f"partial scanned count missing for {reason}")
    passed("all bounded-search stop reasons are visible")

    page.get_by_role("button", name="回到工作階段清單").click()
    first = page.get_by_role("button", name="開啟 web / Claude", exact=False)
    first.focus()
    first.press("Enter")
    page.get_by_role("heading", name="web / Claude").wait_for()
    passed("keyboard session activation")

    storage = page.evaluate("() => ({local: localStorage.length, session: sessionStorage.length})")
    expect(storage == {"local": 0, "session": 0}, f"browser storage not empty: {storage}")
    passed("no persistent browser storage")


def responsive_suite(page: Page, base_url: str, passed: Callable[[str], None]) -> None:
    for width, height in VIEWPORTS:
        page.set_viewport_size({"width": width, "height": height})
        page.goto(base_url, wait_until="domcontentloaded")
        assert_no_document_overflow(page, f"{width}x{height} sessions")
        assert_touch_targets(page, f"{width}x{height} sessions")
        open_session(page)
        assert_no_document_overflow(page, f"{width}x{height} terminal")
        assert_touch_targets(page, f"{width}x{height} terminal")
        open_files(page)
        assert_no_document_overflow(page, f"{width}x{height} files")
        assert_touch_targets(page, f"{width}x{height} files")
    passed("8 responsive sizes have no document overflow and visible controls are >=44px")


def screenshot_suite(page: Page, base_url: str, evidence: Path, passed: Callable[[str], None]) -> None:
    shots = evidence / "screenshots"
    shots.mkdir(parents=True, exist_ok=True)
    for label, width, height in (("mobile", 390, 844), ("desktop", 1440, 900)):
        page.set_viewport_size({"width": width, "height": height})
        page.goto(base_url, wait_until="domcontentloaded")
        page.screenshot(path=shots / f"{label}-session-primary.png")
        open_session(page)
        open_files(page)
        page.screenshot(path=shots / f"{label}-files.png")
        page.locator('[data-path="README.md"]').click()
        page.screenshot(path=shots / f"{label}-preview.png")
        page.keyboard.press("Escape")
        choose_fixture(page, "failure")
        page.screenshot(path=shots / f"{label}-error.png")
    passed("8 external screenshots captured")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument(
        "--chromium",
        type=Path,
        help=f"Optional Chromium executable; omit to use Playwright-managed Chromium. Verified here: {VERIFIED_CHROMIUM}",
    )
    args = parser.parse_args()
    args.evidence_dir.mkdir(parents=True, exist_ok=True)
    if args.chromium is not None and not args.chromium.is_file():
        raise SystemExit(f"Chromium executable not found: {args.chromium}")

    prototype = Path(__file__).resolve().parent
    pass_lines: list[str] = []
    console_lines: list[str] = []
    page_errors: list[str] = []
    requests: list[tuple[str, str]] = []
    websockets: list[str] = []

    def passed(message: str) -> None:
        line = f"PASS {message}"
        pass_lines.append(line)
        print(line, flush=True)

    with local_server(prototype) as base_url, sync_playwright() as playwright:
        launch_options = {"headless": True}
        if args.chromium is not None:
            launch_options["executable_path"] = str(args.chromium)
        browser = playwright.chromium.launch(**launch_options)
        try:
            context = browser.new_context(reduced_motion="reduce")
            page = context.new_page()
            page.on("console", lambda message: console_lines.append(f"{message.type}: {message.text}"))
            page.on("pageerror", lambda error: page_errors.append(str(error)))
            page.on("request", lambda request: requests.append((request.resource_type, request.url)))
            page.on("websocket", lambda socket: websockets.append(socket.url))
            behavior_suite(page, base_url, passed)
            responsive_suite(page, base_url, passed)
            screenshot_suite(page, base_url, args.evidence_dir, passed)
            expect(page.evaluate("matchMedia('(prefers-reduced-motion: reduce)').matches"), "reduced motion media did not match")
            passed("reduced-motion browser mode active")
            page.emulate_media(color_scheme="dark", reduced_motion="reduce")
            page.goto(base_url, wait_until="domcontentloaded")
            open_session(page)
            mobile_colors = page.evaluate(
                """() => ({
                  scheme: getComputedStyle(document.documentElement).colorScheme,
                  canvas: getComputedStyle(document.body).backgroundColor,
                  terminal: getComputedStyle(document.querySelector('.terminal-output')).backgroundColor
                })"""
            )
            expect(
                mobile_colors == {
                    "scheme": "light",
                    "canvas": "rgb(247, 248, 250)",
                    "terminal": "rgb(255, 255, 255)",
                },
                f"OS dark preference changed the mobile light palette: {mobile_colors}",
            )
            passed("OS dark preference keeps the mobile prototype light")
            context.close()
        finally:
            browser.close()

    allowed_requests = {
        ("document", base_url),
        ("stylesheet", f"{base_url}style.css"),
        ("script", f"{base_url}app.js"),
    }
    unexpected = sorted(set(requests) - allowed_requests)
    external = [url for _, url in requests if not url.startswith(base_url)]
    expect(not external, f"external requests observed: {external}")
    expect(not unexpected, f"API or unexpected local requests observed: {unexpected}")
    expect(not websockets, f"WebSocket traffic observed: {websockets}")
    expect(not page_errors, f"page errors observed: {page_errors}")
    passed("no external requests, WebSocket traffic, or JavaScript page errors")

    (args.evidence_dir / "browser-console.log").write_text(
        "\n".join(console_lines) + ("\n" if console_lines else ""), encoding="utf-8"
    )
    result = {
        "result": "PASS",
        "chromium": str(args.chromium) if args.chromium is not None else "playwright-managed",
        "viewports": [f"{width}x{height}" for width, height in VIEWPORTS],
        "checks": pass_lines,
        "external_requests": external,
        "unexpected_local_requests": unexpected,
        "websockets": websockets,
        "page_errors": page_errors,
    }
    (args.evidence_dir / "prototype-test-results.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"RESULT PASS ({len(pass_lines)} checks)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
