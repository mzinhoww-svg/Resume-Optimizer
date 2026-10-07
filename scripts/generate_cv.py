"""Gera um PDF do curriculo adaptado a uma vaga a partir de cv/master.md.

Uso: .venv/bin/python scripts/generate_cv.py VAGA.txt NOME_DA_SAIDA
Saida: cv/out/NOME_DA_SAIDA.pdf (e .md). Requer OPENROUTER_API_KEY; o modelo vem de OPENROUTER_MODEL.
"""
import os
import sys

import pymupdf

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path[:0] = [os.path.join(ROOT, "backend", "models")]

from llm import generate_optimized_resume  # noqa: E402
from pdf_converter import markdown_to_pdf  # noqa: E402

MAX_PAGES = 2
LENGTH_RULE = (
    "\n\nRESTRICAO DE TAMANHO (obrigatoria): o curriculo final deve caber em {pages} paginas A4. "
    "Mantenha TODOS os cargos, mas {detail}. Resumo de ate 4 linhas. Nao invente nada."
)
DETAILS = [
    "use 3-5 marcadores nos cargos mais relevantes para a vaga e 1-2 nos demais",
    "use no maximo 3 marcadores nos cargos relevantes, 1 nos demais e uma lista de competencias curta (ate 8 itens)",
]


def count_pages(pdf_path):
    with pymupdf.open(pdf_path) as doc:
        return len(doc)


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    job_path, name = sys.argv[1], sys.argv[2]
    with open(os.path.join(ROOT, "cv", "master.md"), encoding="utf-8") as f:
        master = f.read()
    with open(job_path, encoding="utf-8") as f:
        job = f.read()

    out_dir = os.path.join(ROOT, "cv", "out")
    os.makedirs(out_dir, exist_ok=True)
    md_path = os.path.join(out_dir, f"{name}.md")
    pdf_path = os.path.join(out_dir, f"{name}.pdf")

    for detail in DETAILS:
        md = generate_optimized_resume(master, job + LENGTH_RULE.format(pages=MAX_PAGES, detail=detail))
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md)
        markdown_to_pdf(md_path, pdf_path)
        pages = count_pages(pdf_path)
        print(f"paginas: {pages}")
        if pages <= MAX_PAGES:
            break
    else:
        print(f"AVISO: ainda com {pages} paginas apos {len(DETAILS)} tentativas", file=sys.stderr)
    print(pdf_path)


if __name__ == "__main__":
    main()
