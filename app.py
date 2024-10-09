import json

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

dummy_output = """<function=navigate_to>{"url": "https://www.doordash.com/"}</function>
Step 2: <function=click_button>{"button_text": "Sign In"}</function>
Step 3: <function=click_button>{"button_text": "Enter Delivery Address"}</function>
Step 4: <function=click_button>{"button_text": "Search for restaurants"}</function>
Step 5: <function=click_button>{"button_text": "Pizza"}</function>
Step 6: <function=click_button>{"button_text": "Select a restaurant"}</function>
Step 7: <function=click_button>{"button_text": "Choose a pizza"}</function>
Step 8: <function=click_button>{"button_text": "Add to cart"}</function>
Step 9: <function=click_button>{"button_text": "Checkout"}</function>
Step 10: <function=click_button>{"button_text": "Place Order"}</function>"""

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
    resized_image = image.resize((256, 256))

    buffer = io.BytesIO()
    resized_image.save(buffer, format="PNG")
    resized_image_bytes = buffer.getvalue()
    return base64.b64encode(resized_image_bytes).decode('utf-8')

@app.function(image=playwright_image, allow_concurrent_inputs=10,     mounts=[modal.Mount.from_local_python_packages("prompt")])
def extract_parameters(output = dummy_output):
    output = output.split('\n')[0]

    soup = BeautifulSoup(output, features="html.parser")
    for e in soup.find_all('function=navigate_to'):
        data = json.loads(e.contents[0])
        print(data)
        return data
    for e in soup.find_all('function=click_button'):
        data = json.loads(e.contents[0])
        print(data)
        return data
    return None

@app.function(image=playwright_image, allow_concurrent_inputs=10,     mounts=[modal.Mount.from_local_python_packages("prompt")], volumes={"/data": volume})
async def session(query: str):
    call_id = modal.current_function_call_id()
    # Unique screenshot paths so we can see them all at the end.
    screenshot_index = 0

    def get_next_screenshot_path():
        nonlocal screenshot_index
        return_val = screenshots_path / call_id / f"screenshot_{screenshot_index}.png"
        screenshot_index += 1
        return return_val

    def get_last_screenshot_path():
        nonlocal screenshot_index
        return screenshots_path / call_id / f"screenshot_{screenshot_index - 1}.png"

    Model = modal.Cls.lookup("browserman", "Model")

    # Step 1): Get a URL given the prompt
    dom = ""
    url = ""
    image = None
    history = []
    prompt = get_prompt(query, url, dom, history)
    print("Prompt: ", prompt)
    # Retry indefinitely until we get a URL
    while True:
        print(f"Attempting to get URL from Model...")
        output = await Model().inference.remote.aio(prompt, None)
        print(f"\tModel output: {output}")

        parameters = extract_parameters.local(output)
        print("Parameters: ", parameters)
        if parameters is not None:
            if "url" in parameters:
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
            dom = await page.content()
            # print(dom)
            # print(type(dom))
            # breakpoint()
            print(type(dom))
            Path("/data").mkdir(parents=True, exist_ok=True)
            with open("/data/dom.txt", "w") as f:
                f.write(dom)
            dom = str(dom)
            await events.put.aio({"image": encode_image(image)}, partition = call_id)

            print(query)
            prompt = get_prompt(query, url, dom, history)

            # Retry indefinitely until we get a valid action
            while True:
                print(f"Attempting to get action from Model...")
                output = await Model().inference.remote.aio(prompt, image)
                print(f"\tModel output: {output}")

                # * <function=click_button>{"button_text": "Delivery Fees: Under $3"}</function>
                parameters = extract_parameters.local(output)
                if parameters is not None:
                    if "button_text" in parameters:
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
