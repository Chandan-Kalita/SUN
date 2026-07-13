import argparse
import glob
import json
import os
import sys
from datetime import datetime

C = {
    "dim": "\033[2m", "bold": "\033[1m", "red": "\033[31m", "green": "\033[32m",
    "yellow": "\033[33m", "blue": "\033[34m", "magenta": "\033[35m", "cyan": "\033[36m",
    "reset": "\033[0m",
}


def paint(text, *styles):
    if not COLOR:
        return text
    return "".join(C[s] for s in styles) + text + C["reset"]


def latest_log() -> str | None:
    found = sorted(glob.glob(os.path.join("logs", "*.jsonl")), key=os.path.getmtime)
    return found[-1] if found else None


def load(path:str) -> list[dict]:
    events = []
    with open(path) as file:
        for line in file:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                print(paint(f"skipping malformed line: {line[:80]}", "red"), file=sys.stderr)
    return events


def stamp(event, origin) -> str:
    when = datetime.fromisoformat(event["ts"])
    return paint(f"[{(when - origin).total_seconds():6.2f}s]", "dim")


def wrap(text, indent, width=100):
    text = (text or "").replace("\n", " ")
    if len(text) > width:
        text = text[:width] + "..."
    return " " * indent + text


def render(events, show_content):
    origin = datetime.fromisoformat(events[0]["ts"])
    for event in events:
        kind = event["type"]
        prefix = stamp(event, origin)

        if kind == "turn_start":
            print()
            print(f"{prefix} {paint('▸ turn ' + str(event['turn']), 'bold', 'blue')}  {paint(event.get('prompt',''), 'bold')}")

        elif kind == "llm_call":
            if event.get("ok"):
                tokens = f"{event.get('prompt_tokens','?')}→{event.get('completion_tokens','?')} tok"
                cached = event.get("cached_tokens")
                prompt_tokens = event.get("prompt_tokens") or 0
                if cached and prompt_tokens:
                    tokens += paint(f" ({cached} cached, {cached/prompt_tokens:.0%})", "dim")
                attempts = event.get("attempts", 1)
                retried = paint(f" after {attempts} attempts", "yellow") if attempts > 1 else ""
                print(f"{prefix}   {paint('● llm', 'cyan')} {event['purpose']:<9} "
                      f"{event.get('latency_ms','?')}ms  {tokens}  "
                      f"{paint('→ ' + str(event.get('finish_reason')), 'dim')}{retried}")
            else:
                print(f"{prefix}   {paint('✗ llm ' + event['purpose'] + ' FAILED', 'red', 'bold')} "
                      f"after {event.get('attempts','?')} attempts, {event.get('latency_ms','?')}ms")
                print(wrap(paint(event.get("error",""), "red"), 14))

        elif kind == "llm_retry":
            print(f"{prefix}   {paint('⟳ retry', 'yellow')} attempt {event['attempt']}, "
                  f"backoff {event.get('delay_ms','?')}ms  {paint(event.get('error',''), 'dim')}")

        elif kind == "tool_call":
            ok = event.get("ok")
            mark = paint("⚙", "green") if ok else paint("⚙", "red")
            status = paint("ok", "green") if ok else paint("FAILED", "red", "bold")
            shell = paint(" shell", "magenta") if event.get("promoted_to_shell") else ""
            exit_code = event.get("exit_code")
            exit_note = f" exit={exit_code}" if exit_code not in (0, None) else ""
            print(f"{prefix}   {mark} {paint(event['name'], 'bold')} "
                  f"{event.get('duration_ms','?')}ms  {status}{exit_note}{shell}")
            print(wrap(paint(event.get("args",""), "dim"), 14))
            effects = event.get("effects")
            if effects:
                style = "dim" if effects.startswith("no filesystem") else "green"
                print(wrap(paint(effects, style), 14))
            if event.get("error"):
                print(wrap(paint(event["error"], "red"), 14))

        elif kind == "stuck":
            action = event.get("action")
            print(f"{prefix}   {paint('■ STUCK', 'red', 'bold')} at iteration {event.get('iteration','?')} "
                  f"{paint('(' + str(action) + ')', 'yellow')}")
            print(wrap(paint(event.get("reason",""), "red"), 14))
            if event.get("guidance"):
                print(wrap(paint("guidance: " + event["guidance"], "yellow"), 14))

        elif kind == "compaction":
            if event.get("ok"):
                print(f"{prefix}   {paint('⇩ compaction', 'magenta')} "
                      f"{event.get('summarized')} msgs → 1  "
                      f"(total {event.get('messages_before')} → {event.get('messages_after')})")
            else:
                print(f"{prefix}   {paint('⇩ compaction FAILED', 'red')} {event.get('error','')}")

        elif kind == "extractor":
            learned = event.get("learned") or {}
            keys = [k for section in learned.values() for k in section]
            if keys:
                print(f"{prefix}   {paint('✎ learned', 'magenta')} {', '.join(keys)}")

        elif kind == "message" and show_content:
            role = event["role"]
            if role == "assistant" and event.get("content"):
                print(f"{prefix}   {paint('assistant', 'dim')} {event['content']}")

        elif kind == "turn_end":
            print(f"{prefix} {paint('▪ turn ' + str(event['turn']) + ' end', 'dim')}  "
                  f"{event.get('total_tokens','?')} tok  "
                  f"budget {event.get('budget_pct','?')}%  "
                  f"messages {event.get('messages','?')}")


