"""Topic calibration tool.

Feed it papers you consider relevant (good) and papers that were noise (bad),
and it will suggest an updated topic block for topics.yaml.

Usage:
    python tools/calibrate_topic.py --topic axon-segmentation-em

The tool reads two plain-text files:
    tools/calibration/good_papers.txt   — one paper per block (title + abstract)
    tools/calibration/bad_papers.txt    — same format, noise examples

Each paper block is separated by a blank line. Example:

    Axon segmentation in FIB-SEM volumes using deep learning
    We present a method for automated segmentation of myelinated axons
    in serial block-face scanning electron microscopy (SBEM) volumes...

    Next paper title
    Next paper abstract...

Outputs a YAML snippet you can paste into config/topics.yaml.
"""

import argparse
import os
import sys
from pathlib import Path

import requests
import yaml
from dotenv import load_dotenv

load_dotenv()

_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
_MODEL = "openai/gpt-oss-120b:free"


def _read_papers(path: Path) -> list[str]:
    """Read a file of paper blocks separated by blank lines."""
    if not path.exists():
        return []
    blocks = path.read_text().strip().split("\n\n")
    return [b.strip() for b in blocks if b.strip()]


def _call_llm(prompt: str) -> str:
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        sys.exit("OPENROUTER_API_KEY not set.")
    resp = requests.post(
        _OPENROUTER_URL,
        json={
            "model": _MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 1024,
            "temperature": 0.2,
        },
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/paper-watch",
        },
        timeout=60,
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"].get("content")
    if not content:
        sys.exit("LLM returned empty content.")
    return content.strip()


def _build_prompt(good_papers: list[str], bad_papers: list[str], topic_name: str) -> str:
    good_section = "\n\n---\n\n".join(good_papers) if good_papers else "(none provided)"
    bad_section = "\n\n---\n\n".join(bad_papers) if bad_papers else "(none provided)"

    return f"""You are helping configure a research paper monitoring tool.

The user is tracking the topic: "{topic_name}"

## RELEVANT papers (user wants these):
{good_section}

## NOISE papers (user does NOT want these — they matched but are off-topic):
{bad_section}

Based on the relevant papers, extract specific technical keywords and phrases that characterise this research area.
Based on the noise papers, identify terms that appear in the noise but NOT in the relevant papers — these become exclusions.

Return ONLY a YAML block in this exact format (no explanation, no markdown fences):

name: {topic_name}
include_any:
  - <specific phrase>
  - <specific phrase>
include_all: []
exclude:
  - <term from noise>
  - <term from noise>
boost_authors: []
boost_venues:
  - <venue name>

Rules:
- include_any: 10–20 specific multi-word phrases (not single generic words). Prefer phrases that would only appear in papers squarely in this domain.
- exclude: terms that clearly separate noise from signal. Avoid excluding terms that might appear in good papers too.
- boost_venues: well-known journals/conferences for this domain.
- Output raw YAML only — no prose, no ```yaml fences.
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a calibrated topic block from example papers.")
    parser.add_argument("--topic", default="my-topic", help="Topic name for the output YAML block")
    parser.add_argument(
        "--good", default="tools/calibration/good_papers.txt",
        help="Path to relevant paper examples (default: tools/calibration/good_papers.txt)",
    )
    parser.add_argument(
        "--bad", default="tools/calibration/bad_papers.txt",
        help="Path to noise paper examples (default: tools/calibration/bad_papers.txt)",
    )
    args = parser.parse_args()

    good_papers = _read_papers(Path(args.good))
    bad_papers = _read_papers(Path(args.bad))

    if not good_papers:
        sys.exit(f"No good papers found at {args.good}. Create the file with at least one paper block.")

    print(f"Loaded {len(good_papers)} relevant paper(s) and {len(bad_papers)} noise paper(s).")
    print("Calling LLM...\n")

    prompt = _build_prompt(good_papers, bad_papers, args.topic)
    result = _call_llm(prompt)

    # Validate it parses as YAML
    try:
        parsed = yaml.safe_load(result)
        print("=== Suggested topic block ===\n")
        print(result)
        print("\n=== Parsed successfully ===")
        print(f"  include_any: {len(parsed.get('include_any', []))} terms")
        print(f"  exclude:     {len(parsed.get('exclude', []))} terms")
        print(f"  boost_venues:{len(parsed.get('boost_venues', []))} venues")
        print("\nCopy the block above into config/topics.yaml under 'topics:'")
    except yaml.YAMLError as e:
        print("Warning: output did not parse cleanly as YAML:", e)
        print("\nRaw output:\n", result)


if __name__ == "__main__":
    main()
