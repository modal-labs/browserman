import json
import asyncio
from urllib.parse import urlparse

import modal
import base64
import io
from pathlib import Path

app = modal.App("browserman")

events = modal.Queue.from_name("browserman-events", create_if_missing=True)
volume = modal.Volume.from_name("browserman-volume", create_if_missing=True)
cookie_dict = modal.Dict.from_name("browserman-cookies", create_if_missing=True)

frontend_path = Path(__file__).parent / "frontend"

screenshots_path = Path("/tmp/screenshots")

playwright_image = (
    modal.Image.debian_slim(python_version="3.10")
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
    # .pip_install("ipython")
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
    return base64.b64encode(resized_image_bytes).decode("utf-8")


def extract_parameters(output):
    soup = BeautifulSoup(output, features="html.parser")
    for function_name in ["navigate_to", "click_button", "final_answer", "go_back"]:
        element = soup.find(f"function={function_name}")
        if element:
            return json.loads(element.contents[0])
    return {}


@app.function(
    image=playwright_image,
    allow_concurrent_inputs=10,
    mounts=[modal.Mount.from_local_python_packages("prompt")],
    container_idle_timeout=1200,
    timeout=1200,
    region="us-east",
    volumes={"/data": modal.Volume.from_name("browserman-volume", create_if_missing=True)}
)
async def session(query: str):
    call_id = modal.current_function_call_id()
    Model = modal.Cls.lookup("browserman-llm", "Model")
    step = 0
    history = []
    image = None
    url = ""
    dom = ""
    use_buttons = True

    async def get_next_target():
        nonlocal url, dom, history, image
        prompt = get_prompt(query, url, dom, history, use_buttons)
        # print(prompt)
        # print(prompt.split("<|start_header_id|>user<|end_header_id|>")[1])

        # Retry until we get a URL
        for _ in range(10):
            print(f"Prompting model: {prompt}")
            output = await Model().inference.remote.aio(prompt, image, temperature=0.2)

            print(f"Model output: {output}")
            output = output.split("\n")[0]
            history.append(output)

            parameters = extract_parameters(output)
            print("Parameters: ", parameters)

            if parameters:
                return parameters

        raise Exception("Failed to get URL from Model")

    async with async_playwright() as p:
        print("Launching chromium...")
        browser = await p.chromium.launch()
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        while step < 10:
            print(f"======Step {step} {use_buttons=} =====")
            if step > 0:
                print(f"Taking screenshot #{step}...")
                path = screenshots_path / call_id / f"screenshot_{step}.png"
                await page.screenshot(path=path)
                image = Image.open(path)
                dom = await page.content()
                Path("/data").mkdir(parents=True, exist_ok=True)
                with open(f"/data/dom_{step}.txt", "w") as f:
                    f.write(dom)
                await events.put.aio({"image": encode_image(image)}, partition=call_id)

            step += 1

            target = await get_next_target()
            if not use_buttons:
                use_buttons = True
            await events.put.aio(target, partition=call_id)

            if "button_text" in target:
                button_text = target['button_text']
                reason = target.get('reason', "")
                print(f"Looking for button with text={button_text} because `{reason}`...")
                options = [page.get_by_role("button", name=button_text).nth(0)]
                options.append(page.get_by_role("link", name=button_text).nth(0))

                for button in options:
                    print(f"Clicking {button}...")
                    if not await button.is_visible():
                        print("Button is not visible, trying to scroll into view...")
                        try:
                            await button.scroll_into_view_if_needed(timeout=2_000)
                        except Exception:
                            print("Failed to scroll into view")

                        if not await button.is_visible():
                            print("Button is still not visible, skipping.")
                            use_buttons = False
                            continue

                    bounding_box = await button.bounding_box()
                    print(f"Button position: x={bounding_box['x']}, y={bounding_box['y']}")
                    print(
                        f"Button size: width={bounding_box['width']}, height={bounding_box['height']}"
                    )

                    # Crop the bounding box area from the existing image
                    # Get the page's viewport size
                    scale_x = page.viewport_size["width"] / image.width
                    scale_y = page.viewport_size["height"] / image.height

                    # Scale the bounding box coordinates
                    scaled_x = int(bounding_box["x"] * scale_x)
                    scaled_y = int(bounding_box["y"] * scale_y)
                    scaled_width = int(bounding_box["width"] * scale_x)
                    scaled_height = int(bounding_box["height"] * scale_y)

                    # Crop the image using the scaled coordinates
                    cropped_image = image.crop(
                        (
                            scaled_x,
                            scaled_y,
                            scaled_x + scaled_width,
                            scaled_y + scaled_height,
                        )
                    )
                    await events.put.aio(
                        {"image": encode_image(cropped_image)}, partition=call_id
                    )
                    try:
                        await button.click(timeout=10_000)
                        # await page.mouse.click(
                        #     x=bounding_box["x"] + bounding_box["width"] / 2,
                        #     y=bounding_box["y"] + bounding_box["height"] / 2,
                        # )
                        await asyncio.sleep(1)
                        print("Successfully clicked")
                        use_buttons = True
                        break
                    except Exception as e:
                        print("Failed to click", e)
                        use_buttons = False
            elif "final_answer" in target:
                break
            elif "go_back" in target:
                print("Going back")
                await page.go_back()
            else:
                assert "url" in target
                url = target["url"]

                url_parts = urlparse(url)
                cookies = cookie_dict.get(url_parts.netloc)
                if cookies:
                    print(f"Adding cookies for {url_parts.netloc} to context...")
                    for cookie in cookies:
                        cookie.pop("sameSite", None)
                    await context.add_cookies(cookies)
                else:
                    print(f"Did not find cookies for {url_parts.netloc}")

                print(f"Going to url: {url}...")
                await page.goto(url)

            if not use_buttons:
                print("FAILED TO CLICK")
                history[-1] += " (FAILED)"

            await page.wait_for_load_state("networkidle", timeout=120_000)
            await page.wait_for_load_state("load", timeout=120_000)


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
                event = await events.get.aio(partition=call_id)
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

    web_app.mount("/", fastapi.staticfiles.StaticFiles(directory="/assets", html=True))
    return web_app
