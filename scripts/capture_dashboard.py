#!/usr/bin/env python3
"""Regenerate the dashboard captures the READMEs and the site embed.

The captures are the real dashboard: this starts it, drives a headless Firefox through a
comparison the way a person would -- choosing two files, pressing Compare -- and photographs
the result. It shows the same two files the terminal capture compares, so both interfaces
describe the same diff.

    python scripts/capture_dashboard.py

Needs the `web` extra and `firefox` on PATH. Firefox is driven over Marionette, its own remote
protocol, spoken here with the standard library: there is no browser-automation package to
install and none to keep in step with the browser. Without Firefox nothing is written.
"""

from __future__ import annotations

import base64
import json
import math
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
ASSETS = REPO_ROOT / "docs" / "assets"
FIXTURES = REPO_ROOT / "tests" / "fixtures"

# The same pair of files `capture_cli.py` compares, bumped from the version the delimiter
# capture and the README's examples already use.
CURRENT_VERSION = "1.4.2"

# CSS pixels. The page is photographed at twice this, so a README that scales it down to a
# column still reads sharp on a dense screen.
WIDTH = 1120
SCALE = 2
# Room left around a photographed card. Less than the 18px between two cards, so a photograph
# neither opens nor closes on the edge of the card next to the one it is about.
TOP_MARGIN = 14
BOTTOM_MARGIN = 14


