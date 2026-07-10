import os
import pprint
import dotenv
from httpx import Client, Timeout
import json
import model
import tools
dotenv.load_dotenv()

deepseek_secret = os.environ.get("DEEPSEEK_SECRET");
if not deepseek_secret:
    print("deepseek_secret not configured")
    exit(1)
base_url = "https://api.deepseek.com/chat/completions"
httpx_client = Client(headers={"Authorization":f"Bearer {deepseek_secret}", "Content-Type":"application/json"}, timeout=Timeout(60))

def chat (messages:list[model.Message], system_prompt:str):
    messages = [model.Message(role="system", content=system_prompt)] + messages
    res = httpx_client.post(
        url=base_url,
        json={
            "model": "deepseek-v4-flash",
            "messages": [msg.model_dump(exclude_none=True) for msg in messages],
            "thinking": {"type": "disabled"},
            "stream": False,
            "tools":tools.tools
        }
    )
    if res.is_success is False:
        return model.ChatResponse(success=False, data=None, error=res.text)
    parsed = model.ChatCompletionResponse.model_validate(res.json())
    return model.ChatResponse(success=True, data=parsed, error=None)

def compact (messages:list[model.Message]):
    messages = [model.Message(role="system", content="Summarize this agent conversation segment. " \
    "Preserve concrete facts the agent needs later: " \
    "file paths, values, command results, decisions made. " \
    "Drop chatter. Be terse. " \
    "Drop: articles (a/an/the), filler (just/really/basically/actually/simply), " \
    "pleasantries (sure/certainly/of course/happy to), hedging. " \
    "Fragments OK. Short synonyms (big not extensive, fix not 'implement a solution for')")] + messages

    res = httpx_client.post(
        url=base_url,
        json={
            "model": "deepseek-v4-flash",
            "messages": [msg.model_dump(exclude_none=True) for msg in messages],
            "thinking": {"type": "disabled"},
            "stream": False,
        }
    )
    if res.is_success is False:
        return model.ChatResponse(success=False, data=None, error=res.text)
    parsed = model.ChatCompletionResponse.model_validate(res.json())
    return model.ChatResponse(success=True, data=parsed, error=None)



def extractor (messages:list[model.Message], existing_facts):
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

    res = httpx_client.post(
        url=base_url,
        json={
            "model": "deepseek-v4-flash",
            "messages": [msg.model_dump(exclude_none=True) for msg in messages],
            "thinking": {"type": "disabled"},
            "stream": False,
        }
    )
    if res.is_success is False:
        return model.ChatResponse(success=False, data=None, error=res.text)
    parsed = model.ChatCompletionResponse.model_validate(res.json())
    print(parsed.choices[0].message.content)
    return model.ChatResponse(success=True, data=parsed, error=None)



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