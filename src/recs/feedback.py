"""Vocabulário persistente; not_now pertence somente a uma interação."""

import csv
from datetime import date

ALIASES = {"bom": "liked", "nao": "not_interested", "ja_vi": "already_seen"}
PERSISTENT = ("liked", "disliked", "not_interested", "already_seen")
VERDICTS = (*PERSISTENT, "not_now", *ALIASES)


def normalize(verdict):
    return ALIASES.get(verdict, verdict)


def load(path):
    if not path.exists():
        return {}
    with open(path, encoding="utf-8-sig", newline="") as f:
        return {int(r["tmdb_id"]): normalize(r["veredito"].strip()) for r in csv.DictReader(f)
                if r.get("tmdb_id") and normalize(r["veredito"].strip()) in PERSISTENT}


def excluded(feedback):
    # liked/disliked implicam assistido; not_interested não é avaliação negativa de gosto.
    return {i for i, v in feedback.items() if normalize(v) in PERSISTENT}


def append(path, tid, verdict):
    verdict = normalize(verdict)
    if verdict not in PERSISTENT:
        raise ValueError("veredito não persistente")
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists() or path.stat().st_size == 0
    with open(path, "a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        if new:
            writer.writerow(["tmdb_id", "veredito", "data"])
        writer.writerow([tid, verdict, date.today().isoformat()])
