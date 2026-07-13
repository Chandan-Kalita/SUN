import json
import pprint
import uuid

import client
import model
import readline

import tools

TOKEN_BUDGET = 20000
KEEP_RECENT = 6
MAX_TOOL_CALL_LIMIT= 10
REPEAT_FAILURE_LIMIT = 3
CONSECUTIVE_FAILURE_LIMIT = 5
SESSION_ID=uuid.uuid4()



def get_memories():
    try:
        with open("permanent_facts.json","r") as file:
            permanent_facts = json.load(file)
    except FileNotFoundError:
        permanent_facts={}

    try:
        with open(f"session_facts_{SESSION_ID}.json","r") as file:
            session_facts = json.load(file)
    except FileNotFoundError:
        session_facts = {}
    return permanent_facts, session_facts



def get_updated_system_prompt():
    permanent_facts,session_facts = get_memories()

    SYSTEM_PROMPT = f"""
    You are a helpfull assistant.
    Below are some facts about the current user. use them when needed. if users name is in facts then use that while greeting
    permanent_facts:{permanent_facts}
    session_facts:{session_facts}
    """
    return SYSTEM_PROMPT

messages : list[model.Message] = []
# what are the files in my current dir
# whats my current dir and what are the files
def append_message(message:model.Message):
    messages.append(message)
    # pprint.pprint(messages)
    with open("chain.txt", "w") as f:
        f.write(str(pprint.pformat([msg.model_dump(exclude_none=True) for msg in messages])))


def run_compaction():
    global messages
    cut =  len(messages)-KEEP_RECENT
    while cut >= 1 and (messages[cut].role == "tool" or (messages[cut - 1].role == "assistant" and messages[cut - 1].tool_calls)):
        cut -= 1
    if cut < 2:
        print("[compaction] skipped: not enough messages to summarize")
        return
    conversations = messages[:cut]
    text = ""
    for conv in conversations:
        content = conv.content
        if conv.tool_calls:
            calls = "; ".join(f"{c.function.name}({c.function.arguments})" for c in conv.tool_calls)
            content = f"{content or ''} [tool_calls: {calls}]"
        text+= f"\n{conv.role}: {content}"

    before = len(messages)
    response = client.compact([model.Message(role="user", content=text)])
    if response.success is True:
        messages = [response.data.choices[0].message] + messages[cut:]
        print(f"[compaction] summarized {len(conversations)} messages -> 1; total messages {before} -> {len(messages)}")
    else:
        print(f"[compaction] failed: {response.error}")


    permanent_facts,session_facts = get_memories()

    all_facts = {"permanent_facts":permanent_facts,"session_facts":session_facts}

    extractor_response = client.extractor(messages=[model.Message(role="user", content=text)], existing_facts=json.dumps(all_facts))
    if extractor_response.success is True:
        raw = extractor_response.data.choices[0].message.content or ""
        raw = raw.strip().removeprefix("```json").removesuffix("```").strip()
        new_facts = json.loads(raw)
        new_permanent_facts = new_facts["permanent_facts"]
        new_session_facts = new_facts["session_facts"]
        for key,val in new_permanent_facts.items():
            permanent_facts[key] = val
        for key,val in new_session_facts.items():
            session_facts[key] = val

        with open("permanent_facts.json", "w") as file:
            file.write(json.dumps(permanent_facts))
        with open(f"session_facts_{SESSION_ID}.json", "w") as file:
            file.write(json.dumps(session_facts))
    



def maybe_compact(token_count:int):
    if token_count > TOKEN_BUDGET:
        print(f"[compaction] triggered: prompt tokens {token_count} exceeded budget {TOKEN_BUDGET}")
        run_compaction()

def call_tool(tool_to_call:model.ToolCall) -> model.ToolResult:
    try:
        args = json.loads(tool_to_call.function.arguments)
    except json.JSONDecodeError as e:
        return model.ToolResult(ok=False, error=f"invalid tool call arguments (not valid JSON): {e}")

    try:
        match tool_to_call.function.name:
            case "run_command":
                return tools.run_command(command=args["command"], timeout=args["timeout"])
            case "read_chunk":
                return tools.read_chunk(file_path=args["file_path"], offset=args["offset"], char_limit=args["char_limit"])
            case _:
                return model.ToolResult(ok=False, error=f"no tool named {tool_to_call.function.name}")
    except KeyError as e:
        return model.ToolResult(ok=False, error=f"missing required argument {e}")


