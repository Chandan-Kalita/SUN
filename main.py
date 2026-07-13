import json
import uuid

import client
import log
import model
import readline

import tools

TOKEN_BUDGET = 20000
KEEP_RECENT = 6
MAX_TOOL_CALL_LIMIT= 10
REPEAT_FAILURE_LIMIT = 3
CONSECUTIVE_FAILURE_LIMIT = 5
SESSION_ID=uuid.uuid4()
LOG_PATH = log.init(SESSION_ID)
print(f"[log] {LOG_PATH}")



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

def append_message(message:model.Message):
    messages.append(message)
    tool_calls = None
    if message.tool_calls:
        tool_calls = [{"name": tc.function.name, "args": log.clip(tc.function.arguments, 300)} for tc in message.tool_calls]
    log.event("message", role=message.role, content=log.clip(message.content),
              tool_calls=tool_calls, tool_call_id=message.tool_call_id, depth=len(messages))


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
        log.event("compaction", ok=True, summarized=len(conversations),
                  messages_before=before, messages_after=len(messages), chars_in=len(text))
    else:
        print(f"[compaction] failed: {response.error}")
        log.event("compaction", ok=False, error=log.clip(response.error, 300))


    permanent_facts,session_facts = get_memories()

    all_facts = {"permanent_facts":permanent_facts,"session_facts":session_facts}

    extractor_response = client.extractor(messages=[model.Message(role="user", content=text)], existing_facts=json.dumps(all_facts))
    if extractor_response.success is False:
        print(f"[extractor] failed: {extractor_response.error}")
        return

    raw = extractor_response.data.choices[0].message.content or ""
    raw = raw.strip().removeprefix("```json").removesuffix("```").strip()
    try:
        new_facts = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"[extractor] skipped: malformed JSON ({e}); got {raw[:200]!r}")
        return
    if not isinstance(new_facts, dict):
        print(f"[extractor] skipped: expected an object, got {type(new_facts).__name__}")
        return

    learned = {}
    for store, key in ((permanent_facts, "permanent_facts"), (session_facts, "session_facts")):
        section = new_facts.get(key)
        if isinstance(section, dict):
            store.update(section)
            learned[key] = list(section)
        elif section is not None:
            print(f"[extractor] ignored {key}: expected an object, got {type(section).__name__}")
    log.event("extractor", ok=True, learned=learned or None)

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
                return tools.run_command(command=args["command"], timeout=args["timeout"], shell=args.get("shell", False))
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
            log.event("tool_call", name=tool_call.function.name,
                      args=log.clip(tool_call.function.arguments, 300),
                      ok=result.ok, exit_code=result.exit_code, duration_ms=result.duration_ms,
                      promoted_to_shell=bool(result.note) or None,
                      effects=log.clip(result.effects, 300), error=log.clip(result.error, 300),
                      output_chars=len(result.output) if result.output else 0,
                      iteration=iter_count)
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
            log.event("stuck", reason=log.clip(stuck_reason, 300), iteration=iter_count,
                      action="abort" if guidance is None else "guided",
                      guidance=log.clip(guidance))
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
turn = 0

while True:
    user_q = input("->")
    turn += 1
    log.event("turn_start", turn=turn, prompt=log.clip(user_q))
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
    log.event("turn_end", turn=turn, prompt_tokens=usage.prompt_tokens,
              completion_tokens=usage.completion_tokens, total_tokens=usage.total_tokens,
              cached_tokens=cache_hit, budget_pct=round(budget_pct, 1), messages=len(messages))
    maybe_compact(usage.prompt_tokens)
    