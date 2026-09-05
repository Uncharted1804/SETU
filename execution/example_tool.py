#!/usr/bin/env python3
"""
Example Execution Tool (Layer 3: Deterministic Execution)

Demonstrates the pattern for all scripts in the execution/ directory:
1. Load environment variables (.env)
2. Parse command-line arguments explicitly
3. Perform deterministic logic with comprehensive error handling
4. Write intermediate outputs to .tmp/ or emit structured data
5. Return 0 on success, non-zero on failure
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path

# Attempt to load dotenv if available
try:
    from dotenv import load_dotenv
    # Look for .env in project root (one directory up from execution/)
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        load_dotenv(dotenv_path=env_path)
    else:
        load_dotenv()
except ImportError:
    pass

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)


def run(input_text: str, output_path: str = None) -> dict:
    """
    Core deterministic function.
    """
    logger.info(f"Processing input: {input_text}")
    
    # Example deterministic transformation
    result = {
        "status": "success",
        "input": input_text,
        "length": len(input_text),
        "upper": input_text.upper(),
        "processed_by": "example_tool.py"
    }
    
    if output_path:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
        logger.info(f"Output successfully written to {output_path}")

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Deterministic tool example following the 3-Layer Architecture."
    )
    parser.add_argument(
        "--input",
        type=str,
        required=True,
        help="Input text or data to process."
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Path for intermediate output file (typically in .tmp/)."
    )

    args = parser.parse_args()

    try:
        result = run(input_text=args.input, output_path=args.output)
        # Emit JSON to stdout for machine readability by the orchestrator
        print(json.dumps(result))
        sys.exit(0)
    except Exception as e:
        logger.error(f"Execution failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()