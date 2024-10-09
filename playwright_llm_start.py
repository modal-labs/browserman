import modal
import logging as L
from pathlib import Path

L.basicConfig(
    level=L.INFO,
    format="%(asctime)s %(levelname)s [%(filename)s.%(funcName)s:%(lineno)d] %(message)s",
    datefmt="%b %d %H:%M:%S",
)

app = modal.App("playwright_llm_start")

volume = modal.Volume.from_name(
    "browser-man", create_if_missing=True
)
volume_path = Path("/vol/data")
screenshots_path = volume_path / "screenshots"

playwright_image = (
    modal.Image.debian_slim(python_version="3.10" )
    .run_commands(  # Doesn't work with 3.11 yet
        "apt-get update",
        "apt-get install -y software-properties-common",
        "apt-add-repository non-free",
        "apt-add-repository contrib",
        "pip install playwright==1.47.0",
        "playwright install-deps chromium",
        "playwright install chromium",
    )
)

with playwright_image.imports():
    from playwright.async_api import async_playwright

@app.function(
    image=playwright_image,
    volumes={volume_path: volume}
)
# @modal.web_endpoint(method="POST", docs=True) TODO turn on
async def run_browser_action_model(prompt: str):
    try:
        L.info(f"Setup...")
        # Unique screenshot paths so we can see them all at the end.
        global screenshot_index
        screenshot_index = 0
        screenshot_name_fmt = f"{screenshots_path}/screenshot_%d.png"
        def get_next_screenshot_path():
            global screenshot_index
            return_val = screenshot_name_fmt % screenshot_index
            screenshot_index += 1
            return return_val

        def get_last_screenshot_path():
            global screenshot_index
            return screenshot_name_fmt % (screenshot_index - 1)

        # Step 1): Get a URL given the prompt
        # TODO: url = LLM(prompt_for_url_format % prompt)
        # url = "https://www.doordash.com/" # Issues with captchas
        url = "https://modal.com/"

        # Step 2): Obtain initial screenshot
        async with async_playwright() as p:
            L.info(f"Launch chromium...")
            browser = await p.chromium.launch()
            page = await browser.new_page()

            L.info(f"Going to url: {url}...")
            await page.goto(url)

            L.info(f"Waiting for load state...")
            await page.wait_for_load_state("load")

            L.info(f"Taking screenshot #{screenshot_index}...")
            await page.screenshot(path=get_next_screenshot_path())

            # Step 2): Loop: LLM(screenshot) -> text of button to click
            for button_text in ["Docs", "Guide", "Done"]:
                #TODO for vLLM
                # image = ImageAsset(get_last_screenshot_path()).pil_image.convert("RGB")

                # TODO: button_text = LLM(image, prompt_for_button_format)
                if button_text == "Done":
                    break

                L.info(f"Looking for 1st link with text={button_text}...")
                button = page.get_by_role('link', name=button_text).nth(0)
                L.info(f"Clicking...")
                async with page.expect_navigation():
                    await button.click(timeout=5000)

                L.info(f"Waiting for navigation & networkidle & load state...")
                await page.wait_for_load_state("networkidle")
                await page.wait_for_load_state("load")

                L.info(f"Taking screenshot #{screenshot_index}...")
                await page.screenshot(path=get_next_screenshot_path())

    except Exception as e:
        print("ERROR: ", e)
        breakpoint()
    return {"success": True}


@app.local_entrypoint()
def go():
    run_browser_action_model.remote("noop")

