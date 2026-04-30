# CryptoQuant CLI Knowledge Base

**Module:** Command-line interface  
**Purpose:** Entry points for all platform operations via argparse

## OVERVIEW

CLI provides 6 subcommands: `backtest`, `paper`, `live`, `status`, `config`, `kill`. Uses argparse with subparser architecture.

## STRUCTURE

```
cli/
├── __init__.py       # Module exports
├── main.py           # Entry point + command dispatch
└── commands/
    ├── __init__.py   # Command exports
    ├── backtest.py   # Backtest execution
    ├── config.py     # Configuration management
    └── status.py     # System status display
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Add new command | `main.py:create_parser()` | Add subparser + dispatch |
| Command logic | `cli/commands/<cmd>.py` | Implement run_<cmd>(args) |
| Global flags | `main.py:54-59` | --version handler |
| Help text | Subparser epilog | Usage examples in epilog |

## CONVENTIONS

**Adding Commands:**
1. Create subparser in `create_parser()`
2. Add handler function `run_<command>(args)`
3. Wire dispatch in `dispatch_command()`
4. Place logic in `cli/commands/<command>.py`

**Argument Pattern:**
- Required: `required=True`
- Defaults: Use `default=` not optional positional
- Types: Explicit `type=str`, `type=int`, `type=float`

## ANTI-PATTERNS

**FORBIDDEN:**
- Running live without `--dry-run` first (safety check enforced)
- Live trading without manual 'LIVE' confirmation (see `run_live():324`)

**WARNINGS:**
- Kill switch requires 'KILL' confirmation unless `--force`
- Commands return exit codes (0=success, 1=error)

## UNIQUE STYLES

**Dispatch Pattern:**
```python
def dispatch_command(args):
    if args.command == "mycmd":
        return run_mycmd(args)
    # Always return int exit code
```

**Confirmation Pattern:**
```python
if not args.dry_run:
    confirmation = input("Type 'LIVE' to confirm: ")
```

## COMMANDS

```bash
# Entry points
python -m cli.main <command> [...]
python -m cryptoquant <command> [...]

# Available commands
backtest --strategy <name> --pair <symbol> [--days 30]
paper --strategy <name> --pair <symbol> [--duration 24]
live --strategy <name> --pair <symbol> [--dry-run]
status [--verbose]
config --show | --set KEY=VALUE | --reset
kill [--force] [--reason <text>]
```
