"""GAIA behavior adapted from the pinned OpenHands benchmark snapshot."""

from pathlib import Path

from .schema import IMAGE_SUFFIXES, TaskRequest


def instruction(request: TaskRequest):
    text = f"""You have one question to answer. It is paramount that you provide a correct answer.
Give it all you can: I know for a fact that you have access to all the relevant tools to solve it and find the correct answer (the answer does exist). Failure or 'I cannot answer' or 'None found' will not be tolerated, success will be rewarded.
You must make sure you find the correct answer! You MUST strictly follow the task-specific formatting instructions for your final answer.
Here is the task:
{request.question}
"""
    if (
        len(request.attachments) == 1
        and Path(request.attachments[0].name).suffix.lower() in IMAGE_SUFFIXES
    ):
        text += "Image: To solve this task you will have to use the image shown below.\n\n"
    elif len(request.attachments) == 1:
        name = request.attachments[0].name
        text += f"To solve this task you will have to use the attached file provided in the workspace at location: /workspace/{name}\n\n"
    elif request.attachments:
        names = ", ".join(f"/workspace/{item.name}" for item in request.attachments)
        text += f"To solve this task you will have to use the attached files provided in the workspace at locations: {names}\n\n"
    text += """IMPORTANT: When seeking information from a website, REFRAIN from arbitrary URL navigation. You should utilize the designated search engine tool with precise keywords to obtain relevant URLs or use the specific website's search interface. DO NOT navigate directly to specific URLs as they may not exist.

For example: if you want to search for a research paper on Arxiv, either use the search engine tool with specific keywords or navigate to arxiv.org and then use its interface.
IMPORTANT: You should NEVER ask for Human Help.
IMPORTANT: Please encapsulate your final answer (answer ONLY) within <solution> and </solution> and report it back to users via a message, instead of the 'finish' tool. Your answer will be evaluated using string matching approaches so it important that you STRICTLY adhere to the output formatting instructions specified in the task (e.g., alphabetization, sequencing, units, rounding, decimal places, etc.)
For example: The answer to the question is <solution> 42 </solution>.
IMPORTANT: Your final answer should be a number OR as few words as possible OR a comma separated list of numbers and/or strings. If you are asked for a number, express it numerically (i.e., with digits rather than words), do not use commas, and do not include units such as $ or percent signs unless specified otherwise. If you are asked for a string, don't use articles, neither abbreviations (e.g. for cities). If you are asked for a comma separated list, apply the above rules depending of whether the element to be put in the list is a number or a string.
"""
    return text


def fake_user_response(previous_responses=0):
    message = (
        "Please continue working on the task on whatever approach you think is suitable.\n"
        "When you think you have solved the question, please use the finish tool and "
        "include your final answer in the message parameter of the finish tool.\n"
        "IMPORTANT: YOU SHOULD NEVER ASK FOR HUMAN HELP.\n"
    )
    if previous_responses >= 1:
        message += 'If you want to give up, use the "finish" tool to finish the interaction.\n'
    return message
