"""
Paycom bC Census Export — Botasaurus-Driver Automation Script
=============================================================
Generated from browser-scout reconnaissance session 533fd2b4ddf0.
Uses botasaurus-driver for anti-detection and stealth browsing.

Workflow: Login → 2FA (SMS via Twilio) → Generate Report → Download CSV → Logout

Usage:
    python paycom_census_export.py

Environment variables (or .env file):
    PAYCOM_CLIENT_CODE  - Paycom client code
    PAYCOM_USERNAME     - Paycom username
    PAYCOM_PASSWORD     - Paycom password
    TWILIO_ACCOUNT_SID  - Twilio account SID
    TWILIO_AUTH_TOKEN   - Twilio auth token
    TWILIO_PHONE_NUMBER - Phone number receiving 2FA SMS (digits only)
"""

import os
import random
import re
import shutil
import time
from pathlib import Path

import requests
from botasaurus_driver import Driver
from dotenv import load_dotenv

# ── Configuration ────────────────────────────────────────────────────────────

load_dotenv()

CLIENT_CODE = os.environ["PAYCOM_CLIENT_CODE"]
USERNAME = os.environ["PAYCOM_USERNAME"]
PASSWORD = os.environ["PAYCOM_PASSWORD"]

TWILIO_SID = os.environ["TWILIO_ACCOUNT_SID"]
TWILIO_TOKEN = os.environ["TWILIO_AUTH_TOKEN"]
TWILIO_PHONE = os.environ["TWILIO_PHONE_NUMBER"]

# Report configuration
REPORT_URL = "https://www.paycomonline.net/v4/cl/enh-srw-reportwriter.php?rpt_id=746&sec_id=1"
DOWNLOAD_DEST = Path(
    r"\\anf-fs01\EDI\sFTP\Clients\CenturyCareManagement\CensusAutomation\Archive"
)
DOWNLOAD_DIR = Path("./downloads").resolve()

# Twilio 2FA polling
TWILIO_POLL_INTERVAL_S = 3
TWILIO_POLL_TIMEOUT_S = 90

# Report generation timeout
REPORT_GEN_TIMEOUT_S = 60


# ── Human-like timing ────────────────────────────────────────────────────────


def human_pause(min_s: float = 0.8, max_s: float = 2.0) -> None:
    """Pause for a randomized duration to mimic human pacing."""
    time.sleep(random.uniform(min_s, max_s))


def human_pause_long(min_s: float = 2.0, max_s: float = 4.0) -> None:
    """Longer pause for page transitions and thinking time."""
    time.sleep(random.uniform(min_s, max_s))


# ── Helpers ──────────────────────────────────────────────────────────────────


def wait_for_url(driver: Driver, pattern: str, timeout: float = 30) -> None:
    """Wait until current_url contains the given substring."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if pattern in driver.current_url:
            return
        time.sleep(0.5)
    raise TimeoutError(
        f"URL did not contain '{pattern}' within {timeout}s. "
        f"Current: {driver.current_url}"
    )


def wait_for_element_hidden(driver: Driver, selector: str, timeout: float = 60) -> None:
    """Wait until an element is no longer visible (removed or hidden)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        visible = driver.run_js(
            f"const el = document.querySelector({repr(selector)}); "
            f"return el ? (el.offsetParent !== null || getComputedStyle(el).display !== 'none') : false"
        )
        if not visible:
            return
        time.sleep(1)
    raise TimeoutError(
        f"Element '{selector}' still visible after {timeout}s"
    )


def wait_for_download(directory: Path, timeout: float = 60) -> Path:
    """Wait for a new file to appear in the download directory."""
    existing = set(directory.iterdir()) if directory.exists() else set()
    deadline = time.time() + timeout
    while time.time() < deadline:
        current = set(directory.iterdir())
        new_files = current - existing
        # Filter out partial downloads (.crdownload, .tmp)
        complete = [f for f in new_files if not f.suffix in (".crdownload", ".tmp", ".part")]
        if complete:
            return complete[0]
        time.sleep(1)
    raise TimeoutError(f"No new file appeared in {directory} within {timeout}s")


def fetch_2fa_code_from_twilio() -> str:
    """Poll Twilio Messages API for the most recent Paycom 2FA code.

    Paycom sends SMS in the format: "XXXXXX is your Paycom authentication code"
    We poll until a message matching that pattern arrives or we timeout.
    """
    url = (
        f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_SID}"
        f"/Messages.json?To=%2B1{TWILIO_PHONE}&PageSize=1"
    )
    pattern = re.compile(r"(\d{6}) is your Paycom authentication code")
    deadline = time.time() + TWILIO_POLL_TIMEOUT_S

    # Record the timestamp of the newest message before we start,
    # so we only match messages that arrive *after* we requested the code.
    baseline_response = requests.get(url, auth=(TWILIO_SID, TWILIO_TOKEN), timeout=10)
    baseline_response.raise_for_status()
    baseline_msgs = baseline_response.json().get("messages", [])
    baseline_sid = baseline_msgs[0]["sid"] if baseline_msgs else None

    while time.time() < deadline:
        time.sleep(TWILIO_POLL_INTERVAL_S)
        resp = requests.get(url, auth=(TWILIO_SID, TWILIO_TOKEN), timeout=10)
        resp.raise_for_status()
        messages = resp.json().get("messages", [])
        if not messages:
            continue

        msg = messages[0]
        # Skip if this is the same message we saw before requesting the code
        if msg["sid"] == baseline_sid:
            continue

        match = pattern.search(msg["body"])
        if match:
            return match.group(1)

    raise TimeoutError(
        f"No Paycom 2FA code received via Twilio within {TWILIO_POLL_TIMEOUT_S}s"
    )


