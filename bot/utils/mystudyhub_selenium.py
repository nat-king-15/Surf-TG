"""
MyStudyHub Key Bypass — Selenium Version (mirrors mystudyhub_bypass.py logic)
==============================================================================
Same Two-Phase flow as Playwright version:

  Phase 1: Visit arolinks.com/ALIAS (8s wait for CF cookies — csrfToken + AppSession)
  Phase 2: Navigate SAME browser to bcsakhi.in (cookies already in session)
           → inject intnt_io cookie → wait for #btn7 → JS click → token!

Usage:
  python mystudyhub_selenium.py
  python mystudyhub_selenium.py --visible
"""

import argparse
import json
import os
import re
import sys
import time
import warnings

import urllib3
warnings.filterwarnings("ignore")
urllib3.disable_warnings()

import requests

try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
except ImportError:
    sys.exit("Run: pip install selenium")

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


def _make_driver(headless: bool) -> webdriver.Chrome:
    opts = Options()
    opts.add_argument(f"user-agent={UA}")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1280,800")
    opts.add_argument("--disable-setuid-sandbox")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    opts.add_argument("--lang=en-US")
    opts.add_argument("--disable-features=TranslateUI")
    opts.add_argument("--js-flags=--max-old-space-size=512")  # JS heap limit
    if headless:
        opts.add_argument("--headless=new")

    # Docker / Linux pe system chrome binary dhundo
    import shutil
    chrome_bin = (
        os.environ.get("CHROME_BIN")              # env override
        or shutil.which("google-chrome")          # google-chrome-stable (apt)
        or shutil.which("google-chrome-stable")   # alternate name
        or shutil.which("chromium-browser")       # fallback chromium
        or shutil.which("chromium")               # alternate chromium
    )
    chromedriver_bin = (
        os.environ.get("CHROMEDRIVER_BIN")
        or shutil.which("chromedriver")
    )

    if chrome_bin:
        opts.binary_location = chrome_bin
        log(f"Using chrome: {chrome_bin}", "o")

    if chromedriver_bin:
        service = Service(chromedriver_bin)
        log(f"Using chromedriver: {chromedriver_bin}", "o")
    else:
        service = Service()  # selenium-manager auto-manage karega

    driver = webdriver.Chrome(service=service, options=opts)

    # Hide webdriver flag via JS
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": (
        "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
        "Object.defineProperty(navigator,'languages',{get:()=>['en-US','en']});"
        "Object.defineProperty(navigator,'plugins',{get:()=>[1,2,3,4,5]});"
        "Object.defineProperty(navigator,'platform',{get:()=>'Win32'});"
        "window.chrome={runtime:{}};"
    )})
    return driver


def _check_token_in_url(url: str):
    tok = TOKEN_RE.search(url)
    return tok.group(1) if tok else None


def _check_token_in_page(driver: webdriver.Chrome):
    """Check current URL, page source, and all hrefs for token."""
    # 1. URL
    tok = _check_token_in_url(driver.current_url)
    if tok:
        return tok, driver.current_url

    # 2. Page source
    try:
        src = driver.page_source
        tok = TOKEN_RE.search(src)
        if tok:
            return tok.group(1), None
    except Exception:
        pass

    # 3. All <a href> links
    try:
        for el in driver.find_elements(By.CSS_SELECTOR, "a[href]"):
            href = el.get_attribute("href") or ""
            tok = TOKEN_RE.search(href)
            if tok:
                return tok.group(1), href
    except Exception:
        pass

    return None, None


