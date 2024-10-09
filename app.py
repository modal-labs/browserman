import modal
from pathlib import Path

app = modal.App("browserman")

frontend_path = Path(__file__).parent / "frontend"


@app.function()
def session(query: str):
    pass



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
    web_app = fastapi.FastAPI()

    # Model = modal.Cls.lookup("browserman", "Model")

    # @web_app.get("/completion/{question}")
    # async def completion(question: str):
    #     from urllib.parse import unquote

    #     async def generate():
    #         # TODO: stream
    #         text = await Model().inference.remote.aio( unquote(question))
    #         yield f"data: {json.dumps(dict(text=text), ensure_ascii=False)}\n\n"

    #     return StreamingResponse(generate(), media_type="text/event-stream")

    @web_app.post("/start")
    async def start(request: Request):
        data = await request.json()
        call = session.spawn(data["query"])
        return {"call_id": call.object_id}

    web_app.mount(
        "/", fastapi.staticfiles.StaticFiles(directory="/assets", html=True)
    )
    return web_app
