"""Coletor de sentenças do TJSP (Consulta de Julgados de 1º Grau - e-SAJ/cjpg).

Uso:
    python tjsp_cjpg.py "dano moral negativação" --inicio 01/01/2026 --fim 30/09/2026 --paginas 5

Grava em sentencas.db (SQLite, com busca textual FTS5) e sentencas.csv.
"""
import argparse
import csv
import re
import sqlite3
import time

import requests
from bs4 import BeautifulSoup

BASE = "https://esaj.tjsp.jus.br/cjpg"
CAMPOS = {
    "Classe": "classe",
    "Assunto": "assunto",
    "Magistrado": "magistrado",
    "Comarca": "comarca",
    "Foro": "foro",
    "Vara": "vara",
    "Data de Disponibilização": "data",
}


def buscar(sessao, termo, inicio="", fim="", pagina=1):
    if pagina == 1:
        params = {
            "conteudoJulgado": termo,
            "dadosConsulta.dtInicio": inicio,
            "dadosConsulta.dtFim": fim,
            "dadosConsulta.ordenacao": "DESC",
        }
        r = sessao.get(f"{BASE}/pesquisar.do", params=params, timeout=60)
    else:
        # a paginação usa a pesquisa guardada na sessão (cookie)
        r = sessao.get(f"{BASE}/trocarDePagina.do", params={"pagina": pagina}, timeout=60)
    r.raise_for_status()
    r.encoding = "utf-8"
    return r.text


def extrair(html):
    soup = BeautifulSoup(html, "html.parser")
    total = None
    m = re.search(r"Resultados\s+\d+\s+a\s+\d+\s+de\s+(\d+)", soup.get_text(" "))
    if m:
        total = int(m.group(1))
    sentencas = []
    for bloco in soup.select("#divDadosResultado tr.fundocinza1"):
        s = {"processo": "", "texto": ""}
        link = bloco.select_one("a.linkPopupDetalhesProcesso, span.fonteNegrito")
        if link:
            s["processo"] = link.get_text(strip=True)
        for linha in bloco.select("tr"):
            t = " ".join(linha.get_text(" ", strip=True).split())
            for rotulo, chave in CAMPOS.items():
                if t.startswith(rotulo + ":"):
                    s[chave] = t[len(rotulo) + 1:].strip()
        # texto integral fica num div oculto; o resumo, num visível
        oculto = bloco.select_one("div[style*='display: none'], div[style*='display:none']")
        visivel = bloco.select_one("div[align='justify']")
        alvo = oculto or visivel
        if alvo:
            s["texto"] = alvo.get_text("\n", strip=True)
        if s["processo"]:
            sentencas.append(s)
    return total, sentencas


def salvar(sentencas, db="sentencas.db", csv_path="sentencas.csv", tribunal="TJSP"):
    con = sqlite3.connect(db)
    con.execute(
        """CREATE TABLE IF NOT EXISTS sentencas (
            tribunal TEXT, processo TEXT, classe TEXT, assunto TEXT, magistrado TEXT,
            comarca TEXT, foro TEXT, vara TEXT, data TEXT, texto TEXT,
            PRIMARY KEY (tribunal, processo, data))"""
    )
    con.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS busca USING fts5("
        "processo, assunto, texto, content='sentencas', tokenize='unicode61 remove_diacritics 2')"
    )
    cols = ["processo", "classe", "assunto", "magistrado", "comarca", "foro", "vara", "data", "texto"]
    novos = 0
    for s in sentencas:
        cur = con.execute(
            f"INSERT OR IGNORE INTO sentencas (tribunal, {', '.join(cols)}) VALUES (?{', ?' * len(cols)})",
            [tribunal] + [s.get(c, "") for c in cols],
        )
        if cur.rowcount:
            novos += 1
            con.execute(
                "INSERT INTO busca (rowid, processo, assunto, texto) VALUES (?, ?, ?, ?)",
                (cur.lastrowid, s.get("processo", ""), s.get("assunto", ""), s.get("texto", "")),
            )
    con.commit()
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["tribunal"] + cols)
        w.writerows(con.execute(f"SELECT tribunal, {', '.join(cols)} FROM sentencas"))
    con.close()
    return novos


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("termo")
    ap.add_argument("--inicio", default="", help="dd/mm/aaaa")
    ap.add_argument("--fim", default="", help="dd/mm/aaaa")
    ap.add_argument("--paginas", type=int, default=3)
    ap.add_argument("--pausa", type=float, default=2.0, help="segundos entre páginas")
    a = ap.parse_args()

    sessao = requests.Session()
    sessao.headers["User-Agent"] = "Mozilla/5.0 (pesquisa academica - banco de sentencas)"
    for p in range(1, a.paginas + 1):
        total, sentencas = extrair(buscar(sessao, a.termo, a.inicio, a.fim, p))
        if p == 1:
            print(f"Total de resultados: {total}")
        if not sentencas:
            break
        print(f"Página {p}: {len(sentencas)} sentenças, {salvar(sentencas)} novas")
        time.sleep(a.pausa)


if __name__ == "__main__":
    main()
