# Directives (Layer 1: What to do)

Directives are Standard Operating Procedures (SOPs) written in clear Markdown. They define *what* needs to be accomplished and serve as the instruction set for the AI agent (Layer 2 Orchestrator).

## Structure of a Directive

Every directive in this folder should clearly define:
1. **Goal**: High-level objective.
2. **Inputs**: What arguments, files, or environment configurations are expected.
3. **Execution Tools**: Which deterministic Python scripts in `execution/` to invoke, and in what order.
4. **Outputs**:
   - **Deliverables**: Final user-facing outputs (e.g. cloud services, Google Sheets, Google Slides, final reports).
   - **Intermediates**: Working files placed in `.tmp/` that can be deleted and regenerated.
5. **Edge Cases & Learnings**: Dynamic section updated via the self-annealing loop whenever an error, rate limit, or new constraint is encountered.

## Operating Guidelines
- Use `_template.md` to scaffold new directives.
- Keep directives pragmatic and up to date.
- When execution tools are modified or improved, update the corresponding directive with notes on new parameters, error handling, or performance tips.