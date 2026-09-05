# Execution Layer (Layer 3: Doing the work)

This directory contains deterministic Python scripts called by the orchestrator (the AI agent) as directed by SOPs in `directives/`.

## Script Design Principles
1. **Deterministic & Testable**: Given the same inputs and environment, scripts should behave predictably.
2. **Explicit Interfaces**: Use `argparse` for inputs/flags and print machine-parseable outputs (or write to `.tmp/`).
3. **Graceful Error Handling**: Provide clear exit codes (0 = success, non-zero = failure) and meaningful error messages to standard error.
4. **Environment Isolation**: Load secrets/tokens strictly from `.env` or system environment variables. Never hardcode keys.
5. **Intermediate File Hygiene**: All temporary/scraping/scratch outputs belong in `.tmp/`.