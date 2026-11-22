"""
Real Browser E2E Acceptance Test & Screenshot Generator (Headless Chromium + Selenium).
Boots the live FastAPI + Arabic RTL web app on localhost, executes:
  Coordinator login -> Create Week 45 ->
  Employee 1 (Maram) login -> View ONLY assigned sections -> Submit P1_3 ->
  Employee 2 (Mohammed) login -> Open AI Diagnostic Editor -> Submit Status + Challenges ->
  Coordinator login -> Review/Approve -> Acknowledge missing -> Generate PPTX -> Download -> Settings
and saves 4 real UI screenshots.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait


def run_browser_e2e(shots_dir: Path, port: int = 8767) -> None:
    shots_dir.mkdir(parents=True, exist_ok=True)
    # Clear any sandbox proxy vars so Chromium connects directly to 127.0.0.1
    clean_env = {
        k: v
        for k, v in os.environ.items()
        if k.lower() not in ("http_proxy", "https_proxy", "all_proxy")
    }
    clean_env["NO_PROXY"] = "127.0.0.1,localhost"

    with tempfile.TemporaryDirectory(prefix="tomoh_e2e_") as tmp:
        srv_env = {
            **clean_env,
            "PYTHONPATH": ".",
            "TOMOH_DATABASE_URL": f"sqlite:///{tmp}/e2e_demo.db",
            "TOMOH_OUTPUT_DIR": f"{tmp}/generated",
            "TOMOH_UPLOADS_DIR": f"{tmp}/uploads",
            "TOMOH_AUTH_MODE": "header_dev",
        }
        srv = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
            env=srv_env,
        )
        try:
            for _ in range(40):
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as r:
                        if r.status == 200:
                            break
                except Exception:
                    time.sleep(0.25)

            for k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"):
                os.environ.pop(k, None)

            opts = Options()
            opts.add_argument("--headless=new")
            opts.add_argument("--no-sandbox")
            opts.add_argument("--disable-dev-shm-usage")
            opts.add_argument("--disable-gpu")
            opts.add_argument("--no-proxy-server")
            opts.add_argument("--window-size=1440,980")
            opts.add_argument("--lang=ar")
            driver = webdriver.Chrome(options=opts)
            wait = WebDriverWait(driver, 12)

            try:
                base_url = f"http://127.0.0.1:{port}/"
                driver.get(base_url)
                wait.until(EC.presence_of_element_located((By.ID, "login-user-select")))

                # Verify Arabic RTL root direction
                assert driver.find_element(By.TAG_NAME, "html").get_attribute("dir") == "rtl"

                # 1. Coordinator logs in & creates Week 45 via UI modal
                Select(driver.find_element(By.ID, "login-user-select")).select_by_value("u-coord")
                driver.find_element(By.ID, "btn-login-submit").click()
                wait.until(EC.presence_of_element_located((By.ID, "btn-new-week")))
                driver.find_element(By.ID, "btn-new-week").click()
                wait.until(EC.presence_of_element_located((By.ID, "btn-create-week-submit")))
                driver.find_element(By.ID, "btn-create-week-submit").click()
                wait.until(EC.presence_of_element_located((By.ID, "btn-generate-pptx")))

                # 2. Employee 1 (Maram) logs in -> sees ONLY her 2 assigned sections -> Screenshot 1
                driver.find_element(By.ID, "btn-logout").click()
                wait.until(EC.presence_of_element_located((By.ID, "login-user-select")))
                Select(driver.find_element(By.ID, "login-user-select")).select_by_value("u-maram")
                driver.find_element(By.ID, "btn-login-submit").click()
                wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".btn-open-project")))
                time.sleep(0.4)
                cards = driver.find_elements(By.CSS_SELECTOR, ".section-card")
                assert len(cards) == 2, f"Expected 2 assigned cards for Maram, got {len(cards)}"
                s1 = shots_dir / "screenshot-1-employee-portal.png"
                driver.save_screenshot(str(s1))
                print("Captured:", s1.resolve())

                # Maram opens P1_3 and submits achievements & task
                driver.find_element(By.CSS_SELECTOR, ".btn-open-project").click()
                wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".ach-input")))
                driver.find_element(By.CSS_SELECTOR, ".ach-input").send_keys(
                    "[اختبار متصفح] اعتماد النسخة النهائية لفيديوهات قصص النجاح."
                )
                driver.find_element(By.CSS_SELECTOR, ".task-input").send_keys(
                    "[اختبار متصفح] إطلاق الحملة المصغرة خلال الأسبوع القادم."
                )
                driver.find_element(By.ID, "btn-submit-update").click()
                time.sleep(0.5)

                # 3. Employee 2 (Mohammed) logs in -> opens AI Diagnostic editor -> submits -> Screenshot 2
                driver.find_element(By.ID, "btn-logout").click()
                wait.until(EC.presence_of_element_located((By.ID, "login-user-select")))
                Select(driver.find_element(By.ID, "login-user-select")).select_by_value("u-mohammed")
                driver.find_element(By.ID, "btn-login-submit").click()
                wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".btn-open-project")))
                driver.find_element(By.CSS_SELECTOR, ".btn-open-project").click()
                wait.until(EC.presence_of_element_located((By.ID, "ed-project-status")))
                Select(driver.find_element(By.ID, "ed-project-status")).select_by_value("on_track")
                driver.find_element(By.ID, "ed-challenges").send_keys(
                    "تسريع اعتماد نطاق المورد التقني لتحديث أسئلة التشخيص"
                )
                driver.find_element(By.ID, "btn-submit-update").click()
                time.sleep(0.5)
                s2 = shots_dir / "screenshot-2-project-editor.png"
                driver.save_screenshot(str(s2))
                print("Captured:", s2.resolve())

                # 4. Coordinator logs in -> approves -> acknowledges missing -> generates PPTX -> Screenshot 3
                driver.find_element(By.ID, "btn-logout").click()
                wait.until(EC.presence_of_element_located((By.ID, "login-user-select")))
                Select(driver.find_element(By.ID, "login-user-select")).select_by_value("u-coord")
                driver.find_element(By.ID, "btn-login-submit").click()
                wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".btn-coord-approve")))
                driver.find_element(By.CSS_SELECTOR, ".btn-coord-approve").click()
                time.sleep(0.5)
                driver.find_element(By.ID, "chk-ack-missing").click()
                driver.find_element(By.ID, "btn-generate-pptx").click()
                wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "a[href*='/download']")))
                time.sleep(0.5)
                s3 = shots_dir / "screenshot-3-coordinator-dashboard.png"
                driver.save_screenshot(str(s3))
                print("Captured:", s3.resolve())

                # 5. Coordinator opens Project & Assignment Settings -> Screenshot 4
                for tab in driver.find_elements(By.CSS_SELECTOR, ".nav-tab"):
                    if "إدارة المشاريع" in tab.text:
                        tab.click()
                        break
                wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".set-owner")))
                time.sleep(0.4)
                s4 = shots_dir / "screenshot-4-coordinator-settings.png"
                driver.save_screenshot(str(s4))
                print("Captured:", s4.resolve())

                print("REAL BROWSER SELENIUM E2E PASSED 100%!")
            finally:
                driver.quit()
        finally:
            srv.terminate()
            srv.wait(timeout=5)


if __name__ == "__main__":
    out = Path("/working_dir/c_cc067088a25be814/artifacts/file_generation/ttl=63d/output")
    run_browser_e2e(out)
