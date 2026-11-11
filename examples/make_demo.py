"""Create one fictional input file and print the exact Hermes demo prompt."""

from __future__ import annotations

import argparse
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path, help="A new folder with an existing parent")
    args = parser.parse_args()
    folder = args.folder.expanduser().absolute()
    original = Path(__file__).with_name("client-notes.md")
    with original.open(encoding="utf-8") as source:
        notes = source.read()

    try:
        folder.mkdir()
    except OSError as exc:
        parser.error(f"Could not create a new demo folder at {folder}: {exc}")
    input_path = folder / original.name
    with input_path.open("x", encoding="utf-8", newline="\n") as target:
        target.write(notes)

    paths = {
        "weekly-brief.md": "Final client-facing brief with progress, next step, and decision needed.",
        "outline.md": "Scratch outline for the brief.",
        "source-excerpts.md": "Scratch notes with the supporting lines from the original.",
        "wording-options.md": "Scratch notes with two alternate phrasings of the next step.",
    }
    print(f"Choose this folder in Clean Exit and start tracking:\n{folder}\n")
    print("Then send the following prompt to Hermes:\n")
    print(f'Read the fictional notes at "{input_path.as_posix()}".')
    print("Use the native write_file tool once for each of these four absolute paths:")
    for filename, purpose in paths.items():
        print(f'- "{(folder / filename).as_posix()}" — {purpose}')
    print(
        "Use only the supplied notes as facts. Keep the original client-notes.md unchanged. "
        "Create exactly those four files using write_file. Report when they are saved."
    )


if __name__ == "__main__":
    main()
