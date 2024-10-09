import json

import modal
import base64
import io
from pathlib import Path

app = modal.App("browserman")

events = modal.Queue.from_name("browserman-events", create_if_missing=True)

frontend_path = Path(__file__).parent / "frontend"

screenshots_path = Path("/tmp/screenshots")

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
    .pip_install("Pillow")
    .pip_install("beautifulsoup4")
)

with playwright_image.imports():
    from bs4 import BeautifulSoup
    from playwright.async_api import async_playwright
    from prompt import prompt as get_prompt
    from PIL import Image

def encode_image(image):
    resized_image = image.resize((256, 256))

    buffer = io.BytesIO()
    resized_image.save(buffer, format="PNG")
    resized_image_bytes = buffer.getvalue()
    return base64.b64encode(resized_image_bytes).decode('utf-8')

@app.function(image=playwright_image, allow_concurrent_inputs=10,     mounts=[modal.Mount.from_local_python_packages("prompt")])
async def session(query: str):
    call_id = modal.current_function_call_id()
    # Unique screenshot paths so we can see them all at the end.
    screenshot_index = 0
    screenshot_name_fmt = screenshots_path / call_id / "screenshot_%d.png"
    def get_next_screenshot_path():
        global screenshot_index
        return_val = screenshot_name_fmt % screenshot_index
        screenshot_index += 1
        return return_val

    def get_last_screenshot_path():
        global screenshot_index
        return screenshot_name_fmt % (screenshot_index - 1)

    def extract_parameters(output):
        soup = BeautifulSoup(output, features="html.parser")
        for e in soup.find_all('function'):
            return json.loads(e.contents[0])
        return None

    Model = modal.Cls.lookup("browserman", "Model")

    # Step 1): Get a URL given the prompt
    dom = ""
    url = ""
    image = None
    history = []
    prompt = get_prompt(query, url, history, dom)
    print("Prompt: ", prompt)
    # Retry indefinitely until we get a URL
    while True:
        print(f"Attempting to get URL from Model...")
        output = await Model().inference.remote.aio(prompt, None)
        print(f"\tModel output: {output}")

        parameters = extract_parameters(output)
        if parameters is not None:
            if parameters.has_key("url"):
                url = parameters["url"]
                break
    await events.put.aio(parameters, partition = call_id)
    history.append(output)

    # Step 2): Obtain initial screenshot
    async with async_playwright() as p:
        print(f"Launch chromium...")
        browser = await p.chromium.launch()
        page = await browser.new_page()

        print(f"Going to url: {url}...")
        await page.goto(url)

        print(f"Waiting for load state...")
        await page.wait_for_load_state("load")

        print(f"Taking screenshot #{screenshot_index}...")
        await page.screenshot(path=get_next_screenshot_path())

        # Step 2): Loop: LLM(screenshot) -> text of button to click
        while True:
            image = Image.open(get_last_screenshot_path())
            dom = page.content()
            await events.put.aio({"image": encode_image(image)}, partition = call_id)

            prompt = get_prompt(query, url, history, dom)

            # Retry indefinitely until we get a valid action
            while True:
                print(f"Attempting to get action from Model...")
                output = await Model().inference.remote.aio(prompt, image)
                print(f"\tModel output: {output}")

                # * <function=click_button>{"button_text": "Delivery Fees: Under $3"}</function>
                parameters = extract_parameters(output)
                if parameters is not None:
                    if parameters.has_key("button_text"):
                        button_text = parameters["button_text"]
                        break
            await events.put.aio({"text": output}, partition = call_id)
            history.append(output)

            if button_text == "Done":  # XXX Never? XXX
                break

            print(f"Looking for button with text={button_text}...")
            button = page.get_by_role('link', name=button_text).nth(0)
            print(f"Clicking {button}...")
            async with page.expect_navigation():
                await button.click(timeout=5000)

            print(f"Waiting for navigation & networkidle & load state...")
            await page.wait_for_load_state("networkidle")
            await page.wait_for_load_state("load")

            print(f"Taking screenshot #{screenshot_index}...")
            await page.screenshot(path=get_next_screenshot_path())
    return {"success": True}




@app.function(
    mounts=[modal.Mount.from_local_dir(frontend_path, remote_path="/assets")],
    keep_warm=1,
    allow_concurrent_inputs=20,
)
@modal.asgi_app(label="browserman-test")
def main():
    import json

    import fastapi
    import fastapi.staticfiles

    from fastapi import Request
    from fastapi.responses import StreamingResponse
    web_app = fastapi.FastAPI()

    @web_app.post("/start")
    async def start(request: Request):
        data = await request.json()
        call = await session.spawn.aio(data["query"])
        return {"call_id": call.object_id}

    @web_app.get("/status/{call_id}")
    async def status(call_id: str):
        async def generate():
            while True:
                event = await events.get.aio(partition = call_id)
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

                if event.get("done", False):
                    break

        return StreamingResponse(generate(), media_type="text/event-stream")

    @web_app.post("/cookies")
    async def cookies(request: Request):
        data = await request.json()



    web_app.mount(
        "/", fastapi.staticfiles.StaticFiles(directory="/assets", html=True)
    )
    return web_app
