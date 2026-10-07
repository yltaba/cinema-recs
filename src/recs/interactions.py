"""Instrumentação local, sem aprendizado e sem inferir associação de ações."""

import json
from uuid import uuid4


def ensure_schema(con):
    con.execute("""
        CREATE TABLE IF NOT EXISTS interactions (
            interaction_id TEXT PRIMARY KEY, created_at TIMESTAMP DEFAULT current_timestamp,
            mode TEXT, query JSON, options JSON, diagnostic JSON, config JSON);
        CREATE TABLE IF NOT EXISTS interaction_actions (
            action_id TEXT PRIMARY KEY, created_at TIMESTAMP DEFAULT current_timestamp,
            interaction_id TEXT, tmdb_id INTEGER, action TEXT, detail JSON);
    """)


def record_query(con, mode, query, rows, diagnostic, cfg):
    ensure_schema(con)
    iid = str(uuid4())
    options = [{"tmdb_id": r["tmdb_id"], "rank": rank, "score": r["score"],
                "personal_score": r["base"], "context_score": r["context_score"], "sources": r["sources"],
                "origin_complement": bool(r.get("origin_complement"))}
               for rank, r in enumerate(rows, 1)]
    # Whitelist: jamais capturar credenciais ou configurações arbitrárias de HTTP.
    snapshot = {k: cfg[k] for k in ("profile", "candidates", "score", "now", "retrieval", "availability") if k in cfg}
    con.execute("INSERT INTO interactions (interaction_id, mode, query, options, diagnostic, config) VALUES (?, ?, ?, ?, ?, ?)",
                [iid, mode, json.dumps(query), json.dumps(options), json.dumps(diagnostic), json.dumps(snapshot)])
    return iid


def validate_action(con, interaction_id, ids):
    if interaction_id is None:
        return
    ensure_schema(con)
    row = con.execute("SELECT options FROM interactions WHERE interaction_id = ?", [interaction_id]).fetchone()
    if not row:
        raise ValueError("interação desconhecida")
    offered = {r["tmdb_id"] for r in json.loads(row[0])}
    if not set(ids) <= offered:
        raise ValueError("filme não pertence às opções dessa interação")


def record_action(con, action, ids, interaction_id=None, detail=None):
    validate_action(con, interaction_id, ids)
    ensure_schema(con)
    for tid in dict.fromkeys(ids):
        con.execute("INSERT INTO interaction_actions (action_id, interaction_id, tmdb_id, action, detail) VALUES (?, ?, ?, ?, ?)",
                    [str(uuid4()), interaction_id, tid, action, json.dumps(detail or {})])


def get(con, iid):
    ensure_schema(con)
    row = con.execute("SELECT mode, query, options, diagnostic FROM interactions WHERE interaction_id = ?", [iid]).fetchone()
    if not row:
        raise ValueError("interação desconhecida")
    actions = con.execute("SELECT tmdb_id, action, detail FROM interaction_actions WHERE interaction_id = ? ORDER BY created_at, action_id", [iid]).fetchall()
    return {"interaction_id": iid, "mode": row[0], "consulta": json.loads(row[1]),
            "opcoes": json.loads(row[2]), "diagnostico": json.loads(row[3]),
            "acoes": [{"tmdb_id": tid, "acao": action, "detalhe": json.loads(detail)} for tid, action, detail in actions]}