class Marionette:
    """A Firefox started headless, and the few commands of its remote protocol this needs."""

    def __init__(self, profile: Path, port: int) -> None:
        prefs = {
            "marionette.port": port,
            # The captures are dark, like the terminal ones, and in English whatever the
            # machine's language is: the browser's own wording would otherwise leak in.
            "ui.systemUsesDarkTheme": 1,
            "intl.accept_languages": "en-US",
            "layout.css.devPixelsPerPx": str(float(SCALE)),
            "browser.shell.checkDefaultBrowser": False,
        }
        profile.joinpath("user.js").write_text(
            "".join(f"user_pref({json.dumps(k)}, {json.dumps(v)});\n" for k, v in prefs.items()),
            encoding="utf-8",
        )
        self._process = subprocess.Popen(
            [
                "firefox",
                "--headless",
                "--marionette",
                "--no-remote",
                "--profile",
                str(profile),
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self._socket = self._connect(port)
        self._sent = 0
        self._receive()  # the greeting
        self.command("WebDriver:NewSession", capabilities={})

    @staticmethod
    def _connect(port: int) -> socket.socket:
        for _ in range(150):
            try:
                return socket.create_connection(("127.0.0.1", port), timeout=30)
            except OSError:
                time.sleep(0.2)
        raise SystemExit("firefox did not open its Marionette port")

    def _receive(self) -> Any:
        """One message: its length in bytes, a colon, then that many bytes of JSON."""
        header = b""
        while not header.endswith(b":"):
            header += self._socket.recv(1)
        remaining = int(header[:-1])
        body = b""
        while len(body) < remaining:
            body += self._socket.recv(remaining - len(body))
        return json.loads(body)

    def command(self, name: str, **parameters: Any) -> Any:
        self._sent += 1
        body = json.dumps([0, self._sent, name, parameters]).encode()
        self._socket.sendall(str(len(body)).encode() + b":" + body)
        _kind, _id, error, result = self._receive()
        if error:
            raise SystemExit(f"{name}: {error.get('message', error)}")
        return result

    def script(self, source: str, *arguments: Any) -> Any:
        return self.command("WebDriver:ExecuteScript", script=source, args=list(arguments))["value"]

    def wait_for(self, condition: str, what: str, seconds: float = 20.0) -> None:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if self.script(f"return Boolean({condition});"):
                return
            time.sleep(0.1)
        raise SystemExit(f"timed out waiting for {what}")

    def upload(self, selector: str, path: Path) -> None:
        found = self.command("WebDriver:FindElement", using="css selector", value=selector)
        element = next(iter(found["value"].values()))
        self.command("WebDriver:ElementSendKeys", id=element, text=str(path))

    def resize(self, height: int) -> None:
        """Make the page area exactly WIDTH by `height` CSS pixels.

        A window is sized including the browser's own chrome even when headless, so the
        viewport it leaves is shorter than the number asked for. It is measured and corrected
        by the shortfall, which settles on the second try.
        """
        height = max(height, 200)
        rect_width, rect_height = WIDTH, height
        for _ in range(4):
            self.command("WebDriver:SetWindowRect", width=rect_width, height=rect_height)
            time.sleep(0.3)  # the window settles after the command has been acknowledged
            width, tall = self.script("return [innerWidth, innerHeight];")
            if (width, tall) == (WIDTH, height):
                return
            rect_width += WIDTH - width
            rect_height += height - tall
        raise SystemExit(f"could not size the window to {WIDTH}x{height}; it is {width}x{tall}")

    def photograph(self, target: Path) -> None:
        shot = self.command("WebDriver:TakeScreenshot", full=False)["value"]
        target.write_bytes(base64.b64decode(shot))

    def close(self) -> None:
        self._process.terminate()
        try:
            self._process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self._process.kill()


def main() -> int:
    if shutil.which("firefox") is None:
        print("firefox is not on PATH; the dashboard captures were left untouched.")
        return 0
    try:
        import uvicorn  # noqa: F401
    except ImportError:
        raise SystemExit('the dashboard is not installed: pip install "datasemver[web]"') from None

    ASSETS.mkdir(parents=True, exist_ok=True)
    port, marionette = _free_port(), _free_port()
    with tempfile.TemporaryDirectory() as tmp:
        server = _start_dashboard(port)
        try:
            browser = Marionette(Path(tmp), marionette)
            try:
                _capture(browser, f"http://127.0.0.1:{port}/")
            finally:
                browser.close()
        finally:
            server.terminate()
            server.wait(timeout=10)
    return 0


def _capture(browser: Marionette, url: str) -> None:
    browser.resize(900)
    browser.command("WebDriver:Navigate", url=url)
    browser.wait_for("document.getElementById('upload-hint').textContent", "the page to load")

    browser.upload("input[name=old]", FIXTURES / "old.csv")
    browser.upload("input[name=new]", FIXTURES / "new.csv")
    browser.script(
        "document.querySelector('input[name=current_version]').value = arguments[0];",
        CURRENT_VERSION,
    )
    browser.script("document.getElementById('compare-form').requestSubmit();")
    browser.wait_for(
        "!document.getElementById('result').classList.contains('is-hidden')", "the report"
    )
    # The cards rise on a spring, the severity bar grows a segment at a time and the version rolls
    # up to its new value; the last of them settles a little before two seconds.
    time.sleep(2.2)

    # The two files and the verdict they earn, which is the whole story at a height a page can
    # spare: it is the one a site sets in a section, where the full report would be a wall.
    top = _top_of(browser, "#compare-form")
    bottom = _bottom_of(browser, "#summary")
    browser.resize(bottom - top + TOP_MARGIN + BOTTOM_MARGIN)
    _scroll_to(browser, top - TOP_MARGIN)
    browser.photograph(ASSETS / "dashboard-verdict.png")
    print("  docs/assets/dashboard-verdict.png")

    # Top of the page to the foot of the changes table: what the dashboard says at a glance.
    foot = _bottom_of(browser, "#changes-table")
    browser.resize(foot + BOTTOM_MARGIN)
    _scroll_to(browser, 0)
    browser.photograph(ASSETS / "dashboard-report.png")
    print("  docs/assets/dashboard-report.png")

    # The column comparison and the changelog entry, which the first image has no room for.
    top = _top_of(browser, "#columns-table", card=True)
    bottom = _bottom_of(browser, "#changelog")
    browser.resize(bottom - top + TOP_MARGIN + BOTTOM_MARGIN)
    _scroll_to(browser, top - TOP_MARGIN)
    browser.photograph(ASSETS / "dashboard-columns.png")
    print("  docs/assets/dashboard-columns.png")


def _top_of(browser: Marionette, selector: str, card: bool = False) -> int:
    return math.floor(
        browser.script(
            "const el = document.querySelector(arguments[0]);"
            "const box = (arguments[1] ? el.closest('.card') : el).getBoundingClientRect();"
            "return box.top + scrollY;",
            selector,
            card,
        )
    )


def _bottom_of(browser: Marionette, selector: str) -> int:
    return math.ceil(
        browser.script(
            "const el = document.querySelector(arguments[0]);"
            "return (el.closest('.card') || el).getBoundingClientRect().bottom + scrollY;",
            selector,
        )
    )


def _scroll_to(browser: Marionette, top: int) -> None:
    # `behavior: "instant"`: the stylesheet asks for smooth scrolling, which would still be
    # moving when the shutter fires.
    browser.script("window.scrollTo({ top: arguments[0], behavior: 'instant' });", top)
    time.sleep(0.3)


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _start_dashboard(port: int) -> subprocess.Popen[bytes]:
    environment = {**os.environ, "DATASEMVER_DATASETS_DIR": str(REPO_ROOT / "datasets")}
    server = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "datasemver_web.backend.main:app",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        cwd=REPO_ROOT,
        env=environment,
    )
    for _ in range(100):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=1).close()
            return server
        except OSError:
            time.sleep(0.1)
    server.terminate()
    raise SystemExit("the dashboard did not start")


if __name__ == "__main__":
    sys.exit(main())
