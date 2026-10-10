"""Avaliações privadas (nota, like e crítica) de filmes assistidos fora do export do Letterboxd."""

import csv
from datetime import date

COLUMNS = ["tmdb_id", "titulo", "nota", "like", "critica", "data", "interaction_id"]


def valid_rating(nota):
    return nota is None or (0.5 <= nota <= 5 and nota * 2 == int(nota * 2))


def load(path):
    """Última linha por tmdb_id prevalece. nota None = assistido sem nota."""
    if not path.exists():
        return {}
    out = {}
    with open(path, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            if not r.get("tmdb_id"):
                continue
            nota = (r.get("nota") or "").strip()
            out[int(r["tmdb_id"])] = {
                "titulo": r.get("titulo", ""),
                "nota": float(nota) if nota else None,
                "like": (r.get("like") or "").strip().lower() == "true",
                "critica": r.get("critica", ""),
                "data": r.get("data", ""),
                "interaction_id": r.get("interaction_id") or None,
            }
    return out


def excluded(ratings):
    # Todo filme avaliado foi assistido.
    return set(ratings)


def append(path, tid, titulo, nota, like, critica="", interaction_id=None):
    if not valid_rating(nota):
        raise ValueError("nota deve estar entre 0,5 e 5, em passos de 0,5")
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists() or path.stat().st_size == 0
    with open(path, "a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        if new:
            writer.writerow(COLUMNS)
        writer.writerow([tid, titulo, "" if nota is None else nota, "true" if like else "false",
                         critica or "", date.today().isoformat(), interaction_id or ""])


def resolve(con, ratings):
    """Qual nota vale para cada avaliação privada: a mais recente entre ela e o Letterboxd.

    A data do Letterboxd é a última atividade do filme no export (visto, diário ou nota). Empate favorece a
    privada, que costuma vir depois de pensar o filme; avaliação privada sem nota ou sem data não substitui
    uma do export. Devolve {tmdb_id: {"vale", "nota_letterboxd", "data_letterboxd", "diverge"}}."""
    if not ratings:
        return {}
    lb = {tid: (rating, logged) for tid, rating, logged in con.execute("""
        SELECT m.tmdb_id, avg(l.rating), max(l.last_logged)
        FROM lb_films l JOIN film_map m USING (lb_uri)
        WHERE l.watched AND m.tmdb_id IS NOT NULL GROUP BY m.tmdb_id""").fetchall()}
    out = {}
    for tid, r in ratings.items():
        if tid not in lb:
            out[tid] = {"vale": "privada", "nota_letterboxd": None, "data_letterboxd": None, "diverge": False}
            continue
        lb_rating, lb_date = lb[tid]
        lb_date = lb_date.isoformat() if lb_date else None
        newer = r["nota"] is not None and bool(r.get("data")) and (lb_date is None or r["data"] >= lb_date)
        out[tid] = {"vale": "privada" if newer else "letterboxd", "nota_letterboxd": lb_rating,
                    "data_letterboxd": lb_date,
                    "diverge": r["nota"] is not None and lb_rating is not None and r["nota"] != lb_rating}
    return out
