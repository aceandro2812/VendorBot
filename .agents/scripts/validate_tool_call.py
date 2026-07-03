import sys
import json

def main():
    try:
        # Context is passed via stdin
        context = json.load(sys.stdin)
        command = context.get("tool_args", {}).get("CommandLine", "")

        blocked_patterns = [
            "rm -rf", "mkfs", "rmdir /s", "del /f", "format ", 
            "shutdown", "reboot", "drop database"
        ]

        for pattern in blocked_patterns:
            if pattern in command.lower():
                print(f"BLOCKED: Destructive command '{pattern}' detected.", file=sys.stderr)
                sys.exit(1)

        print("APPROVED: Command validation passed.")
        sys.exit(0)
    except Exception as e:
        print(f"Validation error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
