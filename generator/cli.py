from __future__ import annotations

import argparse
from pathlib import Path

from .drawio_writer import build_drawio
from .layout_engine import build_layout, validate_input_data
from .library_loader import load_library
from .parser import load_input


def main() -> int:
    parser = argparse.ArgumentParser(description="Generador automatico de diagramas draw.io para Ausarta.")
    parser.add_argument("--input", required=True, help="Ruta al JSON de entrada.")
    parser.add_argument("--library", required=True, help="Ruta a la libreria mxlibrary.")
    parser.add_argument("--output", required=True, help="Ruta del .drawio de salida.")
    parser.add_argument("--template", choices=["oficina_simple", "con_switch", "rack", "multisede"], help="Plantilla a usar.")
    args = parser.parse_args()

    data = load_input(args.input)
    if args.template:
        data["template"] = args.template
    library = load_library(args.library)
    warnings = validate_input_data(data)
    nodes, edges = build_layout(data)
    result = build_drawio(nodes, edges, library, warnings=warnings)

    output_path = Path(args.output)
    output_path.write_text(result.xml, encoding="utf-8")

    if result.warnings:
        print("Warnings:")
        for warning in result.warnings:
            print(f"- {warning}")

    print(f"Generado: {output_path}")
    return 0