def bypass(arolinks_url: str, headless: bool = True):
    result = {"token": None, "verify_url": None}

    # Extract alias → direct bcsakhi URL
    alias_m    = ALIAS_RE.search(arolinks_url)
    alias      = alias_m.group(1) if alias_m else ""
    bcsakhi_url = (f"https://bcsakhi.in/scholorshipseduction/?eductescholrship={alias}"
                   if alias else None)

    log(f"Alias: {alias}")
    log(f"bcsakhi direct URL: {bcsakhi_url}", "o")

    driver = _make_driver(headless)

    try:
        # ══════════════════════════════════════════════════════════════════════
        # PHASE 1: Visit arolinks.com to get CF cookies (csrfToken + AppSession)
        # ══════════════════════════════════════════════════════════════════════
        log(f"Phase 1 — Visit arolinks for CF cookies: {arolinks_url}")
        try:
            driver.get(arolinks_url)
        except Exception:
            pass  # timeout ok — we just need the cookies

        time.sleep(8)  # wait 8s for CF to set cookies
        log(f"  Phase 1 done — URL: {driver.current_url[:70]}")

        # Check lucky redirect to bcsakhi
        if "bcsakhi" in driver.current_url:
            log("  Redirected to bcsakhi naturally!", "o")
        else:
            # Check if token already in URL (rare)
            tok = _check_token_in_url(driver.current_url)
            if tok:
                result["token"]      = tok
                result["verify_url"] = driver.current_url
                log(f"  Token already intercepted! {tok}", "o")
                return result

        # Log CF cookies
        aro_cookies = [c["name"] for c in driver.get_cookies()
                       if "arolinks" in (c.get("domain") or "")]
        log(f"  arolinks cookies in context: {aro_cookies}", "o")

        # ══════════════════════════════════════════════════════════════════════
        # PHASE 2: Navigate to bcsakhi.in (same browser = same cookies!)
        # ══════════════════════════════════════════════════════════════════════
        if bcsakhi_url and "bcsakhi" not in driver.current_url:
            log(f"Phase 2 — Navigate directly to bcsakhi: {bcsakhi_url[:70]}")
            try:
                driver.get(bcsakhi_url)
            except Exception as e:
                log(f"  bcsakhi nav timeout (ok): {e}", "w")
            time.sleep(2)
            log(f"  bcsakhi URL: {driver.current_url[:70]}")

        # ── Inject intnt_io cookie to skip ad countdown ──────────────────
        if "bcsakhi" in driver.current_url:
            log("Injecting intnt_io (skip ad timer)")
            driver.add_cookie({
                "name":   INTNT_N,
                "value":  INTNT_V,
                "domain": ".bcsakhi.in",
                "path":   "/",
            })
            # NOTE: no refresh — cookie sets on next navigation, avoids OOM crash
            log("  intnt_io injected ✓", "o")
        else:
            log(f"  Not on bcsakhi: {driver.current_url[:60]}", "w")

        # Quick token check after inject
        tok, verify = _check_token_in_page(driver)
        if tok:
            result["token"]      = tok
            result["verify_url"] = verify or driver.current_url
            return result

        # ── Wait for #btn7 (max 60s) ──────────────────────────────────────────
        log("Waiting for #btn7 (max 60s)…")
        btn7_el   = None
        btn7_found = False
        for i in range(60):
            # Check if token already appeared
            tok, verify = _check_token_in_page(driver)
            if tok:
                result["token"]      = tok
                result["verify_url"] = verify or driver.current_url
                log(f"Token via page scan: {tok}", "o")
                return result
            try:
                el = driver.find_element(By.CSS_SELECTOR, "#btn7")
                if el.is_displayed():
                    log("  #btn7 visible!", "o")
                    btn7_el    = el
                    btn7_found = True
                    break
            except Exception:
                pass
            if i % 10 == 0:
                log(f"  [{i}s] {driver.current_url[:60]}")
            time.sleep(1)

        # ── Click #btn7 ───────────────────────────────────────────────────────
        if btn7_found and btn7_el:
            log("Clicking #btn7…")
            try:
                driver.execute_script("document.getElementById('btn7').click()")
                log("  JS click OK", "o")
            except Exception:
                log("  JS click failed — Direct click", "w")
                try:
                    btn7_el.click()
                    log("  Direct click OK", "o")
                except Exception as e:
                    log(f"  Direct click failed: {e}", "e")
        else:
            log("  Never found #btn7 — JS /readmore fallback", "w")
            try:
                driver.execute_script("window.location.href='/readmore/'")
            except Exception:
                pass

        # ── Wait for token (max 40s) ──────────────────────────────────────────
        log("Waiting for token from /links/go…")
        for i in range(40):
            tok, verify = _check_token_in_page(driver)
            if tok:
                result["token"]      = tok
                result["verify_url"] = verify or driver.current_url
                log(f"TOKEN: {tok}", "o")
                break
            if i % 5 == 0:
                log(f"  [{i}s] {driver.current_url[:70]}")
            time.sleep(1)

    finally:
        driver.quit()

    return result


def main():
    parser = argparse.ArgumentParser(description="MyStudyHub Bypass — Selenium")
    parser.add_argument("--visible", action="store_true", help="Show browser window")
    args = parser.parse_args()

    print(f"\n{C}{B}[MyStudyHub Bypass — Selenium Two-Phase Flow]{X}\n")

    arolinks_url = get_arolinks_url()
    if not arolinks_url:
        print(f"{R}Failed to get arolinks URL{X}")
        sys.exit(1)

    result = bypass(arolinks_url, headless=not args.visible)
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
