"""Convert local .docx files to readable Markdown using macOS textutil output."""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

SECTION_RE = re.compile(r"^\d+(?:\.\d+)*\.?\s+.+$")
TABLE_HEADER_RE = re.compile(r"^(Phase|Duration|Deliverable|Success Criteria)\s*$")
BULLET_PREFIXES = ("•", "-", "*")


def _extract_text(docx_path: Path) -> str:
    result = subprocess.run(
        ["textutil", "-convert", "txt", "-stdout", str(docx_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.replace("\r\n", "\n")


def _is_all_caps_heading(line: str) -> bool:
    letters = [char for char in line if char.isalpha()]
    return bool(letters) and all(char.isupper() for char in letters)


def _emit_table(lines: list[str], start: int) -> tuple[list[str], int]:
    rows: list[str] = []
    idx = start
    while idx < len(lines):
        line = lines[idx].strip()
        if not line:
            idx += 1
            if rows:
                break
            continue
        if line.startswith("3.1 ") or line.startswith("4.1 "):
            break
        rows.append(line)
        idx += 1

    if len(rows) < 8:
        return [], start

    chunks = [rows[i : i + 4] for i in range(0, len(rows), 4)]
    if not chunks or chunks[0] != ["Phase", "Duration", "Deliverable", "Success Criteria"]:
        return [], start

    md = [
        "| Phase | Duration | Deliverable | Success Criteria |",
        "| --- | --- | --- | --- |",
    ]
    for chunk in chunks[1:]:
        if len(chunk) != 4:
            break
        md.append("| " + " | ".join(chunk) + " |")
    return md + [""], idx


def _convert_text(text: str) -> str:
    raw_lines = [line.rstrip() for line in text.splitlines()]
    lines = [line.replace("\t•\t", "• ").replace("\t", " ").strip() for line in raw_lines]

    output: list[str] = []
    idx = 0
    seen_nonempty = 0
    while idx < len(lines):
        line = lines[idx]
        if line == "Confidential":
            idx += 1
            continue

        if not line:
            if output and output[-1] != "":
                output.append("")
            idx += 1
            continue

        if TABLE_HEADER_RE.match(line):
            table_md, next_idx = _emit_table(lines, idx)
            if table_md:
                output.extend(table_md)
                idx = next_idx
                continue

        if seen_nonempty == 0:
            output.append(f"# {line.title()}" if _is_all_caps_heading(line) else f"# {line}")
            output.append("")
            seen_nonempty += 1
            idx += 1
            continue

        if _is_all_caps_heading(line):
            output.append(f"## {line.title()}")
            seen_nonempty += 1
            idx += 1
            continue

        if SECTION_RE.match(line):
            depth = min(line.count(".") + 1, 4)
            heading = "#" * depth
            normalized = line[:-1] if line.endswith(".") and line[:-1].isdigit() else line
            output.append(f"{heading} {normalized}")
            seen_nonempty += 1
            idx += 1
            continue

        if line.startswith(BULLET_PREFIXES):
            bullet = line[1:].strip()
            output.append(f"- {bullet}")
            seen_nonempty += 1
            idx += 1
            continue

        output.append(line)
        seen_nonempty += 1
        idx += 1

    while output and output[-1] == "":
        output.pop()
    if output:
        output.insert(
            2,
            (
                "_Converted from the original DOCX for repository readability. "
                "Treat this as reference material; the README and PROJECT_STATUS.md "
                "reflect the current implementation state._"
            ),
        )
        output.insert(3, "")

    return "\n".join(output) + "\n"


def convert_docx(docx_path: Path) -> Path:
    markdown = _convert_text(_extract_text(docx_path))
    md_path = docx_path.with_suffix(".md")
    md_path.write_text(markdown, encoding="utf-8")
    return md_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert one or more .docx files to Markdown.")
    parser.add_argument("paths", nargs="+", help="Paths to .docx files.")
    args = parser.parse_args()

    for raw_path in args.paths:
        docx_path = Path(raw_path).resolve()
        md_path = convert_docx(docx_path)
        print(md_path)


if __name__ == "__main__":
    main()
