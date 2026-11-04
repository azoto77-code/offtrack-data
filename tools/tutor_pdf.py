#!/usr/bin/env python3
"""The Tutor stretches of the Polizia di Stato, from their PDF to tools/data/tutor.csv.

The Polizia di Stato publishes the motorway stretches checked by the Tutor (average speed) as a PDF, at
https://www.poliziadistato.it/articolo/tutor: one row per stretch, from one exit to the next, with the direction. The
motorway is only a picture of its sign, so it is not read: sections.py finds the two exits by name on OpenStreetMap,
and the road between them. The list changes a few times a year; run this on the new PDF and commit the CSV:

    pdftotext -layout elenco.pdf elenco.txt && tutor_pdf.py elenco.txt tools/data/tutor.csv "maggio 2026"
"""
import csv
import re
import sys

DIRECTIONS = ("NORD", "SUD", "EST", "OVEST", "FRANCIA", "ITALIA")
_DIR = re.compile(r"\s*\bDI(?:R)?\s+(" + "|".join(DIRECTIONS) + r")\b")
# A note in brackets after a name: "(A1 VAR)", "(A1 D19)".
_NOTE = re.compile(r"\(([^)]*)\)")


def split_name(cell):
    """The exit's name, the direction written after it (or None) and the note in brackets (or None)."""
    note = None
    m = _NOTE.search(cell)
    if m:
        note = m.group(1).strip()
        cell = _NOTE.sub(" ", cell)
    # "ALL SAN LAZZARODIR SUD": the space before DIR is sometimes missing.
    cell = re.sub(r"(?<=[A-Z])DIR\s", " DIR ", cell)
    d = None
    m = _DIR.search(cell)
    if m:
        d = m.group(1)
        cell = cell[: m.start()]
    # "-M" after some names, of no meaning for where the exit is.
    cell = re.sub(r"\s+-\s*M\b", " ", cell)
    return re.sub(r"\s+", " ", cell).strip(" .-"), d, note


def rows_of(text):
    """The stretches of the PDF's text as pdftotext -layout writes it: [(from, to, direction, note)]."""
    out = []
    for line in text.splitlines():
        cells = [c for c in re.split(r"\s{2,}", line.strip()) if c]
        if len(cells) < 2 or line.strip().startswith(("TRATTI", "aggiornato")):
            continue
        a, da, na = split_name(cells[0])
        b, db, nb = split_name(cells[1])
        if not a or not b:
            continue
        # The direction of the arrival, else of the departure, else the one written in the third column.
        rest = " ".join(cells[2:])
        m = _DIR.search(" " + rest)
        d = db or da or (m.group(1) if m else "")
        out.append((a, b, d, na or nb or ""))
    return out


def main():
    src, dst, edition = sys.argv[1], sys.argv[2], sys.argv[3]
    rows = rows_of(open(src, encoding="utf-8").read())
    with open(dst, "w", encoding="utf-8", newline="") as f:
        f.write(f"# Tratti controllati dal Tutor, Polizia di Stato, {edition}: https://www.poliziadistato.it/articolo/tutor\n")
        w = csv.writer(f)
        w.writerow(["da", "a", "direzione", "nota"])
        w.writerows(rows)
    print(f"{len(rows)} tratti in {dst}")


if __name__ == "__main__":
    main()
