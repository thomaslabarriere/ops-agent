"""The confirmation portal the agent posts to, behind one common interface.

The "post a public confirmation" action has no API (see `world.NoAPIEndpoint`),
so it is carried out in a browser. This module gives that a real seam:

- `MockPortal` -- the offline default: an in-memory store, no browser, no
  network. It still records only what `browser_post` actually wrote, so the
  harness's DOM-style check is genuine even offline.
- `RealBrowserPortal` -- drives a real headless Chromium page loaded from
  `confirmation.html` over `file://` (zero network). Posting fills a textarea
  and clicks a button; reading returns the page's live DOM text.

Both satisfy `ConfirmationPortal`, so `Tools` is oblivious to which is wired in.
The verdict for the post action is READ BACK from `current_text()` -- the DOM in
real mode -- never from what the agent claims, so an agent that reports a post
it never made is caught (its confirmation is simply absent from the portal).

Playwright is imported lazily, only inside the real path, so the offline core
never needs it installed and `import opsagent.browser` stays cheap.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from playwright.sync_api import Browser, Page

# The toy portal page, loaded over file:// -- no network is ever touched.
CONFIRMATION_HTML = Path(__file__).with_name("confirmation.html")
CONFIRMATION_URL = CONFIRMATION_HTML.as_uri()


class ConfirmationPortal(Protocol):
    """The browser-backed action surface for the no-API confirmation post."""

    def reset(self) -> None:
        """Return the portal to an empty state before a scenario run."""
        ...

    def post(self, text: str) -> None:
        """Publish `text` as the current public confirmation."""
        ...

    def current_text(self) -> str:
        """The confirmation the portal currently holds (empty if none)."""
        ...


class MockPortal:
    """Offline default: an in-memory portal. Holds only what was actually
    posted, so the harness's confirmation check means the same thing it does
    against a real DOM -- a claimed-but-unposted confirmation stays absent."""

    def __init__(self) -> None:
        self._text = ""

    def reset(self) -> None:
        self._text = ""

    def post(self, text: str) -> None:
        if text:
            self._text = text

    def current_text(self) -> str:
        return self._text


class RealBrowserPortal:
    """Drives a real headless page (confirmation.html over file://). Posting
    operates the DOM (fill + click); reading returns the live DOM text."""

    def __init__(self, page: Page) -> None:
        self._page = page
        self.reset()

    def reset(self) -> None:
        self._page.goto(CONFIRMATION_URL)
        self._page.wait_for_selector("#confirmation")
        # Clear any draft left over from a previous scenario on the shared page.
        self._page.fill("#draft", "")

    def post(self, text: str) -> None:
        if not text:
            return
        self._page.fill("#draft", text)
        self._page.click("#post")
        # Wait until the published confirmation actually reflects the post, so
        # current_text() reads a settled DOM (the effect, not the intent).
        self._page.wait_for_function(
            "t => document.getElementById('confirmation').textContent === t",
            arg=text,
        )

    def current_text(self) -> str:
        el = self._page.query_selector("#confirmation")
        if el is None or el.get_attribute("data-empty") == "true":
            return ""
        return el.inner_text()


@contextmanager
def confirmation_session(real: bool) -> Iterator[Callable[[], ConfirmationPortal]]:
    """Yield a factory that returns a ready-to-use portal per scenario.

    Offline (`real=False`): a fresh `MockPortal` each call, no browser.
    Real (`real=True`): launch Chromium once, reuse one page, and hand back the
    same `RealBrowserPortal` reset to an empty portal for each scenario.
    """
    if not real:
        yield MockPortal
        return

    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser: Browser = pw.chromium.launch()
        page = browser.new_page()
        portal = RealBrowserPortal(page)

        # The same page is reused across scenarios; run_scenario resets it
        # (fresh, empty portal) at the start of each run.
        def factory() -> ConfirmationPortal:
            return portal

        try:
            yield factory
        finally:
            browser.close()
