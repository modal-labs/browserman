import modal
import base64
from pathlib import Path

app = modal.App("browserman")

events = modal.Queue.from_name("browserman-events", create_if_missing=True)

frontend_path = Path(__file__).parent / "frontend"

@app.function()
def session(query: str):
    from urllib.parse import unquote
    from PIL import Image

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

        def extract_paramaters(output):
            #TODO Use soup
            # * <function=navigate_to>{"url": "https://www.doordash.com/"}</function>
            if output.find("{") != -1 and output.find("}") != -1:
                i,j = output.find("{"), output.find("}")
                return dict(output[i+1:j])
            return None
            # * <function=navigate_to>{"url": "https://www.doordash.com/"}</function>
            if output.find("{") != -1 and output.find("}") != -1:
                i,j = output.find("{"), output.find("}")
                return unquote(dict(output[i+1:j])["url"])
            return None

        # Modal Stuff
        call_id = modal.current_function_call_id()
        Model = modal.Cls.lookup("browserman", "Model")

        # Step 1): Get a URL given the prompt
        dom = ""
        url = ""
        image = None
        history = []
        prompt = get_prompt(query, url, history, dom)
        # Retry indefinitely until we get a URL
        while True:
            L.info(f"Attempting to get URL from Model...")
            output = await Model().inference.remote.aio(prompt)
            L.info(f"\tModel output: {output}")

            parameters = extract_paramaters(output)
            if parameters is not None:
                if parameters.has_key("url"):
                    url = parameters["url"]
                    break
        await events.put.aio(parameters, partition = call_id)
        history.append(output)

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
            while True:
                image = Image.open(get_last_screenshot_path())
                dom = page.content()
                prompt = get_prompt(query, url, history, dom)

                # Retry indefinitely until we get a valid action
                while True:
                    L.info(f"Attempting to get action from Model...")
                    output = LLM(image, prompt_for_button_format)
                    L.info(f"\tModel output: {output}")

                    # * <function=click_button>{"button_text": "Delivery Fees: Under $3"}</function>
                    parameters = extract_paramaters(output)
                    if parameters is not None:
                        if parameters.has_key("button_text"):
                            button_text = parameters["button_text"]
                            break
                await events.put.aio(parameters, partition = call_id)
                history.append(output)

                if button_text == "Done":  # XXX Never? XXX
                    break

                L.info(f"Looking for button with text={button_text}...")
                button = page.get_by_role('link', name=button_text).nth(0)
                L.info(f"Clicking {button}...")
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
