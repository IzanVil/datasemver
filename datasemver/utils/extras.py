"""What to tell someone who asked for a feature their installation does not carry.

The advice depends on what they are holding. A `pip install` is the answer for a Python
installation and no answer at all inside the standalone binary, where there is no environment
to add anything to -- the reader would have to go and get a Python install first, and the
message may as well say so.
"""

from __future__ import annotations

import sys


def is_frozen() -> bool:
    """Whether this is running from the standalone executable rather than an installation.

    `sys.frozen` is what PyInstaller sets on the interpreter it bundles. Read at call time
    rather than at import, so the answer is the truth about this process.
    """
    return bool(getattr(sys, "frozen", False))


def install_hint(extra: str, capability: str) -> str:
    """One line naming what is missing and the one thing the reader can do about it."""
    if is_frozen():
        return (
            f"{capability} is not part of the standalone executable. It needs a Python "
            f'installation: pip install "datasemver[{extra}]"'
        )
    return f'{capability} needs the {extra} extra: pip install "datasemver[{extra}]"'
