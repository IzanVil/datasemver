#!/usr/bin/env python3
"""Regenerate the terminal captures the README embeds.

The captures are real CLI runs, not mockups: this swaps the console the CLI prints through
for a recording one, invokes the commands, and exports what rich rendered. Run it whenever
the CLI output changes, so the images in the README keep matching the tool.

    python scripts/capture_cli.py

SVGs are written unconditionally. Rasterising them to the PNGs the README links needs a
headless browser or an SVG converter on PATH; the script reports what it found and skips
that step when there is nothing to use.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from rich.console import Console
from rich.terminal_theme import TerminalTheme
from typer.testing import CliRunner

import datasemver.cli.main as cli

REPO_ROOT = Path(__file__).resolve().parents[1]
ASSETS = REPO_ROOT / "docs" / "assets"
WIDTH = 104

# Matches the palette of the architecture notes: a calm dark ground with the severity hues
# the CLI already assigns to major, minor and patch.
THEME = TerminalTheme(
    (16, 19, 26),
    (226, 232, 240),
    [
        (16, 19, 26), (239, 133, 120), (92, 191, 162), (223, 173, 92),
        (126, 179, 215), (197, 152, 224), (126, 204, 204), (200, 208, 220),
    ],
    [
        (70, 80, 95), (244, 160, 148), (124, 209, 184), (235, 196, 132),
        (158, 201, 228), (214, 180, 235), (158, 220, 220), (230, 236, 245),
    ],
)

SEMICOLON_V1 = """id;cliente;pais;importe;estado
1;Ana Ruiz;ES;1240,00;pagado
2;Bruno Sala;IT;890,50;pagado
3;Carla Diaz;PT;1580,25;pendiente
4;Diego Moro;ES;720,00;pagado
5;Elena Vidal;FR;2100,75;pagado
6;Felipe Cano;ES;450,00;pendiente
7;Gema Ortiz;IT;1330,00;pagado
8;Hugo Lara;PT;980,40;pagado
"""

SEMICOLON_V2 = """id;cliente;pais;importe;estado;canal
1;Ana Ruiz;ES;1240,00;pagado;web
2;Bruno Sala;IT;890,50;pagado;tienda
3;Carla Diaz;PT;1580,25;pagado;web
4;Diego Moro;ES;720,00;pagado;web
5;Elena Vidal;FR;2100,75;pagado;tienda
6;Felipe Cano;ES;450,00;pagado;web
7;Gema Ortiz;IT;1330,00;pagado;web
8;Hugo Lara;PT;980,40;pagado;tienda
9;Irene Sanz;FR;1750,00;pagado;web
10;Jorge Pena;ES;1120,00;pagado;tienda
"""


@dataclass(frozen=True)
class Capture:
    """One recorded CLI run and the file it becomes."""

    name: str
    title: str
    args: list[str]
    cwd: Path | None = None


def main() -> int:
    ASSETS.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        sales = _write_semicolon_pair(Path(tmp))
        captures = [
            Capture(
                "cli-diff",
                "datasemver diff",
                ["diff", "tests/fixtures/old.csv", "tests/fixtures/new.csv"],
                REPO_ROOT,
            ),
            Capture("cli-rules", "datasemver rules", ["rules"], REPO_ROOT),
            Capture(
                "cli-delimiter",
                "datasemver diff — semicolon-delimited CSV",
                ["diff", "ventas_v1.csv", "ventas_v2.csv", "--current-version", "1.4.2"],
                sales,
            ),
        ]
        written = [_record(capture) for capture in captures]

    rasteriser = _find_rasteriser()
    if rasteriser is None:
        print("\nno rasteriser found; the PNGs the README links were left untouched.")
        print("install one of: firefox, chromium, rsvg-convert")
        return 0

    print(f"\nrasterising with {rasteriser.name}")
    for svg in written:
        _rasterise(rasteriser, svg)
    return 0


def _write_semicolon_pair(root: Path) -> Path:
    (root / "ventas_v1.csv").write_text(SEMICOLON_V1, encoding="utf-8")
    (root / "ventas_v2.csv").write_text(SEMICOLON_V2, encoding="utf-8")
    return root


def _record(capture: Capture) -> Path:
    """Invoke one command through a recording console and export what it rendered."""
    recorder = Console(record=True, width=WIDTH, force_terminal=True)
    original, cli.console = cli.console, recorder
    previous = Path.cwd()
    try:
        if capture.cwd is not None:
            import os

            os.chdir(capture.cwd)
        result = CliRunner().invoke(cli.app, capture.args)
    finally:
        cli.console = original
        import os

        os.chdir(previous)

    if result.exit_code != 0:
        raise SystemExit(f"{capture.name}: exited {result.exit_code}\n{result.output}")

    target = ASSETS / f"{capture.name}.svg"
    target.write_text(recorder.export_svg(title=capture.title, theme=THEME), encoding="utf-8")
    print(f"  {target.relative_to(REPO_ROOT)}")
    return target


@dataclass(frozen=True)
class Rasteriser:
    """An external tool able to turn one of the SVGs into a PNG."""

    name: str
    path: str


def _find_rasteriser() -> Rasteriser | None:
    for name in ("firefox", "chromium", "chromium-browser", "google-chrome", "rsvg-convert"):
        found = shutil.which(name)
        if found:
            return Rasteriser(name, found)
    return None


def _rasterise(tool: Rasteriser, svg: Path) -> None:
    png = svg.with_suffix(".png")
    width, height = _view_box(svg)

    if tool.name == "rsvg-convert":
        subprocess.run([tool.path, "-o", str(png), str(svg)], check=True)
    else:
        # Browsers screenshot a page, not a file, so the SVG is framed at its own size.
        wrapper = svg.with_suffix(".html")
        wrapper.write_text(
            "<style>html,body{margin:0;padding:0;background:transparent}"
            f"img{{display:block;width:{width}px;height:{height}px}}</style>\n"
            f'<img src="{svg.name}">\n',
            encoding="utf-8",
        )
        flag = "--headless" if tool.name == "firefox" else "--headless=new"
        subprocess.run(
            [tool.path, flag, "--screenshot", str(png),
             f"--window-size={round(width)},{round(height) + 1}", f"file://{wrapper}"],
            check=False,
            capture_output=True,
        )
        wrapper.unlink(missing_ok=True)

    print(f"  {png.relative_to(REPO_ROOT)}" if png.exists() else f"  {png.name} FAILED")


def _view_box(svg: Path) -> tuple[float, float]:
    import re

    match = re.search(r'viewBox="0 0 ([0-9.]+) ([0-9.]+)"', svg.read_text(encoding="utf-8"))
    if match is None:
        raise SystemExit(f"{svg.name}: no viewBox to size the screenshot with")
    return float(match.group(1)), float(match.group(2))


if __name__ == "__main__":
    sys.exit(main())
