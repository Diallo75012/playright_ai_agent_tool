from playwright.sync_api import sync_playwright, Playwright


def run(playwright: Playwright):
    chromium = playwright.chromium  # or "firefox" or "webkit".
    browser = chromium.launch()
    page = browser.new_page()
    page.goto("http://google.com")

    # other actions...
    page.screenshot(path="google_before_with_gdpr.png")
    page.get_by_role("button", name="Tout refuser").click()
    page.screenshot(path="google_after_cleared_gdpr.png")
    browser.close()


with sync_playwright() as playwright:
    run(playwright)
