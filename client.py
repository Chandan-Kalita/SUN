import os
import random
import sys
import time

import dotenv
import httpx
from httpx import Client, Timeout
from pydantic import ValidationError

import model
import tools

dotenv.load_dotenv()

deepseek_secret = os.environ.get("DEEPSEEK_SECRET");
if not deepseek_secret:
    print("deepseek_secret not configured")
    exit(1)
base_url = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-v4-flash"

MAX_ATTEMPTS = 4
BASE_DELAY = 1.0
MAX_DELAY = 30.0
RETRY_STATUS = {429, 500, 502, 503, 504}

httpx_client = Client(
    headers={"Authorization": f"Bearer {deepseek_secret}", "Content-Type": "application/json"},
    timeout=Timeout(connect=10, read=120, write=30, pool=10),
)


def _retry_after(res: httpx.Response) -> float | None:
    raw = res.headers.get("Retry-After")
    if raw is None:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        # The header also allows an HTTP-date, which we don't honor.
        return None


def _backoff(attempt: int) -> float:
    # Full jitter, so concurrent retries don't resynchronize.
    return random.uniform(0, min(MAX_DELAY, BASE_DELAY * 2 ** attempt))


def _post(messages: list[model.Message], **payload_extra) -> model.ChatResponse:
    payload = {
        "model": MODEL,
        "messages": [msg.model_dump(exclude_none=True) for msg in messages],
        "thinking": {"type": "disabled"},
        "stream": False,
        **payload_extra,
    }

    last_error = "no attempts made"
    for attempt in range(MAX_ATTEMPTS):
        delay = None
        try:
            res = httpx_client.post(url=base_url, json=payload)
        except (httpx.TimeoutException, httpx.TransportError) as e:
            last_error = f"{type(e).__name__}: {e}"
            delay = _backoff(attempt)
        else:
            if res.is_success:
                try:
                    return model.ChatResponse(
                        success=True,
                        data=model.ChatCompletionResponse.model_validate(res.json()),
                        error=None,
                    )
                except (ValueError, ValidationError) as e:
                    return model.ChatResponse(
                        success=False, data=None, error=f"unparseable response: {e}; body: {res.text[:500]}"
                    )
            last_error = f"HTTP {res.status_code}: {res.text}"
            if res.status_code not in RETRY_STATUS:
                return model.ChatResponse(success=False, data=None, error=last_error)
            delay = _retry_after(res)
            if delay is None:
                delay = _backoff(attempt)

        if attempt == MAX_ATTEMPTS - 1:
            break
        print(
            f"[retry] attempt {attempt + 1}/{MAX_ATTEMPTS} failed ({last_error[:120]}), "
            f"sleeping {delay:.1f}s",
            file=sys.stderr,
        )
        time.sleep(delay)

    return model.ChatResponse(
        success=False, data=None, error=f"gave up after {MAX_ATTEMPTS} attempts; last error: {last_error}"
    )


def chat(messages: list[model.Message], system_prompt: str):
    messages = [model.Message(role="system", content=system_prompt)] + messages
    return _post(messages, tools=tools.tools)


def compact(messages: list[model.Message]):
    messages = [model.Message(role="system", content="Summarize this agent conversation segment. " \
    "Preserve concrete facts the agent needs later: " \
    "file paths, values, command results, decisions made. " \
    "Drop chatter. Be terse. " \
    "Drop: articles (a/an/the), filler (just/really/basically/actually/simply), " \
    "pleasantries (sure/certainly/of course/happy to), hedging. " \
    "Fragments OK. Short synonyms (big not extensive, fix not 'implement a solution for')")] + messages
    return _post(messages)


def extractor(messages: list[model.Message], existing_facts):
    messages = [model.Message(role="system", content=f"""You are a fact extractor. Given a conversation history, extract durable facts into two categories.

PERMANENT FACTS: Identity, preferences, environment details that persist across sessions.
Examples: name, role, OS, preferred tools, skill level, server hostnames.

SESSION FACTS: Current task context, what's been tried, what worked/failed, active goals.
Examples: "installing nginx on port 8080", "port 443 blocked by firewall", "switched from apt to snap".

You already have these stored facts:
{existing_facts}

Return ONLY a JSON object with this exact structure, no explanation, no markdown:
{{"permanent_facts": {{}}, "session_facts": {{}}}}

Rules:
- Only include NEW facts not already captured, or UPDATED facts where the old value is now wrong.
- If nothing new to extract, return empty dicts for both.
- Keys should be short, snake_case descriptors.
- Values should be concise strings or simple types.
- Do NOT include conversational fluff, opinions, or anything the user said casually without intent.""")] + messages

    res = _post(messages)
    if res.success:
        print(res.data.choices[0].message.content)
    return res


# {
#     'id': '68ff3772-5286-4c88-8be8-83a994405985',
#     'object': 'chat.completion',
#     'created': 1782933026,
#     'model': 'deepseek-v4-flash',
#     'choices': [
#                 {'index': 0,
#                 'message': {
#                     'role': 'assistant',
#                     'content': 'Hi there! How can I help you today?'
#                     },
#                 'logprobs': None,
#                 'finish_reason': 'stop'
#                 }
#             ],
#     'usage': {
#         'prompt_tokens': 12,
#         'completion_tokens': 10,
#         'total_tokens': 22,
#         'prompt_tokens_details': {
#             'cached_tokens': 0
#             },
#         'prompt_cache_hit_tokens': 0,
#         'prompt_cache_miss_tokens': 12
#         },
#     'system_fingerprint': 'fp_8b330d02d0_prod0820_fp8_kvcache_20260402'
# }


# {'choices': [{'finish_reason': 'tool_calls',
#               'index': 0,
#               'logprobs': None,
#               'message': {'content': '',
#                           'role': 'assistant',
#                           'tool_calls': [{'function': {'arguments': '{"command": '
#                                                                     '["ls", '
#                                                                     '"-la"], '
#                                                                     '"timeout": '
#                                                                     '10}',
#                                                        'name': 'run_command'},
#                                           'id': 'call_00_VB343PV6q2EH1sOAeg4B0774',
#                                           'index': 0,
#                                           'type': 'function'}]}}],
#  'created': 1782937218,
#  'id': '15f521c9-a149-4624-9af5-732caff60f51',
#  'model': 'deepseek-v4-flash',
#  'object': 'chat.completion',
#  'system_fingerprint': 'fp_8b330d02d0_prod0820_fp8_kvcache_20260402',
#  'usage': {'completion_tokens': 65,
#            'prompt_cache_hit_tokens': 384,
#            'prompt_cache_miss_tokens': 11,
#            'prompt_tokens': 395,
#            'prompt_tokens_details': {'cached_tokens': 384},
#            'total_tokens': 460}}
