from typing import Any

from pydantic import BaseModel, Field

class FunctionTool(BaseModel):
    arguments:str
    name:str

class ToolCall(BaseModel):
    function:FunctionTool
    id:str
    index:int
    type:str


class Message(BaseModel):
    role: str
    content: str | None = None
    tool_calls:list[ToolCall]|None=None
    tool_call_id:str | None = None
    # Future compatibility
    model_config = {
        "extra": "allow",
    }



class Choice(BaseModel):
    index: int
    message: Message
    logprobs: Any | None = None
    finish_reason: str | None = None # tool_calls | stop

    model_config = {
        "extra": "allow",
    }


class PromptTokensDetails(BaseModel):
    cached_tokens: int | None = None

    model_config = {
        "extra": "allow",
    }


class Usage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int

    prompt_tokens_details: PromptTokensDetails | None = None

    # DeepSeek-specific
    prompt_cache_hit_tokens: int | None = None
    prompt_cache_miss_tokens: int | None = None

    model_config = {
        "extra": "allow",
    }


class ChatCompletionResponse(BaseModel):
    id: str
    object: str
    created: int
    model: str

    choices: list[Choice]
    usage: Usage | None = None

    system_fingerprint: str | None = None

    model_config = {
        "extra": "allow",
    }
    
class ChatResponse(BaseModel):
    success:bool
    data:ChatCompletionResponse|None
    error:str|None