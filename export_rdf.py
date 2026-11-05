#!/usr/bin/env python3
"""Write the graph in other RDF formats: N-Triples, JSON-LD and RDF/XML.

Reads data/sib.ttl and writes data/sib.nt, data/sib.jsonld and data/sib.rdf. Each
file is parsed back and its triple count compared with the source, so a format that
loses data fails loudly. Run it with the project's virtualenv (see requirements.txt).

Usage: .venv/bin/python export_rdf.py
"""
import os
import sys

from rdflib import Graph
from rdflib.namespace import SDO

HERE = os.path.dirname(os.path.abspath(__file__))
SOURCE = os.path.join(HERE, "data", "sib.ttl")
FORMATS = {
    "nt": "nt",
    "jsonld": "json-ld",
    "rdf": "xml",
}


def main():
    graph = Graph()
    graph.bind("schema", SDO)
    graph.parse(SOURCE, format="turtle")
    expected = len(graph)
    print(f"read {expected} triples from data/sib.ttl", file=sys.stderr)

    for ext, fmt in FORMATS.items():
        out = os.path.join(HERE, "data", f"sib.{ext}")
        graph.serialize(destination=out, format=fmt, encoding="utf-8")

        check = Graph()
        check.parse(out, format=fmt)
        if len(check) != expected:
            sys.exit(f"{out} has {len(check)} triples, expected {expected}")
        print(f"wrote {out} ({len(check)} triples)", file=sys.stderr)


if __name__ == "__main__":
    main()