# ── Main Workflow ────────────────────────────────────────────────────────────


def run():
    # Ensure download directory exists
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

    driver = Driver(headless=False)
    driver.enable_human_mode()

    try:
        # ── Step 1: Navigate to login page ───────────────────────────────
        driver.get("https://www.paycomonline.net/v4/cl/cl-login.php")
        human_pause_long()

        # ── Step 2: Fill credentials ─────────────────────────────────────
        # The login form has three fields: client code, username, password.
        # No iframes, no shadow DOM — straightforward form fill.
        driver.type("#clientcode", CLIENT_CODE)
        human_pause(0.5, 1.2)
        driver.type("#username", USERNAME)
        human_pause(0.5, 1.2)
        driver.type("#password", PASSWORD)
        human_pause(0.8, 1.5)

        # ── Step 3: Submit the login form ────────────────────────────────
        driver.run_js("document.querySelector('form').submit()")
        human_pause_long(3.0, 5.0)
        wait_for_url(driver, "/security/two-factor/", timeout=30)

        # ── Step 4: Select SMS 2FA option ────────────────────────────────
        # The 2FA page presents radio buttons for SMS, call, or email.
        # The radio inputs are visually hidden; clicking them via JS works.
        # value="0" is the SMS option.
        human_pause()
        driver.click('input[name="two-factor-option"][value="0"]')
        human_pause(0.5, 1.0)

        # ── Step 5: Click "Send Code" ────────────────────────────────────
        driver.run_js(
            "const btn = Array.from(document.querySelectorAll('button'))"
            ".find(b => b.textContent.includes('Send Code'));"
            "if (btn) btn.click();"
        )
        human_pause_long()

        # ── Step 6: Fetch 2FA code from Twilio ───────────────────────────
        # Paycom sends a 6-digit code via SMS. We use the Twilio Messages
        # API to retrieve it. Polling starts after a baseline check to
        # avoid reading stale codes from previous sessions.
        driver.wait_for_element("#pin", wait=30)
        code = fetch_2fa_code_from_twilio()
        print(f"2FA code received: {code}")

        # ── Step 7: Enter 2FA code and submit ────────────────────────────
        human_pause()
        driver.type("#pin", code)
        human_pause(0.8, 1.5)

        # The submit button is a green button inside [data-testid="BottomButtonLayout"].
        driver.click(
            '[data-testid="BottomButtonLayout"] '
            'button[style*="background-color: rgb(0, 133, 66)"]'
        )

        # Wait for successful login — lands on client-landing page
        human_pause_long(3.0, 5.0)
        wait_for_url(driver, "/client-landing", timeout=30)
        print("Login successful — on client landing page")

        # ── Step 8: Navigate to report page ──────────────────────────────
        human_pause_long()
        driver.get(REPORT_URL)
        human_pause_long(3.0, 5.0)

        # ── Step 9: Click "Generate Report" ──────────────────────────────
        # The button is a dropdown group (div#dropdownButtonGroup_headerButton)
        # containing two <a> children. The first <a> is the "Generate Report"
        # action; the second is the dropdown toggle.
        driver.click("#dropdownButtonGroup_headerButton > a:first-child")
        human_pause_long()

        # ── Step 10: Wait for report generation ──────────────────────────
        # After clicking, we're redirected to the saved-report page.
        # A .recentReportStatusImage element appears while the report
        # generates. We wait for it to disappear (hidden/removed).
        wait_for_url(driver, "/srw-reportwriter-savedReport.php", timeout=30)
        human_pause()
        wait_for_element_hidden(driver, ".recentReportStatusImage", timeout=REPORT_GEN_TIMEOUT_S)
        print("Report generation complete")

        # ── Step 11: Download the report ─────────────────────────────────
        # Enable downloads to our directory via CDP
        from botasaurus_driver import cdp
        driver.run_cdp_command(
            cdp.browser.set_download_behavior(
                behavior="allow",
                download_path=str(DOWNLOAD_DIR),
            )
        )
        human_pause()

        # The download button is an <input type="button"> with an onclick
        # handler that first checks if a one-time password is required via
        # XHR, then triggers the actual file download.
        download_selector = (
            'ul.view-list:first-of-type li:first-child '
            '.buttonReportGreen[value="Download"]'
        )
        driver.click(download_selector)

        # Wait for the file to appear in the download directory
        downloaded_file = wait_for_download(DOWNLOAD_DIR, timeout=60)
        print(f"Downloaded: {downloaded_file.name}")

        # Copy to destination if the network share is accessible
        if DOWNLOAD_DEST.exists():
            dest_path = DOWNLOAD_DEST / downloaded_file.name
            shutil.copy2(str(downloaded_file), str(dest_path))
            print(f"Copied to: {dest_path}")
        else:
            print(f"Network share unavailable — saved locally: {downloaded_file}")

        # ── Step 12: Log out ─────────────────────────────────────────────
        # The logout link triggers a window.confirm() dialog. Override it
        # to auto-accept before clicking.
        human_pause_long()
        driver.run_js("window.confirm = () => true")
        driver.click("#clientLogout")

        # Verify we're back on the login page
        human_pause_long(2.0, 4.0)
        wait_for_url(driver, "/cl-login.php", timeout=15)
        print("Logged out successfully")

    finally:
        driver.close()


if __name__ == "__main__":
    run()
