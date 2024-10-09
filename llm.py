import modal.gpu

GPU_COUNT = 4

image = modal.Image.debian_slim(python_version="3.10").pip_install(
    "pillow",
    "torch",
    "requests",
    "huggingface-hub",
    "vllm",
)

app = modal.App("browserman-llm", image=image)

MODEL_NAME = "neuralmagic/Llama-3.2-90B-Vision-Instruct-FP8-dynamic"


@app.cls(gpu=modal.gpu.H100(count=GPU_COUNT), container_idle_timeout=20 * 60)
class Model:
    @modal.build()
    def build(self):
        import transformers.utils
        from huggingface_hub import snapshot_download

        snapshot_download(MODEL_NAME)
        transformers.utils.move_cache()

    @modal.enter()
    def enter(self):
        from vllm import LLM

        self.llm = LLM(
            model=MODEL_NAME,
            max_num_seqs=1,
            enforce_eager=True,
            tensor_parallel_size=GPU_COUNT,
        )

    @modal.method()
    def inference(self, prompt, image, temperature=0.2):
        from vllm import SamplingParams

        # Set up sampling parameters
        sampling_params = SamplingParams(temperature=temperature, max_tokens=300)

        # Generate the response
        inputs = {"prompt": prompt, "multi_modal_data": {}}
        if image:
            inputs["multi_modal_data"]["image"] = image
        outputs = self.llm.generate(inputs, sampling_params=sampling_params)

        return outputs[0].outputs[0].text
