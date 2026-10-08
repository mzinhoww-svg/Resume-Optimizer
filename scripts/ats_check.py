"""Checa cobertura de palavras-chave de uma vaga no texto de um PDF.

Uso: .venv/bin/python scripts/ats_check.py CV.pdf "kw1;kw2;..."
"""
import re
import sys

import pymupdf

pdf, kws = sys.argv[1], sys.argv[2].split(";")
text = " ".join(p.get_text() for p in pymupdf.open(pdf)).lower()
text = re.sub(r"\s+", " ", text)
hit, miss = [], []
for k in kws:
    k = k.strip()
    (hit if k.lower() in text else miss).append(k)
print(f"cobertura: {len(hit)}/{len(kws)}")
print("FALTANDO:", "; ".join(miss) if miss else "nenhuma")
