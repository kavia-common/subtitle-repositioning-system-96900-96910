#!/usr/bin/env python3
from __future__ import annotations

"""
PUBLIC_INTERFACE
Script to reposition all SRT subtitles to the top of the screen.

This tool:
- Accepts a video file and an SRT subtitle file as input.
- Parses the SRT.
- Ensures each subtitle cue carries a position indicator to render at the top.
- Writes a new SRT file next to the input (or to a specified output path).

Notes on positioning in SRT:
- The SRT format does not have an official, standardized positioning field.
- Many players ignore any positioning in SRT; some accept inline ASS-style override tags like "{\\an8}" in the cue text.
- This script uses a robust, player-agnostic strategy:
  1) If a cue line already contains an ASS override block with alignment (\\an1..\\an9), it is removed/replaced with {\\an8}.
  2) Otherwise, it prepends {\\an8} to the first non-empty line of each cue (leaving subsequent lines intact).
- {\\an8} indicates top-middle alignment in ASS, which a subset of players honor even when embedded within SRT text.

CLI usage:
  python reposition_srt_top.py --video attachments/output.mp4 --srt attachments/Key_and_Peele_sample1.srt
  # Writes attachments/Key_and_Peele_sample1.repositioned.srt by default.

To specify a custom output:
  python reposition_srt_top.py --video input.mp4 --srt input.srt --out output_top.srt
"""

import argparse
import os
import re
from typing import List, Tuple


SRT_BLOCK_SPLIT = re.compile(r"\n\s*\n", re.MULTILINE)
TIME_LINE_RE = re.compile(
    r"(?P<sh>\d{2}):(?P<sm>\d{2}):(?P<ss>\d{2})[,\.](?P<sms>\d{3})\s*-->\s*"
    r"(?P<eh>\d{2}):(?P<em>\d{2}):(?P<es>\d{2})[,\.](?P<ems>\d{3})"
)

# Regex to find any ASS alignment override within braces, e.g., {\an1} .. {\an9}
ASS_ALIGN_TAG_RE = re.compile(r"\{\\an[1-9]\}")

# Regex to find any ASS override block (not necessarily alignment) at the very start of a line
ASS_BLOCK_AT_START_RE = re.compile(r"^\{[^}]*\}")


def _sanitize_line_top(line: str) -> str:
    """
    Ensure the given text line renders at the top:
    - Remove/replace any existing alignment tag with {\\an8}.
    - If the line already starts with an override block, replace first alignment with an8 or prepend new block.
    - Otherwise, prepend {\\an8}.
    """
    if not line.strip():
        return line  # keep pure blank as is

    # If there's any alignment tag anywhere in the line, strip them all and enforce {\\an8} at start
    if ASS_ALIGN_TAG_RE.search(line):
        line_no_align = ASS_ALIGN_TAG_RE.sub("", line)
        # If line begins with an override block, insert alignment just after it to keep other overrides intact
        m = ASS_BLOCK_AT_START_RE.match(line_no_align)
        if m:
            # Insert \an8 inside the first block if it doesn't include it
            block = m.group(0)
            if r"\an8" not in block:
                new_block = block[:-1] + r"\an8" + "}"
                return new_block + line_no_align[m.end():]
            return line_no_align  # already had \an8 within the first block
        else:
            return "{\\an8}" + line_no_align

    # No alignment tag present:
    # If line starts with an override block, append \an8 inside that first block to avoid stacking blocks
    m = ASS_BLOCK_AT_START_RE.match(line)
    if m:
        block = m.group(0)
        if r"\an8" in block:
            return line  # already top
        new_block = block[:-1] + r"\an8" + "}"
        return new_block + line[m.end():]

    # Otherwise, simply prepend {\\an8}
    return "{\\an8}" + line


def _process_cue_text_lines_to_top(text_lines: List[str]) -> List[str]:
    """
    For a multi-line cue, enforce top alignment by editing the first non-empty line.
    Subsequent lines are kept verbatim to avoid excessive clutter of override tags.
    """
    if not text_lines:
        return text_lines

    out = text_lines[:]
    # Find first non-empty line index
    idx = next((i for i, t in enumerate(out) if t.strip()), None)
    if idx is None:
        return out  # all empty, nothing to do

    out[idx] = _sanitize_line_top(out[idx])
    return out


def parse_srt_blocks(content: str) -> List[Tuple[str, str, List[str]]]:
    """
    Parse SRT into (index, time_line, text_lines) tuples.
    The parser is forgiving: if the first line is not an index number, we synthesize indices.
    """
    blocks = SRT_BLOCK_SPLIT.split(content.strip())
    cues: List[Tuple[str, str, List[str]]] = []
    synth_index = 1

    for block in blocks:
        lines = block.splitlines()
        if not lines:
            continue

        # Try to detect index
        index_line = lines[0].strip()
        index_is_number = index_line.isdigit()
        line_ptr = 1 if index_is_number and len(lines) > 1 else 0
        index_value = index_line if index_is_number else str(synth_index)

        if line_ptr >= len(lines):
            continue

        time_line = lines[line_ptr].strip()
        if not TIME_LINE_RE.search(time_line):
            # Not a valid cue, skip
            continue

        text = lines[line_ptr + 1 :] if (line_ptr + 1) < len(lines) else []
        cues.append((index_value, time_line, text))
        synth_index += 1

    return cues


def format_srt(cues: List[Tuple[str, str, List[str]]]) -> str:
    """
    Render SRT cues back to a string.
    """
    parts: List[str] = []
    for i, (idx, time_line, text_lines) in enumerate(cues, start=1):
        parts.append(str(i))
        parts.append(time_line)
        parts.extend(text_lines if text_lines else [""])
        parts.append("")  # blank between cues
    return "\n".join(parts).strip() + "\n"


# PUBLIC_INTERFACE
def reposition_srt_to_top(srt_content: str) -> str:
    """
    Reposition all SRT cues so they render at the top of the screen
    by inserting/replacing inline alignment tags to {\\an8}.

    Returns:
      Modified SRT content (string).
    """
    cues = parse_srt_blocks(srt_content)
    updated: List[Tuple[str, str, List[str]]] = []
    for idx, time_line, text_lines in cues:
        new_text = _process_cue_text_lines_to_top(text_lines)
        updated.append((idx, time_line, new_text))
    return format_srt(updated)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Move all SRT subtitle cues to the TOP by inserting/replacing {\\an8} override tags."
    )
    parser.add_argument(
        "--video", "-v",
        required=True,
        help="Path to the associated video file (not analyzed here; kept for parity with task signature)."
    )
    parser.add_argument(
        "--srt", "-s",
        required=True,
        help="Path to the input SRT subtitle file."
    )
    parser.add_argument(
        "--out", "-o",
        help="Path to write the updated SRT. Default: <input>.repositioned.srt"
    )
    args = parser.parse_args()

    srt_path = args.srt
    if not os.path.isfile(srt_path):
        raise SystemExit(f"Input SRT not found: {srt_path}")

    with open(srt_path, "r", encoding="utf-8", errors="ignore") as f:
        original = f.read()

    updated = reposition_srt_to_top(original)

    if args.out:
        out_path = args.out
    else:
        base, ext = os.path.splitext(srt_path)
        out_path = f"{base}.repositioned{ext or '.srt'}"

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(updated)

    print(f"Repositioned SRT saved to: {out_path}")


if __name__ == "__main__":
    main()
