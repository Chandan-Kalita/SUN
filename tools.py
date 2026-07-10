import fnmatch
from pathlib import Path
import subprocess


def run_command(command:list[str], timeout:float):
    consent = input(f"sun wants to execute this command {command}, press y to proceed and n to cancel or instruct sun what to do different: ")
    if consent.lower().strip() != 'y':
        
        if consent.lower().strip() == 'n':
            return "ran:false;reason:user declined"
        else :
            return f"ran:false;reason:{consent}"
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

def read_chunk(file_path, offset, char_limit=2000):
    print(f"reading {file_path} from {offset} to {char_limit}...")
    if is_critical_file(file_path=file_path) is True:
        consent = input(f"this file looks critical do you want to allow sun to read it, press y to proceed and n to cancel or instruct sun what to do different: ")
        if consent.lower().strip() != 'y':    
            if consent.lower().strip() == 'n':
                return "ran:false;reason:user declined"
            else :
                return f"ran:false;reason:{consent}"

    if char_limit > 2000:
        return f"ran:false;reason:char_limit must be less then 2000"
    try :
        with open(file_path, "r", encoding="utf-8") as file:
        # Jump directly to the offset position
            file.seek(offset)
            
            # Read only the limited amount into memory
            data = file.read(char_limit)
            return data
    except Exception as e:
        return f"ran:false;error:{e}"

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