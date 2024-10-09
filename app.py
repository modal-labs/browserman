import json

import modal
import base64
import io
from pathlib import Path

app = modal.App("browserman")

events = modal.Queue.from_name("browserman-events", create_if_missing=True)

cookie_dict = modal.Dict.from_name("browserman-cookies", create_if_missing=True)

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
    from prompt import get_prompt
    from PIL import Image

def encode_image(image):
    resized_image = image.resize((480, 270))

    buffer = io.BytesIO()
    resized_image.save(buffer, format="PNG")
    resized_image_bytes = buffer.getvalue()
    return base64.b64encode(resized_image_bytes).decode('utf-8')

def extract_parameters(output):
    output = output.split('\n')[0]

    soup = BeautifulSoup(output, features="html.parser")
    for e in soup.find_all('function=navigate_to'):
        return json.loads(e.contents[0])
    for e in soup.find_all('function=click_button'):
        return json.loads(e.contents[0])
    return None

def get_screenshot_path(call_id: str, idx: int):
    return screenshots_path / call_id / f"screenshot_{idx}.png"

@app.function(image=playwright_image, allow_concurrent_inputs=10, mounts=[modal.Mount.from_local_python_packages("prompt")])
async def session(query: str):
    call_id = modal.current_function_call_id()
    Model = modal.Cls.lookup("browserman-llm", "Model")
    step = 0
    history = []
    image = None
    url = ""
    dom = ""

    async def get_next_target(page):
        nonlocal url, dom, history
        prompt = get_prompt(query, url, dom, history)
        print("Prompt: ", prompt)

        # Retry indefinitely until we get a URL
        while True:
            print("Attempting to get URL from Model...")
            output = await Model().inference.remote.aio(prompt, None)
            history.append(output) # TODO: truncate?
            await events.put.aio({"text": output}, partition = call_id)
            print(f"Model output: {output}")

            parameters = extract_parameters(output)
            print("Parameters: ", parameters)

            if "url" in parameters:
                return {"url": parameters["url"]}
            elif "button_text" in parameters:
                button_text = parameters["button_text"]
                print(f"Looking for button with text={button_text}...")
                button = page.get_by_role('link', name=button_text).nth(0)
                return {"button": button}

    async with async_playwright() as p:
        print("Launching chromium...")
        browser = await p.chromium.launch()
        page = await browser.new_page()
        
        step += 1

        while step < 5:
            if step > 0:
                print(f"Taking screenshot #{step}...")
                await page.screenshot(path=get_screenshot_path(call_id, step))
                image = Image.open(get_screenshot_path(call_id, step))
                dom = await page.content()
                await events.put.aio({"image": encode_image(image)}, partition = call_id)

            target = await get_next_target(page)

            if "button" in target:
                button = target["button"]
                print(f"Clicking {button}...")
                await button.click(timeout=5000)
            else:
                assert "url" in target
                url = target["url"]

                print(f"Going to url: {url}...")
                await page.goto(url)

            print("Waiting for navigation & networkidle & load state...")
            await page.wait_for_load_state("networkidle")
            await page.wait_for_load_state("load")

            print(f"Taking screenshot #{step}...")
            await page.screenshot(path=get_screenshot_path(call_id, step))




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
        import urllib.parse
        data = await request.json()

        url = data["url"]
        cookies = data["cookies"]

        parsed_url = urllib.parse.urlparse(url)
        await cookie_dict.put.aio(parsed_url.hostname, cookies)



    web_app.mount(
        "/", fastapi.staticfiles.StaticFiles(directory="/assets", html=True)
    )
    return web_app
