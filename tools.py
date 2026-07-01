import subprocess


def run_command(command:list[str], timeout:float):
    consent = input(f"sun wants to execute this command {command}, press y to proceed and n to cancel: ")
    consent = consent.lower().strip()
    if consent != 'y':
        return "ran:false;reason:user declined"
    try:
        output = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except Exception as e:
        return f"ran:false;error:{e}"
    _stdout = _truncate(output.stdout)
    _stderr = _truncate(output.stderr)
    _exitcode = output.returncode
    return f"ran:true;exitcode:{_exitcode};stdout:{_stdout};stderr:{_stderr}"

def _truncate(s: str, limit: int = 2000) -> str:
    if len(s) <= limit:
        return s
    head = s[: limit // 2]
    tail = s[-limit // 2 :]
    dropped = len(s) - limit
    return f"{head}\n... [{dropped} chars truncated] ...\n{tail}"

# print(run_command(["cat1","chain2.txt"], timeout=10))
tools = [
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": (
                "Execute a system command on the local machine after obtaining "
                "user confirmation. The command must be provided as a list of "
                "arguments rather than a single shell string."
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
                            '["python", "--version"] or ["ls", "-la"].'
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
                },
                "required": ["command", "timeout"],
            },
        },
    },
]