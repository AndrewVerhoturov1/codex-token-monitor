"""Optional text-review helper for docs/zchat_live_calculator.

This file is not auto-run by the package. It performs local static checks only
when a reviewer chooses to run it from the repository root.
"""

from pathlib import Path

BASE = Path("docs") / "zchat_live_calculator"
EXPECTED = [
    BASE / "index.html",
    BASE / "styles.css",
    BASE / "app.js",
    BASE / "README.md",
    BASE / "context_readback.md",
    BASE / "change_summary.md",
    BASE / "verification" / "check_result.py",
]

BAD_JS = [
    "ev" + "al(",
    "new " + "Function",
    "fe" + "tch(",
    "XML" + "HttpRequest",
    "import" + "(",
]
BAD_CSS = [
    "@im" + "port",
    "url(http" + "://",
    "url(https" + "://",
]


def fail(message):
    raise SystemExit(f"CHECK_FAILED: {message}")


def main():
    missing = [str(path) for path in EXPECTED if not path.exists()]
    if missing:
        fail("missing expected files: " + ", ".join(missing))

    actual = sorted(path for path in BASE.rglob("*") if path.is_file())
    expected = sorted(EXPECTED)
    if actual != expected:
        extra = sorted(set(actual) - set(expected))
        absent = sorted(set(expected) - set(actual))
        fail(f"unexpected file set; extra={extra}; absent={absent}")

    html = (BASE / "index.html").read_text(encoding="utf-8")
    css = (BASE / "styles.css").read_text(encoding="utf-8")
    js = (BASE / "app.js").read_text(encoding="utf-8")

    if 'src="app.js"' not in html or 'href="styles.css"' not in html:
        fail("index.html must reference only local app.js and styles.css")

    for token in BAD_JS:
        if token in js:
            fail("blocked JavaScript token present: " + token)

    lower_css = css.lower()
    for token in BAD_CSS:
        if token in lower_css:
            fail("blocked CSS token present: " + token)

    for token in ["+", "-", "*", "/"]:
        if token not in js:
            fail("missing arithmetic operator support token: " + token)

    if "keydown" not in js:
        fail("keyboard handler not found")

    print("CHECK_OK: static calculator files are present and pass text checks")


if __name__ == "__main__":
    main()
