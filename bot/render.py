"""HTML -> image. One shared headless Chromium; each render gets a fresh page."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.async_api import Browser, Playwright, async_playwright

from . import fonts
from .style import Style

log = logging.getLogger(__name__)

WIDTH, HEIGHT = 1280, 720
FONT_HOST = "http://assets.local/"  # virtual origin, served from disk by a route handler


def clip(text: str, n: int) -> str:
    """Cut at a word boundary and add an ellipsis (used for synopsis text)."""
    text = (text or "").strip()
    if len(text) <= n:
        return text
    return text[:n].rsplit(" ", 1)[0].rstrip(",.;:-– ") + "…"


class Renderer:
    def __init__(self, templates_dir: Path, assets_dir: Path, concurrency: int = 2):
        self.env = Environment(
            loader=FileSystemLoader(str(templates_dir)),
            autoescape=select_autoescape(["html"]),
        )
        self.env.filters["clip"] = clip
        self.assets_dir = assets_dir
        self.special_assets = {n: (assets_dir / "special" / f"{n}.png").is_file() for n in ("boxes", "watermark", "credit")}
        self._sem = asyncio.Semaphore(concurrency)
        self._pw: Playwright | None = None
        self._browser: Browser | None = None
        self._start_lock = asyncio.Lock()

    async def _ensure_browser(self) -> Browser:
        async with self._start_lock:
            if self._browser and self._browser.is_connected():
                return self._browser
            if self._pw is None:
                self._pw = await async_playwright().start()
            log.info("Launching Chromium")
            self._browser = await self._pw.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
            return self._browser

    async def close(self) -> None:
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()

    async def _serve_assets(self, route) -> None:
        rel = route.request.url.removeprefix(FONT_HOST)
        path = (self.assets_dir / rel).resolve()
        if self.assets_dir.resolve() in path.parents and path.is_file():
            await route.fulfill(path=str(path))
        else:
            await route.abort()

    def html(self, template_file: str, anime: dict, variant: str = "", style: Style | None = None) -> str:
        style = style or Style()
        anime = {"art": anime.get("cover"), "art_wide": False, **anime}      # templates always have `a.art`
        if "season_line" not in anime:
            anime["season_line"] = (f"{anime.get('season') or ''} {anime.get('year') or ''}".strip()) or anime.get("format", "")
        if "episodes_label" not in anime:
            anime["episodes_label"] = f"{anime['episodes']} episodes" if anime.get("episodes") else ""
        font = fonts.get(style.font)
        brand, groups = None, []
        if style.brand_text or style.logo:
            brand = {"text": style.brand_text, "logo": style.logo, "pos": style.position, "logo_pos": style.logo_position}
            if style.logo and style.brand_text and style.logo_position == style.position:
                groups = [{"pos": style.position, "logo": style.logo, "text": style.brand_text}]   # same corner: stack together
            else:
                if style.logo:
                    groups.append({"pos": style.logo_position, "logo": style.logo, "text": ""})
                if style.brand_text:
                    groups.append({"pos": style.position, "logo": None, "text": style.brand_text})
        return self.env.get_template(template_file).render(
            a=anime, variant=variant, brand=brand, brand_groups=groups, font_host=FONT_HOST, asset_host=FONT_HOST,
            sp_assets=self.special_assets, sp_defaults=style.special_defaults, wm_opacity=style.wm_opacity, boxes_opacity=style.boxes_opacity,
            font=font, font_css=fonts.font_css(font, FONT_HOST), fscale=font.title_scale,
            scheme=style.scheme, char=style.char,
        )

    async def render(self, template_file: str, anime: dict, variant: str = "", fmt: str = "jpeg",
                     style: Style | None = None, scale: float = 1.0) -> bytes:
        """scale 1 = 1280x720, 2 = 2560x1440 (sharper text and shapes), 0.5 = small previews."""
        html = self.html(template_file, anime, variant, style)
        async with self._sem:
            browser = await self._ensure_browser()
            ctx = await browser.new_context(viewport={"width": WIDTH, "height": HEIGHT}, device_scale_factor=scale)
            try:
                page = await ctx.new_page()
                await page.route(f"{FONT_HOST}**", self._serve_assets)
                await page.set_content(html, wait_until="load", timeout=20_000 if scale <= 1 else 40_000)
                await page.evaluate("document.fonts.ready")
                await page.evaluate("window.__ready")  # brand overlay measured, nav shifted
                opts = {"type": "png"} if fmt == "png" else {"type": "jpeg", "quality": 92}
                return await page.screenshot(**opts)
            finally:
                await ctx.close()

    async def inspect(self, template_file: str, anime: dict, js: str, variant: str = "", style: Style | None = None):
        """Render the page and return the result of a JavaScript expression (used by tests and debugging)."""
        html = self.html(template_file, anime, variant, style)
        async with self._sem:
            browser = await self._ensure_browser()
            ctx = await browser.new_context(viewport={"width": WIDTH, "height": HEIGHT})
            try:
                page = await ctx.new_page()
                await page.route(f"{FONT_HOST}**", self._serve_assets)
                await page.set_content(html, wait_until="load", timeout=20_000)
                await page.evaluate("document.fonts.ready")
                await page.evaluate("window.__ready")
                return await page.evaluate(js)
            finally:
                await ctx.close()
