"""
MyStudyHub Key Bypass — v13 TWO-PHASE (Playwright arolinks → bcsakhi)
=====================================================================
Key insight from v12 failure:
  - v12 skipped arolinks.com entirely → no csrfToken in browser
  - When btn7 clicked → browser went to arolinks WITHOUT cookie → failed

Fix:
  Phase 1: Playwright visits arolinks.com/ALIAS (5-8s, just to get CF cookies)
           → CF sets csrfToken + AppSession in browser context
           → Redirect to bcsakhi not required — we just need the cookies!

  Phase 2: Navigate SAME browser (same context = same cookies) to bcsakhi.in
           → intnt_io injected → wait for #btn7 → click
           → Browser goes to arolinks.com WITH csrfToken → /links/go intercept → TOKEN!
"""

import asyncio
import argparse
import json
import re
import sys
import time
import warnings

import urllib3
warnings.filterwarnings("ignore")
urllib3.disable_warnings()

import requests

try:
    from playwright.async_api import async_playwright
except ImportError:
    sys.exit("Run: pip install playwright && playwright install chromium")

try:
    from playwright_stealth import stealth_async
    STEALTH = True
except ImportError:
    STEALTH = False

try:
    from colorama import Fore, Style, init
    init(autoreset=True)
    G=Fore.GREEN; R=Fore.RED; Y=Fore.YELLOW; C=Fore.CYAN; B=Style.BRIGHT; X=Style.RESET_ALL
except ImportError:
    G=R=Y=C=B=X=""

# ── Config ────────────────────────────────────────────────────────────────────
BASE     = "https://web.mystudyhub.shop"
GEN      = f"{BASE}/api/keys/generate"
UA       = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")
HDRS     = {"User-Agent": UA, "Accept": "text/html,*/*", "Accept-Language": "en-US,en;q=0.9"}
INTNT_N  = "intnt_io"
INTNT_V  = "insurance,online_colleges,study_abroad,finance,loan"
TOKEN_RE = re.compile(r"mystudyhub\.shop/token/verify/([A-Z0-9]{8,})")
ALIAS_RE = re.compile(r"arolinks\.com/([A-Za-z0-9]+)$")


def log(msg, t="i"):
    ic = {"i": C+"[*]", "o": G+"[+]", "e": R+"[-]", "w": Y+"[!]"}.get(t, "[*]")
    print(f"{ic} {msg}{X}", flush=True)


def get_arolinks_url() -> str:
    try:
        r = requests.get(GEN, headers=HDRS, allow_redirects=False, timeout=15, verify=False)
        url = r.headers.get("Location", "")
        if url:
            log(f"AroLinks URL: {url}", "o")
            return url
    except Exception as e:
        log(f"HTTP error: {e}", "e")
    return ""


_pw = None
_browser = None
_browser_lock = None

async def get_browser(headless: bool = True):
    global _pw, _browser, _browser_lock
    if _browser_lock is None:
        _browser_lock = asyncio.Lock()
    async with _browser_lock:
        if _browser is None:
            _pw = await async_playwright().start()
            _browser = await _pw.chromium.launch(
                headless=headless,
                args=[
                    "--no-sandbox",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--window-size=1280,800",
                    "--disable-setuid-sandbox",
                    "--disable-extensions",
                ]
            )
            log("Global Chromium instance started", "o")
    return _browser


