import json
import pprint

import client
import model
import readline

import tools

TOKEN_BUDGET = 6000
KEEP_RECENT = 6
messages : list[model.Message] = [model.Message(role="system", content="You are a helpfull assistant.")]
# what are the files in my current dir
# whats my current dir and what are the files
def append_message(message:model.Message):
    messages.append(message)
    # pprint.pprint(messages)
    with open("chain.txt", "w") as f:
        f.write(str(pprint.pformat([msg.model_dump(exclude_none=True) for msg in messages])))


def run_compaction():
    global messages
    system_message = messages[0]
    cut =  len(messages)-KEEP_RECENT
    while messages[cut].role == "tool":
        cut -= 1
    if cut < 2:
        return
    conversations = messages[1:cut]
    text = ""
    for conv in conversations:
        text+= f"\n{conv.role}: {conv.content}"

    response = client.compact([system_message, model.Message(role="user", content=text)])
    if response.success is True:
        messages = [system_message] + [response.data.choices[0].message] + messages[cut:]





def call_tool(tool_to_call:model.ToolCall):
    match tool_to_call.function.name:
        case "run_command":
            args = tool_to_call.function.arguments
            args = json.loads(args)
            res = tools.run_command(command=args["command"], timeout=args["timeout"])
            return res
        case _:
            return "no tool found"


def tool_call_loop(data:model.ChatCompletionResponse):
    choice = data.choices[0]
    response_msg = choice.message
    append_message(response_msg)
    for tool_call in response_msg.tool_calls:
        tool_output = call_tool(tool_call)
        append_message(model.Message(role="tool",content=tool_output, tool_call_id=tool_call.id))
        
    tool_response = client.chat(messages=messages)
    if tool_response.success is False:
        print(tool_response.error)
        raise Exception(tool_response.error)
    if tool_response.data.choices[0].finish_reason == "tool_calls":
        return tool_call_loop(tool_response.data)
    return tool_response.data.choices[0].message

token_usage = []

while True:
    user_q = input("->")
    append_message(model.Message(role="user",content=user_q))
    response = client.chat(messages=messages)
    if response.success is False:
        print(response.error)
        break
    data = response.data
    choice = data.choices[0]
    response_msg = choice.message
    if choice.finish_reason == "tool_calls":
        response_msg = tool_call_loop(data=data)

    append_message(response_msg)
    print(response_msg.content)
    token_usage.append(data.usage.prompt_tokens)
    print(f"\n\nToken Usage: prompt-{data.usage.prompt_tokens}, answer-{data.usage.completion_tokens}, total-{data.usage.total_tokens}\n\n")
    print(f"\n Token usage trend: {token_usage}")
    if data.usage.prompt_tokens > TOKEN_BUDGET:
        run_compaction()