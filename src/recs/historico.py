"""Consulta por título: o filme já está no histórico (export, feedback ou avaliação privada)?

Serve para conferir sugestões de conhecimento geral, que não passam pelo ranking.
"""

import json
import re
import unicodedata

SEEN_VERDICTS = ("liked", "disliked", "already_seen")


def normalize(text):
    # Tira acentos, mas preserva escritas não latinas (天国と地獄 não pode virar vazio).
    text = "".join(c for c in unicodedata.normalize("NFKD", text or "") if not unicodedata.combining(c))
    return " ".join(re.sub(r"[\W_]+", " ", text.casefold()).split())


def parse_term(term):
    """'Get Out (2017)' ou 'Get Out 2017' -> ('get out', 2017)."""
    m = re.fullmatch(r"\s*(.+?)\s*\(?((?:18|19|20)\d\d)\)?\s*", term)
    if m and normalize(m.group(1)):
        return normalize(m.group(1)), int(m.group(2))
    return normalize(term), None


def _tmdb_titles(payload):
    data = json.loads(payload)
    titles = {data.get("title"), data.get("original_title")}
    for t in (data.get("translations") or {}).get("translations", []):
        titles.add((t.get("data") or {}).get("title"))
    year = (data.get("release_date") or "")[:4]
    return data.get("title"), int(year) if year.isdigit() else None, {normalize(t) for t in titles if t}


def lookup(con, terms, feedback, ratings, limit=10):
    lb = con.execute("""
        SELECT f.name, f.year, m.tmdb_id, f.watched, f.in_watchlist, f.rating, f.liked
        FROM lb_films f LEFT JOIN film_map m USING (lb_uri)""").fetchall()
    tmdb = {tid: _tmdb_titles(p) for tid, p in con.execute("SELECT tmdb_id, payload FROM tmdb_raw").fetchall()}
    entries = []
    lb_ids = set()
    for name, year, tid, watched, watchlist, rating, liked in lb:
        names = {normalize(name)} | (tmdb[tid][2] if tid in tmdb else set())
        entries.append(dict(titulo=name, ano=year, tmdb_id=tid, names=names, watched=bool(watched),
                            watchlist=bool(watchlist), nota_letterboxd=rating, like_letterboxd=bool(liked)))
        lb_ids.add(tid)
    # Fora do export, só interessa o que tem feedback ou avaliação privada.
    for tid in (set(feedback) | set(ratings)) - lb_ids:
        title, year, names = tmdb.get(tid, (ratings.get(tid, {}).get("titulo"), None, set()))
        names = names | {normalize(ratings.get(tid, {}).get("titulo", ""))}
        entries.append(dict(titulo=title, ano=year, tmdb_id=tid, names=names - {""}, watched=False,
                            watchlist=False, nota_letterboxd=None, like_letterboxd=False))

    out = []
    for term in terms:
        q, year = parse_term(term)
        if not q:
            out.append({"termo": term, "exato": False, "resultados": []})
            continue
        pool = [e for e in entries if year is None or e["ano"] is None or abs(e["ano"] - year) <= 1]
        exact = [e for e in pool if q in e["names"]]
        hits = exact or [e for e in pool if len(q) >= 4 and any(q in n for n in e["names"])]
        out.append({"termo": term, "exato": bool(exact),
                    "resultados": [_result(e, feedback, ratings) for e in hits[:limit]]})
    return out


def _result(e, feedback, ratings):
    verdict = feedback.get(e["tmdb_id"])
    rated = e["tmdb_id"] in ratings
    return {"titulo": e["titulo"], "ano": e["ano"], "tmdb_id": e["tmdb_id"],
            "visto": e["watched"] or verdict in SEEN_VERDICTS or rated,
            "watchlist": e["watchlist"], "nota_letterboxd": e["nota_letterboxd"],
            "like_letterboxd": e["like_letterboxd"], "feedback": verdict, "avaliacao_privada": rated}
