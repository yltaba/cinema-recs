"""Eval online: nota dada aos filmes que o sistema indicou, comparada com o que foi visto sem indicação.

Só lê o banco e os CSVs de overrides; não acessa a rede nem grava tabelas.
"""

import csv
import json
from datetime import date

from recs import feedback as feedback_mod, ratings as ratings_mod

WATCHED_VERDICTS = ("liked", "disliked", "already_seen")
MIN_SAMPLE = 20


def load_feedback_dates(path):
    """Último veredito persistente por filme, com a data (feedback.load descarta a data)."""
    if not path.exists():
        return {}
    out = {}
    with open(path, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            v = feedback_mod.normalize((r.get("veredito") or "").strip())
            if r.get("tmdb_id") and v in feedback_mod.PERSISTENT:
                out[int(r["tmdb_id"])] = (v, r.get("data") or None)
    return out


def offers(con):
    """tmdb_id -> primeira data em que foi indicado, melhor posição e fontes."""
    out = {}
    for created, options in con.execute(
            "SELECT created_at, options FROM interactions ORDER BY created_at").fetchall():
        for o in json.loads(options):
            e = out.setdefault(o["tmdb_id"], {"desde": created.date(), "rank": o["rank"], "fontes": set()})
            e["rank"] = min(e["rank"], o["rank"])
            e["fontes"].update(o.get("sources") or [])
    return out


def outcomes(con, ratings, feedback):
    """tmdb_id -> (nota que prevalece ou None, data, origem) de tudo que foi assistido."""
    status = ratings_mod.resolve(con, ratings)
    out = {}
    for tid, rating, logged in con.execute("""
            SELECT m.tmdb_id, avg(l.rating), max(l.last_logged)
            FROM lb_films l JOIN film_map m USING (lb_uri)
            WHERE l.watched AND m.tmdb_id IS NOT NULL GROUP BY m.tmdb_id""").fetchall():
        out[tid] = (rating, logged, "letterboxd")
    for tid, (verdict, d) in feedback.items():
        if verdict in WATCHED_VERDICTS and tid not in out:
            out[tid] = (None, date.fromisoformat(d) if d else None, "feedback")
    for tid, r in ratings.items():
        if status[tid]["vale"] == "privada" or tid not in out:
            out[tid] = (r["nota"], date.fromisoformat(r["data"]) if r.get("data") else None, "privada")
    return out


def _mean(xs):
    return round(sum(xs) / len(xs), 2) if xs else None


def evaluate(con, ratings, feedback, titles=None):
    titles = titles or {}
    off = offers(con)
    seen = outcomes(con, ratings, feedback)
    if not off:
        return {"indicados": 0, "avisos": ["nenhuma interação registrada"]}
    start = min(e["desde"] for e in off.values())
    # Visto depois da primeira indicação; sem data não dá para afirmar que a indicação veio antes.
    hits = {tid: seen[tid] for tid, e in off.items() if tid in seen and seen[tid][1] and seen[tid][1] >= e["desde"]}
    base = [n for tid, (n, d, _) in seen.items() if tid not in off and n is not None and d and d >= start]
    overall = [n for n, _, src in seen.values() if n is not None and src == "letterboxd"]

    by_source = {}
    for tid, e in off.items():
        # "filmografia:director" e "filmografia:cinematographer" contam uma vez em "filmografia".
        for s in {f.split(":")[0] for f in e["fontes"]} or {"(sem fonte)"}:
            b = by_source.setdefault(s, {"indicados": 0, "assistidos": 0, "notas": []})
            b["indicados"] += 1
            if tid in hits:
                b["assistidos"] += 1
                if hits[tid][0] is not None:
                    b["notas"].append(hits[tid][0])

    notes = [n for n, _, _ in hits.values() if n is not None]
    avisos = []
    if len(notes) < MIN_SAMPLE:
        avisos.append(f"amostra pequena: {len(notes)} filmes indicados com nota (sinal útil a partir de ~{MIN_SAMPLE})")
    if len(base) < MIN_SAMPLE:
        avisos.append(f"base do período pequena: {len(base)} notas sem indicação desde {start}")
    return {
        "periodo_desde": start.isoformat(),
        "indicados": len(off),
        "assistidos": len(hits),
        "com_nota": len(notes),
        "media_indicados": _mean(notes),
        "media_sem_indicacao_periodo": _mean(base), "n_sem_indicacao_periodo": len(base),
        "media_geral_letterboxd": _mean(overall),
        "por_fonte": sorted(({"fonte": s, "indicados": b["indicados"], "assistidos": b["assistidos"],
                              "com_nota": len(b["notas"]), "media": _mean(b["notas"])}
                             for s, b in by_source.items()), key=lambda x: -x["indicados"]),
        "filmes": [{"tmdb_id": tid, "titulo": titles.get(tid), "nota": n, "data": d.isoformat(), "origem": src,
                    "indicado_em": off[tid]["desde"].isoformat(), "melhor_rank": off[tid]["rank"],
                    "fontes": sorted(off[tid]["fontes"])}
                   for tid, (n, d, src) in sorted(hits.items(), key=lambda x: x[1][1])],
        "avisos": avisos,
    }
