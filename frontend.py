import modal
from pathlib import Path

app = modal.App("browserman-frontend")

frontend_path = Path(__file__).parent / "llm-frontend"


@app.function(
    mounts=[modal.Mount.from_local_dir(frontend_path, remote_path="/assets")],
    keep_warm=1,
    allow_concurrent_inputs=20,
    timeout=60 * 10,
)
@modal.asgi_app(label="browserman-test")
def tgi_mixtral():
    import json

    import fastapi
    import fastapi.staticfiles
    from fastapi.responses import StreamingResponse

    web_app = fastapi.FastAPI()

    Model = modal.Cls.lookup("browserman", "Model")

    @web_app.get("/stats")
    async def stats():
        stats = await Model().inference.get_current_stats.aio()
        return {
            "backlog": stats.backlog,
            "num_total_runners": stats.num_total_runners,
            "model": "Llama 3.2",
        }

    @web_app.get("/completion/{question}")
    async def completion(question: str):
        from urllib.parse import unquote

        async def generate():
            # TODO: stream
            text = await Model().inference.remote.aio(unquote(question))
            yield f"data: {json.dumps(dict(text=text), ensure_ascii=False)}\n\n"

        return StreamingResponse(generate(), media_type="text/event-stream")

    web_app.mount("/", fastapi.staticfiles.StaticFiles(directory="/assets", html=True))
    return web_app
