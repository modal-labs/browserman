import re
import typing
from pathlib import Path

import modal
import modal.gpu
from PIL import Image

from bs4 import BeautifulSoup, Tag

BUTTON_INSTRUCTION = """Use the function 'click_button' to: To click a button on the web page.
{
    "name": "click_button",
    "description": "Click a button on a web page in a browser",
    "parameters": {
        "button_text": {
            "param_type": "string",
            "description": "button text",
            "required": true
        }
        "reason": {
            "param_type": "string",
            "description": "reason for clicking this button",
            "required": true
        }
    }
}"""

PROMPT_TEMPLATE = """\
<|begin_of_text|><|start_header_id|>system<|end_header_id|>

You have access to the following functions to interact with web pages using a web browser:

Use the function 'navigate_to' to: To open a web page
{
    "name": "navigate_to",
    "description": "Navigate to a root web page in a browser",
    "parameters": {
        "url": {
            "param_type": "string",
            "description": "URL of homepage",
            "required": true
        }
    }
}

Use the function 'go_back' to: To navigate back to the previous web page
{
    "name": "go_back",
    "description": "Navigate back to the previous web page",
    "parameters": {
        "go_back": {
            "param_type": "string",
            "description": "Reason for going back",
            "required": true
        }
    }
}

BUTTON_INSTRUCTION_PLACEHOLDER

Use the function 'final_answer' to: To come up with a final text response to the user's query based on the web page content.
{
    "name": "final_answer",
    "description": "Respond to the user's query based on the web page content",
    "parameters": {
        "final_answer": {
            "param_type": "string",
            "description": "final answer",
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

Here is an example of navigating to a URL:
<function=navigate_to>{"url": "https://food.com"}</function>

You are an obedient and helpful assistant that excels in following instructions to the letter. 

Please provide a sequence of steps to take.<|eot_id|><|start_header_id|>user<|end_header_id|>
CURRENT_DOM_PLACEHOLDER

CURRENT_URL_PLACEHOLDER

SCREENSHOT_PLACEHOLDER

Reminder:
- Function calls MUST follow the specified format
- Required parameters MUST be specified
- Only call one function at a time
- Put the entire function call reply on one line
- Do not try and do the same thing over and over again
- Only provide the next step to take
- DO NOT REPEAT THE SAME STEPS OVER AND OVER
- DO NOT TRY A FAILED STEP AGAIN

USER_QUERY_PLACEHOLDER<|eot_id|><|start_header_id|>assistant<|end_header_id|>
HISTORY_PLACEHOLDER
Step STEP_PLACEHOLDER: """


def get_prompt(
    query: str, current_url: str, current_dom: str, history: typing.Sequence[str], use_buttons: bool = True
) -> str:
    prompt = PROMPT_TEMPLATE.replace("USER_QUERY_PLACEHOLDER", query)
    prompt = prompt.replace("STEP_PLACEHOLDER", str(len(history) + 1))
    if history:
        steps = "\n".join(f"Step {i + 1}: {action}" for i, action in list(enumerate(history))[-3:])
        prompt = prompt.replace("HISTORY_PLACEHOLDER", steps)
    else:
        prompt = prompt.replace("HISTORY_PLACEHOLDER", "")

    if current_dom:
        soup = BeautifulSoup(current_dom, features="html.parser")
        links = []
        for t in soup.find_all("script"):
            t.extract()
        for t in soup.find_all("svg"):
            t.extract()
        for e in soup.descendants:
            if isinstance(e, Tag):
                unwanted_attrs = [
                    attr
                    for attr in e.attrs
                    if attr != "href" and attr != "content" and attr != "id"
                ]
                for attr in unwanted_attrs:
                    del e[attr]
        for t in soup.find_all("a"):
            links.append(t)
        links = "\n".join([str(e) for e in links])
        links = re.sub(r'\?cursor=[^"]+"', "", links)
        prompt = prompt.replace(
            "CURRENT_DOM_PLACEHOLDER", "" # f"Links on current web page: {links}"
        )
    else:
        prompt = prompt.replace("CURRENT_DOM_PLACEHOLDER", "")

    if current_url:
        prompt = prompt.replace(
            "CURRENT_URL_PLACEHOLDER", f"Current URL: {current_url}"
        )
        prompt = prompt.replace(
            "SCREENSHOT_PLACEHOLDER", "Screenshot from current web page:<|image|>"
        )
    else:
        prompt = prompt.replace("CURRENT_URL_PLACEHOLDER", "")
        prompt = prompt.replace("SCREENSHOT_PLACEHOLDER", "")

    if use_buttons:
        prompt = prompt.replace("BUTTON_INSTRUCTION_PLACEHOLDER", BUTTON_INSTRUCTION)
    else:
        prompt = prompt.replace("BUTTON_INSTRUCTION_PLACEHOLDER", "")

    return prompt


def main():
    APP_NAME = "browserman"
    QUERY = "Please order me food from doordash"

    f = modal.Function.lookup(APP_NAME, "Model.inference")

    prompt_00 = get_prompt(QUERY, "", "", [])
    print()
    print("Prompt 1")
    print("======")
    print(prompt_00)
    step_01 = f.remote(prompt_00, None)
    print()
    print("Step 1")
    print("======")
    print(step_01)

    prompt_01 = get_prompt(
        QUERY,
        "https://www.doordash.com/home/",
        Path("doordash_01.html").read_text(),
        ['<function=navigate_to>{"url": "https://www.doordash.com/"}</function>'],
    )
    print()
    print("Prompt 2")
    print("======")
    print(prompt_01)
    step_02 = f.remote(prompt_01, Image.open("doordash_01.png"))
    print()
    print("Step 2")
    print("======")
    print(step_02)


if __name__ == "__main__":
    main()
