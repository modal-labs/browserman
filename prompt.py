import re
import typing
from pathlib import Path
from textwrap import dedent

import modal
import modal.gpu
from PIL import Image

from bs4 import BeautifulSoup, Tag

PROMPT_TEMPLATE = """\
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


Please provide a sequence of steps to take.<|eot_id|><|start_header_id|>user<|end_header_id|>
SCREENSHOT_PLACEHOLDER
CURRENT_DOM_PLACEHOLDER

HISTORY_PLACEHOLDER

CURRENT_URL_PLACEHOLDER

USER_QUERY_PLACEHOLDER<|eot_id|><|start_header_id|>assistant<|end_header_id|>
Step STEP_PLACEHOLDER:
"""


def prompt(query: str, current_url: str, current_dom: str, history: typing.Sequence[str]) -> str:
    prompt = PROMPT_TEMPLATE.replace("USER_QUERY_PLACEHOLDER", query)
    prompt = prompt.replace("STEP_PLACEHOLDER", str(len(history) + 1))
    if history:
        steps = "\n".join(f"Step {i + 1}: {action}" for i, action in enumerate(history))
        prompt = prompt.replace("HISTORY_PLACEHOLDER", f"Past steps: \n{steps}")
    else:
        prompt = prompt.replace("HISTORY_PLACEHOLDER", "")

    if current_dom:
        soup = BeautifulSoup(current_dom)
        extracted = []
        for t in soup.find_all("script"):
            t.extract()
        for t in soup.find_all("svg"):
            t.extract()
        for e in soup.descendants:
            if isinstance(e, Tag):
                unwanted_attrs = [attr for attr in e.attrs if
                                  attr != "href" and attr != "content" and attr != "id"]
                for attr in unwanted_attrs:
                    del e[attr]
        for t in soup.find_all("a"):
            extracted.append(t)
        cleaned_dom = "\n".join([str(e) for e in extracted])
        cleaned_dom = re.sub(r'\?cursor=[^"]+"', "", cleaned_dom)
        prompt = prompt.replace("CURRENT_DOM_PLACEHOLDER", f"DOM of current web page: {cleaned_dom}")
    else:
        prompt = prompt.replace("CURRENT_DOM_PLACEHOLDER", "")

    if current_url:
        prompt = prompt.replace("CURRENT_URL_PLACEHOLDER", f"Current URL: {current_url}")
        prompt = prompt.replace("SCREENSHOT_PLACEHOLDER", "Screenshot from current web page:<|image|>")
    else:
        prompt = prompt.replace("CURRENT_URL_PLACEHOLDER", "")
        prompt = prompt.replace("SCREENSHOT_PLACEHOLDER", "")

    return prompt


def main():
    APP_NAME = "browserman"
    QUERY = "Please order me food from doordash"

    f = modal.Function.lookup(APP_NAME, "Model.inference")

    # prompt_00 = prompt(QUERY, "", "", [])
    # print("Prompt 1")
    # print("======")
    # print(prompt_00)
    # step_01 = f.remote(prompt_00, None)
    # print("Step 1")
    # print("======")
    # print(step_01)

    prompt_01 = prompt(QUERY, "https://www.doordash.com/home/",
                       Path("doordash_01.html").read_text(),
                       ['<function=navigate_to>{"url": "https://www.doordash.com/"}</function>'])
    print("Prompt 2")
    print("======")
    print(prompt_01)
    step_02 = f.remote(prompt_01, Image.open("doordash_01.png"))
    print("Step 2")
    print("======")
    print(step_02)


if __name__ == "__main__":
    main()


def _old_hardcoded_prompt():
    APP_NAME = "browserman"

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
    
    
    Please provide a sequence of steps to take.<|eot_id|><|start_header_id|>user<|end_header_id|>
    Screenshot from current web page:<|image|>
    DOM of current web page:CURRENT_DOM
    
    Past steps:
    Step 1: <function=navigate_to>{"url": "https://www.doordash.com/"}</function>
    Step 2: <function=click_button>{"button_text": "Delivery Fees: Under $3"}</function>
    Step 3: <function=click_button>{"button_text": "Empanada Mama"}</function>
    
    Current URL: https://www.doordash.com/store/empanada-mama-new-york-544094/
    
    Please order me food from doordash.<|eot_id|><|start_header_id|>assistant<|end_header_id|>
    Step 4:
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

    prompt = prompt.replace("CURRENT_DOM", cleaned_dom)

    Image.open("doordash_01.png")
    Image.open("doordash_02.png")
    image_03 = Image.open("doordash_03.png")

    f = modal.Function.lookup(APP_NAME, "Model.inference")
    result = f.remote(prompt, image_03)
    print(result)
