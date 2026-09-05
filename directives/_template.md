# Directive: [Task / SOP Name]

## 1. Goal
[Describe the objective of this task in plain English as you would to a mid-level team member.]

## 2. Inputs & Prerequisites
- **Parameters**: [e.g. Query string, date range, target URL]
- **Environment Variables**: [e.g. API keys needed from `.env`]
- **Input Files**: [Any required files or references]

## 3. Execution Flow
Deterministic tools to run from the `execution/` directory:

1. **Step 1**: Run `execution/[tool_name].py`
   - Arguments: `--input <value> --output .tmp/<intermediate_file>`
   - Purpose: [What this step does]
2. **Step 2**: Run `execution/[processing_tool].py`
   - Arguments: `--source .tmp/<intermediate_file>`
   - Purpose: [What this step does]

## 4. Outputs
- **Deliverables**: [e.g., Google Sheet link, Google Slide deck, user report]
- **Intermediates**: [e.g., `.tmp/raw_data.json` - regenerable files]

## 5. Edge Cases & Learnings (Self-Annealing Log)
- *[Date]*: [Document any API rate limits, schema quirks, bugfixes, or operational learnings discovered during execution.]