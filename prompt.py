from pathlib import Path
from textwrap import dedent

import modal
import modal.gpu
from PIL import Image

APP_NAME = "browserman"

if __name__ == "__main__":
    prompt = dedent("""\
    <|begin_of_text|><|start_header_id|>system<|end_header_id|>
    
    You have access to the following functions to interact with web pages using a web browser:
    
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
    
    Use the function 'click_button' to: To click a button on the web page.
    {
        "name": "click_button",
        "description": "Click a button on a web page in a browser",
        "parameters": {
            "button_text": {
                "param_type": "string",
                "description": "button text",
                "required": true
            }
        }
    }
    
    If a you choose to call a function ONLY reply in the following format with no prefix or suffix:
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
    
    You are an obedient and helpful assistant that excels in following instructions to the letter. 
    
    Previous step: <function=click_button>{"button_text": "Empanada Mama"}</function>

    Screenshot from current step:<|image|>
    DOM of current step:CURRENT_DOM
    
    Please provide the next function to call.<|eot_id|><|start_header_id|>user<|end_header_id|>
    Please order me food from doordash.<|eot_id|><|start_header_id|>assistant<|end_header_id|>
    """)

    current_dom = Path("doordash_03.html").read_text()

    from bs4 import BeautifulSoup, Tag

    soup = BeautifulSoup(current_dom)
    extracted = []
    for t in soup.find_all("script"):
        t.extract()
    for t in soup.find_all("svg"):
        t.extract()
    for e in soup.descendants:
        if isinstance(e, Tag):
            unwanted_attrs = [attr for attr in e.attrs if attr != "href" and attr != "content" and attr != "id"]
            for attr in unwanted_attrs:
                del e[attr]
    for t in soup.find_all("a"):
        extracted.append(t)

    cleaned_dom = "\n".join([str(e) for e in extracted])
    print(f"cleaned dom len: {len(cleaned_dom)}")

    # print(cleaned_dom)

    prompt = prompt.replace("CURRENT_DOM", cleaned_dom)

    # * <function=click_button>{"button_text": "Delivery Fees: Under $3"}</function>

    image_01 = Image.open("doordash_01.png")
    image_02 = Image.open("doordash_02.png")
    image_03 = Image.open("doordash_03.png")

    f = modal.Function.lookup(APP_NAME, "Model.inference")
    result = f.remote(prompt, image_03)
    print(result)
