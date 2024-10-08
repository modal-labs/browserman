import modal
import modal.gpu

image = (
    modal.Image.debian_slim(python_version="3.10")
    .pip_install(
        "pillow",
        "torch",
        "requests",
        "huggingface-hub",
        "vllm",
    )
)

APP_NAME = "browserman"
app = modal.App(APP_NAME, image=image)

MODEL_NAME = "neuralmagic/Llama-3.2-11B-Vision-Instruct-FP8-dynamic"


@app.cls(gpu=modal.gpu.H100(), container_idle_timeout=30 * 60)
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
        self.llm = LLM(model=MODEL_NAME, max_num_seqs=1, enforce_eager=True)

    @modal.method()
    def inference(self, prompt):
        from vllm import SamplingParams

        # Set up sampling parameters
        sampling_params = SamplingParams(temperature=0.2, max_tokens=30)

        # Generate the response
        inputs = {
            "prompt": prompt,
            "multi_modal_data": {
            },
        }
        outputs = self.llm.generate(inputs, sampling_params=sampling_params)

        return outputs[0].outputs[0].text


if __name__ == "__main__":
    prompt = """
    <|begin_of_text|><|start_header_id|>system<|end_header_id|>
    
    You have access to the following functions:
    
    Use the function 'navigate_to' to: To open a web page
    {
        "name": "navigate_to",
        "description": "Navigate to a web page in a browser",
        "parameters": {
            "url": {
                "param_type": "string",
                "description": "URL of webpage",
                "required": true
            }
        }
    }
    
    
    
    If a you choose to call a function ONLY reply in the following format:
    <{start_tag}={function_name}>{parameters}{end_tag}
    where
    
    start_tag => `<function`
    parameters => a JSON dict with the function argument name as key and function argument value as value.
    end_tag => `</function>`
    
    Here is an example,
    <function=example_function_name>{"example_name": "example_value"}</function>
    
    Reminder:
    - Function calls MUST follow the specified format
    - Required parameters MUST be specified
    - Only call one function at a time
    - Put the entire function call reply on one line
    - Always add your sources when using search results to answer the user query
    
    You are a helpful assistant.<|eot_id|><|start_header_id|>user<|end_header_id|>
    
    To begin our journey please navigate to doordash<|eot_id|><|start_header_id|>assistant<|end_header_id|>
    """

    f = modal.Function.lookup(APP_NAME, "Model.inference")
    result = f.remote(prompt)
    print(result)
