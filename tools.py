import fnmatch
import os
import shlex
import stat as statmod
from pathlib import Path
import subprocess

from model import ToolResult

SHELL_TOKENS = {">", ">>", "<", "|", "||", "&&", ";", "&"}
INFORMATIONAL_EXIT = {"grep", "egrep", "fgrep", "rg", "diff", "cmp", "test"}
MAX_WATCHED_PATHS = 200


def _consent(prompt: str) -> ToolResult | None:
    answer = input(prompt).lower().strip()
    if answer == 'y':
        return None
    if answer == 'n':
        return ToolResult(ok=False, error="user declined")
    return ToolResult(ok=False, error=f"user declined and instructed instead: {answer}")


def _needs_shell(command:list[str]) -> bool:
    return any(tok in SHELL_TOKENS or tok.startswith("$(") or "`" in tok for tok in command)


def _promote(command:list[str]) -> str:
    parts = []
    for tok in command:
        if tok in SHELL_TOKENS or any(c in tok for c in "*?$~`"):
            parts.append(tok)
        else:
            parts.append(shlex.quote(tok))
    return " ".join(parts)


def _watched_paths(command:list[str]) -> list[str]:
    paths = []
    for tok in command:
        if tok.startswith("-") or tok in SHELL_TOKENS:
            continue
        if any(c in tok for c in "*?`$"):
            continue
        paths.append(tok)
    try:
        paths.extend(os.listdir("."))
    except OSError:
        pass
    return list(dict.fromkeys(paths))[:MAX_WATCHED_PATHS]


def _snapshot(paths:list[str]) -> dict:
    snap = {}
    for path in paths:
        try:
            st = os.stat(path)
            kind = "dir" if statmod.S_ISDIR(st.st_mode) else "file"
            snap[path] = (kind, st.st_size, st.st_mtime_ns)
        except OSError:
            snap[path] = None
    return snap


def _diff(before:dict, after:dict) -> str:
    lines = []
    for path, now in after.items():
        was = before.get(path)
        if was == now:
            continue
        if was is None and now is not None:
            lines.append(f"created: {path} ({now[0]}, {now[1]} bytes)")
        elif was is not None and now is None:
            lines.append(f"deleted: {path}")
        elif now is not None:
            lines.append(f"modified: {path} ({now[0]}, {now[1]} bytes)")
    return "\n".join(lines) if lines else "no filesystem changes observed"


def run_command(command:list[str], timeout:float, shell:bool=False) -> ToolResult:
    note = None
    shell_line = None
    if shell:
        shell_line = " ".join(command)
    elif _needs_shell(command):
        shell_line = _promote(command)
        note = "argv held shell metacharacters, so this ran through `sh -lc` and the redirect/pipe/chain worked normally. the result above is real, do not retry. pass shell:true next time to be explicit"

    if shell_line is not None:
        argv = ["sh", "-lc", shell_line]
        display = f"sh -lc {shell_line!r}"
    else:
        argv = command
        display = str(command)

    refused = _consent(f"sun wants to execute this command {display}, press y to proceed and n to cancel or instruct sun what to do different: ")
    if refused:
        return refused

    watched = _watched_paths(command)
    before = _snapshot(watched)
    try:
        output = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except Exception as e:
        return ToolResult(ok=False, error=f"{type(e).__name__}: {e}", note=note)

    watched = list(dict.fromkeys(watched + _watched_paths(command)))
    after = _snapshot(watched)
    before = {path: before.get(path) for path in watched}

    exe = command[0].split()[0] if command else ""
    ok = output.returncode == 0 or (exe in INFORMATIONAL_EXIT and output.returncode == 1)

    return ToolResult(
        ok=ok,
        exit_code=output.returncode,
        output=_truncate(output.stdout) or None,
        error=_truncate(output.stderr) or None,
        note=note,
        effects=_diff(before, after),
    )

