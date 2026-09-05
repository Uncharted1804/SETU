# SSH Project

Built for the **SSH Hackathon**, operating under a **3-Layer Architecture** that separates concerns to maximize AI agent reliability:

1. **Layer 1: Directive (What to do)** - Standard Operating Procedures (SOPs) written in Markdown in `directives/`.
2. **Layer 2: Orchestration (Decision making)** - The AI agent navigating directives, calling deterministic scripts, handling errors, and self-annealing.
3. **Layer 3: Execution (Doing the work)** - Deterministic, well-tested Python scripts in `execution/`.

## Directory Structure

```text
SSH/
├── AGENTS.md            # Agent instructions (loaded by modern AI IDEs)
├── CLAUDE.md            # Mirrored instructions for Claude
├── GEMINI.md            # Mirrored instructions for Gemini
├── README.md            # Project overview & documentation
├── .env.example         # Template for environment variables and API keys
├── .gitignore           # Git ignore rules for secrets and temporary files
├── requirements.txt     # Python dependencies for execution scripts
├── directives/          # Layer 1: SOPs and markdown guides
│   ├── README.md        # How to write and maintain directives
│   └── _template.md     # Template for creating new directives
├── execution/           # Layer 3: Deterministic Python tools
│   ├── __init__.py
│   ├── README.md        # Script design principles & conventions
│   └── example_tool.py  # Reference deterministic script
└── .tmp/                # Layer 2/3: Temporary intermediate data (never committed)
    └── .gitkeep
```

## Quick Start

### 1. Configure Environment
Copy `.env.example` to `.env` and fill in necessary credentials:
```bash
cp .env.example .env
```

### 2. Set Up Python Dependencies
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Run a Tool
Execute deterministic scripts directly or instruct the AI orchestrator:
```bash
python3 execution/example_tool.py --input "Hackathon test" --output .tmp/test_result.json
```

## Operating Principles
- **Check for tools first**: Before writing new code, check `execution/`.
- **Deliverables vs Intermediates**: Cloud-based deliverables (Google Sheets, Slides, docs) are deliverables; intermediate files belong in `.tmp/` and can be regenerated anytime.
- **Self-annealing**: When execution scripts fail or hit API constraints, fix the code, test it, and update the corresponding directive with the learnings.