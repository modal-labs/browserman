import modal
import logging as L
L.basicConfig(
    level=L.INFO,
    format="%(asctime)s %(levelname)s [%(filename)s.%(funcName)s:%(lineno)d] %(message)s",
    datefmt="%b %d %H:%M:%S",
)

app = modal.App("browserman")


playwright_image = (
    modal.Image.debian_slim(python_version="3.10" )
    .run_commands(  # Doesn't work with 3.11 yet
        # New
        # "vllm==0.4.0.post1",
        # Playwright Example:
        "apt-get update",
        "apt-get install -y software-properties-common",
        "apt-add-repository non-free",
        "apt-add-repository contrib",
        "pip install playwright==1.42.0",
        "playwright install-deps chromium",
        "playwright install chromium",
    ).pip_install(
    )
)

with playwright_image.imports():
    from playwright.async_api import async_playwright

#TODO vLLM Image & Class
        # "vllm==0.6.2", # Separate image
    # from vllm.assets.image import ImageAsset
@app.cls(image=playwright_image, gpu="A10G")
class vLLM:
    @modal.enter()
    def enter(self) :
        pass

    @modal.method()
    async def run(self, prompt: str):
        pass

@app.function(image=playwright_image)
# @modal.web_endpoint(method="POST", docs=True) TODO turn on
async def run_browser_action_model(prompt: str):
    try:
        L.info(f"Setup...")
        ### Setup ###
        # Unique screenshot paths so we can see them all at the end.
        global screenshot_index
        screenshot_index = 0
        screenshot_name_fmt = "screenshot_%d.png"
        def get_next_screenshot_path():
            global screenshot_index
            return screenshot_name_fmt % screenshot_index
            screenshot_index += 1
        def get_last_screenshot_path():
            global screenshot_index
            return screenshot_name_fmt % (screenshot_index - 1)

        # Prompt Engineering prefixes
        # prompt_for_url_format = (
            # "Please give me a URL that will start to satisfy the"
            # "following request prompt:%s")
        # prompt_for_button = (
            # "Please give me the text of the button you would like me to click"
            # "to proceed with request"
            # )

        # Step 1): Get a URL given the prompt
        # TODO: url = LLM(prompt_for_url_format % prompt)
            # TODO: Check URL is valid and retry if not?
        url = "https://www.doordash.com/"

        # XXX: Does vLLM have state across inference calls? Session ID?

        # Step 2): Obtain initial screenshot
        async with async_playwright() as p:
            L.info(f"Launch chromium...")
            browser = await p.chromium.launch()
            page = await browser.new_page()
            L.info(f"GOTO URL")
            await page.goto(url)

            L.info(f"screenshot")
            await page.screenshot(path=get_next_screenshot_path())

            # Step 2): Loop: LLM(screenshot) -> text of button to click
            while True:
                # image = ImageAsset(get_last_screenshot_path()).pil_image.convert("RGB")

                # TODO: button_text = LLM(image, prompt_for_button_format)
                button_text = "Sign In"
                button_text = "Login"
                if button_text == "Done":
                    break

                # TODO: Broken
                # locate_me = f'button:text({button_text})'
                # L.info ("Locateme:",locate_me)
                # button = page.locator(locate_me)
                for button_text in ["Sign in", "Login"]:
                    try:
                        L.info(f"Locate & Click {screenshot_index} : {button_text}")
                        locator = page.getByRole('button', { name: button_text });
                        L.info(f"locator: {locator}")
                        await button.click()
                    except Exception as e:
                        L.info("Error: ", e)
                        breakpoint()

                # TODO Is this the right thing to wait for?
                L.info(f"Wait for new page...")
                page = await browser.new_page()

                L.info(f"Screenshot {screenshot_index}...")
                await page.screenshot(path=get_next_screenshot_path())
                break #XXX Remove

    except Exception as e:
        print("ERROR: ", e)
    breakpoint()
    return {"success": True}


@app.local_entrypoint()
def go():
    run_browser_action_model.remote("noop")