async def bypass(arolinks_url: str, headless: bool = True, use_chrome: bool = False):
    result = {"token": None, "verify_url": None}

    # Extract alias → construct direct bcsakhi URL
    alias_m    = ALIAS_RE.search(arolinks_url)
    alias      = alias_m.group(1) if alias_m else ""
    bcsakhi_url = (f"https://bcsakhi.in/scholorshipseduction/?eductescholrship={alias}"
                   if alias else None)

    log(f"Alias: {alias}")
    log(f"bcsakhi direct URL: {bcsakhi_url}", "o")

    browser = await get_browser(headless=headless)

    ctx = await browser.new_context(
        user_agent=UA,
        ignore_https_errors=True,
        viewport={"width": 1280, "height": 800},
        locale="en-US",
    )

    try:
        await ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
            "Object.defineProperty(navigator,'languages',{get:()=>['en-US','en']});"
            "Object.defineProperty(navigator,'plugins',{get:()=>[1,2,3,4,5]});"
            "Object.defineProperty(navigator,'platform',{get:()=>'Win32'});"
            "window.chrome={runtime:{}};"
        )

        page = await ctx.new_page()

        if STEALTH:
            await stealth_async(page)
            log("Stealth applied", "o")

        # ── Response + navigation interceptors ───────────────────────────────
        async def on_response(resp):
            if "links/go" in resp.url and not result["token"]:
                try:
                    body = await resp.text()
                    log(f"[links/go] {resp.status}: {body[:200]}", "o")
                    data = json.loads(body)
                    if data.get("status") == "success" and data.get("url"):
                        tok = TOKEN_RE.search(data["url"])
                        if tok:
                            result["token"]      = tok.group(1)
                            result["verify_url"] = data["url"]
                            log(f"TOKEN: {tok.group(1)}", "o")
                except Exception:
                    pass

        async def on_nav(frame):
            tok = TOKEN_RE.search(frame.url)
            if tok and not result["token"]:
                result["token"]      = tok.group(1)
                result["verify_url"] = frame.url
                log(f"Token via nav: {tok.group(1)}", "o")

        page.on("response", on_response)
        page.on("framenavigated", on_nav)

        # ══════════════════════════════════════════════════════════════════════
        # PHASE 1: Visit arolinks.com to get CF cookies (csrfToken + AppSession)
        #          We do NOT wait for bcsakhi redirect — just 8s for cookies!
        # ══════════════════════════════════════════════════════════════════════
        log(f"Phase 1 — Visit arolinks for CF cookies: {arolinks_url}")
        try:
            await page.goto(arolinks_url, wait_until="domcontentloaded", timeout=15000)
        except Exception:
            pass  # timeout ok — we just need the cookies

        await page.wait_for_timeout(8000)  # wait 8s for CF to set cookies
        log(f"  Phase 1 done — URL: {page.url[:70]}")

        # Check if already on bcsakhi (lucky redirect!)
        if "bcsakhi" in page.url:
            log("  Redirected to bcsakhi naturally!", "o")
        elif result["token"]:
            log("  Token already intercepted!", "o")
            return result

        # Log arolinks cookies
        arolinks_cookies = await ctx.cookies("https://arolinks.com")
        log(f"  arolinks cookies in context: {[c['name'] for c in arolinks_cookies]}", "o")

        # ══════════════════════════════════════════════════════════════════════
        # PHASE 2: Navigate to bcsakhi.in directly (same context = same cookies!)
        #          The arolinks CF cookies are now in the browser context.
        # ══════════════════════════════════════════════════════════════════════
        if bcsakhi_url and "bcsakhi" not in page.url:
            log(f"Phase 2 — Navigate directly to bcsakhi: {bcsakhi_url[:70]}")
            try:
                await page.goto(bcsakhi_url, wait_until="domcontentloaded", timeout=30000)
            except Exception as e:
                log(f"  bcsakhi nav timeout (ok): {e}", "w")
            await page.wait_for_timeout(2000)
            log(f"  bcsakhi URL: {page.url[:70]}")

        # ── Inject intnt_io to skip ad countdown ─────────────────────────────
        if "bcsakhi" in page.url:
            log("Injecting intnt_io (skip ad timer)")
            await ctx.add_cookies([{
                "name": INTNT_N, "value": INTNT_V,
                "domain": ".bcsakhi.in", "path": "/", "sameSite": "Lax",
            }])
            log("  intnt_io injected ✓", "o")
        else:
            log(f"  Not on bcsakhi: {page.url[:60]}", "w")

        if result["token"]:
            return result

        # ── Wait for #btn7 (max 60s) ─────────────────────────────────────────
        log("Waiting for #btn7 (max 60s)…")
        btn7_found = False
        for i in range(60):
            if result["token"]: break
            try:
                btn = page.locator("#btn7")
                if await btn.count() > 0 and await btn.is_visible():
                    log("  #btn7 visible!", "o")
                    btn7_found = True
                    break
            except Exception:
                pass
            if i % 10 == 0:
                log(f"  [{i}s] {page.url[:60]}")
            await page.wait_for_timeout(1000)

        if result["token"]:
            return result

        # ── Click #btn7 ───────────────────────────────────────────────────────
        if btn7_found:
            log("Clicking #btn7…")
            try:
                await page.evaluate("document.getElementById('btn7').click()")
                log("  JS click OK", "o")
            except Exception:
                log("  JS click failed — Direct click", "w")
                try:
                    await page.locator("#btn7").click()
                    log("  Direct click OK", "o")
                except Exception as e:
                    log(f"  Direct click failed: {e}", "e")
        else:
            log("  Never found #btn7 — JS /readmore fallback", "w")
            try:
                await page.evaluate("window.location.href='/readmore/'")
            except Exception:
                pass

        # ── Wait for /links/go response → token ──────────────────────────────
        log("Waiting for token from /links/go…")
        for i in range(15):
            if result["token"]: break
            cur = page.url
            tok = TOKEN_RE.search(cur)
            if tok:
                result["token"]      = tok.group(1)
                result["verify_url"] = cur
                break
            try:
                content = await page.content()
                tok = TOKEN_RE.search(content)
                if tok:
                    result["token"] = tok.group(1)
                    break
                for href in await page.eval_on_selector_all("a[href]", "e=>e.map(x=>x.href)"):
                    tok = TOKEN_RE.search(href)
                    if tok:
                        result["token"] = tok.group(1)
                        break
            except Exception:
                pass
            if i % 5 == 0:
                log(f"  [{i}s] {cur[:70]}")
            await page.wait_for_timeout(1000)

        # ── VPS Alternative Route: Bypass /links/go block ────────────────────
        if not result["token"]:
            log("Normal route failed (VPS IP block). Trying VPS Alternative Route...", "w")
            log(f"Navigating directly to: {arolinks_url}")
            try:
                await page.goto(arolinks_url, wait_until="domcontentloaded", timeout=20000)
                log("Waiting 10s for 'Get Link' button to become active...")
                await page.wait_for_timeout(10500)
                
                # Look for the get link button
                get_link = page.locator("a:has-text('Get Link'), a:has-text('GET LINK')").first
                if await get_link.count() > 0 and await get_link.is_visible():
                    log("Found Get Link button! Clicking...", "o")
                    try:
                        await get_link.click()
                    except Exception:
                        await page.evaluate("arguments[0].click()", await get_link.element_handle())
                        
                    await page.wait_for_timeout(5000)
                    
                    # Search all pages in context (handles new tabs/popups)
                    for p in ctx.pages:
                        if result["token"]: break
                        try:
                            tok = TOKEN_RE.search(p.url)
                            if tok:
                                result["token"] = tok.group(1)
                                result["verify_url"] = p.url
                                break
                            
                            content = await p.content()
                            tok = TOKEN_RE.search(content)
                            if tok:
                                result["token"] = tok.group(1)
                                break
                                
                            for href in await p.eval_on_selector_all("a[href]", "e=>e.map(x=>x.href)"):
                                tok2 = TOKEN_RE.search(href)
                                if tok2:
                                    result["token"] = tok2.group(1)
                                    break
                        except Exception:
                            pass
                else:
                    log("Get Link button not found on alternative route.", "e")
                    
            except Exception as e:
                log(f"VPS Alternative Route failed: {e}", "e")

    finally:
        await ctx.close()

    return result