def _truncate(s: str, limit: int = 2000) -> str:
    if len(s) <= limit:
        return s
    head = s[: limit // 2]
    tail = s[-limit // 2 :]
    dropped = len(s) - limit
    return f"{head}\n... [{dropped} chars truncated, to read full output use paginated read, if reading command output then write the output in a temp file then read part by part, if reading a existing file directly read part by part ] ...\n{tail}"

def is_critical_file(file_path: str) -> bool:
    """
    Checks if a file path belongs to common critical data categories 
    (secrets, configurations, keys, databases, or sensitive documents).
    """
    path = Path(file_path)
    name = path.name.lower() # Normalize to lowercase for case-insensitive matching
    
    # 1. Exact file name matches
    exact_matches = {
        '.env', 'wp-config.php', 'settings.py', 
        'id_rsa', 'id_ed25519', 'sam', 'system'
    }
    if name in exact_matches:
        return True

    # 2. Wildcard pattern matches
    patterns = [
        # Credentials & Envs
        '.env.*', 'config.*', 'credentials.*', 'secrets.*',
        # Keys & Certificates
        '*.pem', '*.crt', '*.key', '*.keystore', '*.jks', '*.pfx', '*.p12',
        # Databases & Backups
        '*.db', '*.sqlite', '*.sqlite3', '*.sql', 'dump.sql', 'backup.sql', '*.bak',
        # High-risk User Content
        '*password*', '*pass*', 'payroll.*', 'financials.*', 'customers.*'
    ]
    
    for pattern in patterns:
        if fnmatch.fnmatch(name, pattern):
            return True
            
    return False

def read_chunk(file_path, offset, char_limit=2000) -> ToolResult:
    print(f"reading {file_path} from {offset} to {char_limit}...")
    if is_critical_file(file_path=file_path) is True:
        refused = _consent(f"this file looks critical do you want to allow sun to read it, press y to proceed and n to cancel or instruct sun what to do different: ")
        if refused:
            return refused

    if char_limit > 2000:
        return ToolResult(ok=False, error="char_limit must be less then 2000")
    try :
        with open(file_path, "r", encoding="utf-8") as file:
            file.seek(offset)
            data = file.read(char_limit)
            return ToolResult(ok=True, output=data)
    except Exception as e:
        return ToolResult(ok=False, error=f"{type(e).__name__}: {e}")

# print(run_command(["cat1","chain2.txt"], timeout=10))
tools = [
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": (
                "Execute a system command on the local machine after obtaining "
                "user confirmation. Runs without a shell by default, so shell "
                "features need shell:true. The result reports the filesystem "
                "changes actually observed, so verify them instead of assuming "
                "a zero exit code did what you intended."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "array",
                        "description": (
                            "The command to execute as a list of strings. "
                            "The first element must be the executable, followed "
                            "by its arguments. For example: "
                            '["python", "--version"] or ["ls", "-la"]. '
                            "When shell is true the elements are joined with "
                            "spaces into a single shell line, so "
                            '["echo hi > f.txt"] and ["echo", "hi", ">", "f.txt"] '
                            "are equivalent."
                        ),
                        "items": {
                            "type": "string"
                        },
                    },
                    "timeout": {
                        "type": "number",
                        "description": (
                            "Maximum time in seconds to allow the command to run "
                            "before timing out."
                        ),
                    },
                    "shell": {
                        "type": "boolean",
                        "description": (
                            "Run the command through `sh -lc`. Required for "
                            "redirection (>), pipes (|), chaining (&& ;), globs, "
                            "and variable expansion -- without it those "
                            "characters are passed to the program as literal "
                            "arguments and do nothing. Defaults to false."
                        ),
                    },
                },
                "required": ["command", "timeout"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_chunk",
            "description": (
                "Read a file chunk by chunk."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": (
                            "Path of the file. "
                        ),
                    },
                    "offset": {
                        "type": "number",
                        "description": (
                            "From which character to start reading the file "
                            "must be a positive number"
                        ),
                    },
                    "char_limit": {
                        "type": "number",
                        "description": (
                            "How many character to read starting from the offset"
                            "must be a less then 2000"
                        ),
                    },
                },
                "required": ["file_path", "offset","char_limit"],
            },
        },
    },
]