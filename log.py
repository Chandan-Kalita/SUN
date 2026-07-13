import json
import os
from datetime import datetime, timezone

LOG_DIR = "logs"
_path = None


def init(session_id) -> str:
    global _path
    os.makedirs(LOG_DIR, exist_ok=True)
    _path = os.path.join(LOG_DIR, f"{session_id}.jsonl")
    return _path


def clip(value, limit:int=500):
    if value is None:
        return None
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    if len(text) <= limit:
        return text
    return f"{text[:limit]}...[+{len(text) - limit} chars]"


def event(type:str, **fields):
    if _path is None:
        return
    record = {"ts": datetime.now(timezone.utc).isoformat(), "type": type}
    record.update({key: val for key, val in fields.items() if val is not None})
    with open(_path, "a") as file:
        file.write(json.dumps(record, default=str) + "\n")