def main():
    parser = argparse.ArgumentParser(description="MyStudyHub Bypass v13")
    parser.add_argument("--visible", action="store_true")
    parser.add_argument("--chrome",  action="store_true")
    args = parser.parse_args()

    print(f"\n{C}{B}[MyStudyHub Bypass v13 — Two-Phase Flow]{X}\n")
    log(f"stealth: {'available' if STEALTH else 'not installed (non-critical)'}", "o" if STEALTH else "w")

    arolinks_url = get_arolinks_url()
    if not arolinks_url:
        print(f"{R}Failed to get arolinks URL{X}")
        sys.exit(1)

    result = asyncio.run(bypass(arolinks_url, headless=not args.visible, use_chrome=args.chrome))
    token  = result.get("token")

    if token:
        verify = result.get("verify_url") or f"{BASE}/token/verify/{token}"
        print(f"\n{C}{'═'*60}{X}")
        print(f"  {B}Token :{X} {G}{B}{token}{X}")
        print(f"  {B}URL   :{X} {C}{verify}{X}")
        print(f"{C}{'═'*60}{X}")
        print(f"\n{G}{B}YOUR KEY: {token}{X}\n")
    else:
        print(f"\n{R}Bypass failed.{X}")
        sys.exit(1)


if __name__ == "__main__":
    main()