def call_signature(tool_call:model.ToolCall) -> str:
    try:
        args = json.dumps(json.loads(tool_call.function.arguments), sort_keys=True)
    except json.JSONDecodeError:
        args = tool_call.function.arguments
    return f"{tool_call.function.name}({args})"


def ask_user_unstick(reason:str) -> str | None:
    print(f"\n[stuck] {reason}")
    guidance = input("guide sun (or press enter to abort this turn): ").strip()
    if not guidance:
        print("[stuck] turn abandoned")
        return None
    return guidance


def tool_call_loop(data:model.ChatCompletionResponse):
    iter_count = 1
    fail_counts:dict[str,int] = {}
    consecutive_failures = 0

    while True:
        response_msg = data.choices[0].message
        append_message(response_msg)
        if response_msg.content:
            print(f"\nchandan: {response_msg.content}\n")

        stuck_reason = None
        for tool_call in response_msg.tool_calls or []:
            result = call_tool(tool_call)
            append_message(model.Message(role="tool", content=result.render(), tool_call_id=tool_call.id))

            if result.ok:
                consecutive_failures = 0
                continue

            consecutive_failures += 1
            sig = call_signature(tool_call)
            fail_counts[sig] = fail_counts.get(sig, 0) + 1
            detail = result.error or f"exit_code {result.exit_code}"
            if fail_counts[sig] >= REPEAT_FAILURE_LIMIT:
                stuck_reason = f"{sig} failed {fail_counts[sig]}x -- last error: {detail}"
            elif consecutive_failures >= CONSECUTIVE_FAILURE_LIMIT:
                stuck_reason = f"{consecutive_failures} tool calls failed in a row -- last: {sig} -> {detail}"

        if stuck_reason is None and iter_count > MAX_TOOL_CALL_LIMIT:
            stuck_reason = f"reached max tool call limit ({MAX_TOOL_CALL_LIMIT}) without finishing"

        if stuck_reason:
            guidance = ask_user_unstick(stuck_reason)
            if guidance is None:
                return {"success":False, "data":data}
            append_message(model.Message(role="user", content=guidance))
            fail_counts.clear()
            consecutive_failures = 0
            iter_count = 1

        tool_response = client.chat(messages=messages, system_prompt=get_updated_system_prompt())
        if tool_response.success is False:
            print(tool_response.error)
            return {"success":False, "data":data}

        if tool_response.data.choices[0].finish_reason != "tool_calls":
            return {"success":True,"data": tool_response.data}

        data = tool_response.data
        iter_count += 1

token_usage = []

while True:
    user_q = input("->")
    append_message(model.Message(role="user",content=user_q))
    response = client.chat(messages=messages, system_prompt=get_updated_system_prompt())
    if response.success is False:
        print(response.error)
        continue
    data = response.data
    
    if data.choices[0].finish_reason == "tool_calls":
        tool_response = tool_call_loop(data=data)
        if tool_response["success"] is False:
            maybe_compact(tool_response["data"].usage.prompt_tokens)
            continue
        data = tool_response["data"]

    choice = data.choices[0]
    response_msg = choice.message

    append_message(response_msg)
    print(f"\nchandan: {response_msg.content}\n")

    usage = data.usage
    token_usage.append(usage.prompt_tokens)
    budget_pct = usage.prompt_tokens / TOKEN_BUDGET * 100
    cache_hit = usage.prompt_cache_hit_tokens
    cache_info = f", cache-hit {cache_hit}/{usage.prompt_tokens} ({cache_hit / usage.prompt_tokens:.0%})" if cache_hit is not None and usage.prompt_tokens else ""
    print(
        f"[usage] prompt {usage.prompt_tokens} | completion {usage.completion_tokens} | "
        f"total {usage.total_tokens} | budget {budget_pct:.0f}% ({usage.prompt_tokens}/{TOKEN_BUDGET})"
        f"{cache_info} | messages {len(messages)}"
    )
    print(f"[usage] trend (last 10): {token_usage[-10:]}")
    maybe_compact(usage.prompt_tokens)
    