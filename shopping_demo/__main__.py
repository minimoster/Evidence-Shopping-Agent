"""Standard-library CLI. No external requests or model calls."""
import argparse
import json
from pathlib import Path

from .core import DEFAULT_QUERY, SCENARIOS, Task, replay_trace


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline ScriptedPolicy demo, not an LLM or real shop")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="Run one synthetic task; emit public JSON trace")
    run.add_argument("--scenario", choices=SCENARIOS, default="success")
    run.add_argument("--query", default=DEFAULT_QUERY)
    run.add_argument("--max-steps", type=int, default=12)
    replay = commands.add_parser("replay", help="Read an explicitly supplied local public trace")
    replay.add_argument("trace", type=Path)
    serve = commands.add_parser("serve", help="Start local-only WebUI")
    serve.add_argument("--host", default="127.0.0.1", choices=["127.0.0.1"])
    serve.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if args.command == "serve":
        from .web import main as web_main
        web_main(["--host", args.host, "--port", str(args.port)])
        return
    try:
        if args.command == "run":
            task = Task(args.query, args.scenario, max_steps=args.max_steps)
            task.run()
            result = task.trace()
        else:
            if args.trace.stat().st_size > 2_000_000:
                raise ValueError("trace_file_too_large")
            result = replay_trace(json.loads(args.trace.read_text(encoding="utf-8")))
    except (ValueError, OSError, TypeError, RecursionError):
        parser.exit(2, "Invalid task or public trace; no action executed.\n")
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