def summarize(events):
    calls = [e for e in events if e["type"] == "llm_call"]
    tools = [e for e in events if e["type"] == "tool_call"]
    retries = [e for e in events if e["type"] == "llm_retry"]
    stuck = [e for e in events if e["type"] == "stuck"]

    ok_calls = [e for e in calls if e.get("ok")]
    prompt = sum(e.get("prompt_tokens") or 0 for e in ok_calls)
    completion = sum(e.get("completion_tokens") or 0 for e in ok_calls)
    cached = sum(e.get("cached_tokens") or 0 for e in ok_calls)
    latencies = sorted(e.get("latency_ms") or 0 for e in ok_calls)

    span = ""
    if len(events) > 1:
        seconds = (datetime.fromisoformat(events[-1]["ts"]) - datetime.fromisoformat(events[0]["ts"])).total_seconds()
        span = f"{seconds:.1f}s"

    by_purpose = {}
    for call in ok_calls:
        stat = by_purpose.setdefault(call["purpose"], [0, 0])
        stat[0] += 1
        stat[1] += (call.get("total_tokens") or 0)

    print()
    print(paint("─" * 72, "dim"))
    print(paint("summary", "bold"))
    print(f"  wall            {span}")
    print(f"  turns           {len([e for e in events if e['type'] == 'turn_start'])}")
    retry_note = f", {len(retries)} retry" + ("" if len(retries) == 1 else "s") if retries else ""
    print(f"  llm calls       {len(ok_calls)} ok, {len(calls) - len(ok_calls)} failed{retry_note}")
    for purpose, (count, total) in sorted(by_purpose.items()):
        print(f"    {purpose:<12}  {count} calls, {total} tok")
    if latencies:
        mid = latencies[len(latencies) // 2]
        print(f"  llm latency     median {mid}ms, max {latencies[-1]}ms")
    print(f"  tokens          {prompt + completion} total ({prompt} prompt, {completion} completion)")
    if prompt:
        print(f"  cache           {cached}/{prompt} prompt tokens ({cached/prompt:.0%})")

    failed = [e for e in tools if not e.get("ok")]
    promoted = [e for e in tools if e.get("promoted_to_shell")]
    noop = [e for e in tools if e.get("ok") and (e.get("effects") or "").startswith("no filesystem")]
    print(f"  tools           {len(tools)} calls, {len(failed)} failed, {len(promoted)} promoted to shell")
    if noop:
        print(paint(f"  claimed success but changed nothing: {len(noop)}", "yellow"))
    if stuck:
        print(paint(f"  stuck           {len(stuck)} interventions", "red", "bold"))
    if failed:
        print()
        print(paint("  failing tool calls:", "red"))
        for event in failed:
            print(f"    {event['name']} {paint(event.get('args',''), 'dim')}")
            print(f"      {paint(event.get('error',''), 'red')}")


parser = argparse.ArgumentParser(description="render a sun session log as a timeline")
parser.add_argument("logfile", nargs="?", help="path to a logs/*.jsonl file (default: most recent)")
parser.add_argument("--no-color", action="store_true")
parser.add_argument("--quiet", action="store_true", help="summary only")
parser.add_argument("--content", action="store_true", help="include assistant message text")
args = parser.parse_args()

COLOR = not args.no_color and sys.stdout.isatty()

path = args.logfile or latest_log()
if not path:
    print("no logs found; run sun first (looked in ./logs/*.jsonl)", file=sys.stderr)
    raise SystemExit(1)
if not os.path.exists(path):
    print(f"no such log: {path}", file=sys.stderr)
    raise SystemExit(1)

events = load(path)
if not events:
    print(f"{path} is empty", file=sys.stderr)
    raise SystemExit(1)

print(paint(f"{path}  ({len(events)} events)", "bold"))
if not args.quiet:
    render(events, show_content=args.content)
summarize(events)
