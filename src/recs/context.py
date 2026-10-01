"""Modo contexto (Fase 7): restrições do momento ("comédia, até 2h, nos meus serviços") sobre o perfil.

O pedido em linguagem natural é traduzido em flags pelo Claude Code (ver CLAUDE.md); aqui tudo é
determinístico. O pool da Fase 4 é ampliado com /discover/movie nos mesmos filtros, e o ranking final é

    score_contexto = score × (1 + prefer_bonus · nº de keywords preferidas no filme)   (se score > 0)

com gênero, duração, idioma, país, anos e keywords evitadas como filtros rígidos.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import duckdb
from unidecode import unidecode

from recs.availability import is_subscribed

# Gêneros de filme do TMDB (ids fixos), com apelidos em português e inglês.
GENRES: dict[int, tuple[str, ...]] = {
    28: ("action", "acao"),
    12: ("adventure", "aventura"),
    16: ("animation", "animacao"),
    35: ("comedy", "comedia"),
    80: ("crime", "policial"),
    99: ("documentary", "documentario"),
    18: ("drama",),
    10751: ("family", "familia"),
    14: ("fantasy", "fantasia"),
    36: ("history", "historia", "historico"),
    27: ("horror", "terror"),
    10402: ("music", "musica", "musical"),
    9648: ("mystery", "misterio"),
    10749: ("romance", "romantico"),
    878: ("science fiction", "sci-fi", "scifi", "ficcao cientifica", "ficcao"),
    53: ("thriller", "suspense"),
    10752: ("war", "guerra"),
    37: ("western", "faroeste"),
}
_ALIASES = {alias: gid for gid, names in GENRES.items() for alias in names}


def _norm(s: str) -> str:
    return unidecode(s).lower().strip()


def parse_genres(values: list[str]) -> list[int]:
    out = []
    for v in values:
        for part in v.split(","):
            if not part.strip():
                continue
            gid = _ALIASES.get(_norm(part))
            if gid is None:
                raise ValueError(f"gênero desconhecido: {part.strip()!r} (use um de: "
                                 + ", ".join(names[0] for names in GENRES.values()) + ")")
            out.append(gid)
    return sorted(set(out))


def parse_years(s: str | None) -> tuple[int | None, int | None]:
    """'1990s' / '90s' → (1990, 1999); '1980-2000'; '2010-'; '-1979'; '1975' → (1975, 1975)."""
    if not s:
        return None, None
    s = s.strip().lower()
    if m := re.fullmatch(r"(\d{2}|\d{4})s", s):
        d = int(m[1])
        d = d + (1900 if d >= 20 else 2000) if d < 100 else d
        return d, d + 9
    if m := re.fullmatch(r"(\d{4})?\s*-\s*(\d{4})?", s):
        if not (m[1] or m[2]):
            raise ValueError(f"intervalo de anos inválido: {s!r}")
        return (int(m[1]) if m[1] else None), (int(m[2]) if m[2] else None)
    if re.fullmatch(r"\d{4}", s):
        return int(s), int(s)
    raise ValueError(f"anos inválidos: {s!r} (ex.: 1990s, 1980-2000, 2010-)")


def _split(values: list[str] | None) -> list[str]:
    return [p.strip() for v in values or [] for p in v.split(",") if p.strip()]


@dataclass
class Context:
    genres: list[int] = field(default_factory=list)       # qualquer um deles (OU); todos com all_genres
    all_genres: bool = False
    max_runtime: int | None = None
    min_runtime: int | None = None
    languages: list[str] = field(default_factory=list)    # idioma original (ISO 639-1)
    countries: list[str] = field(default_factory=list)    # país de produção (ISO 3166-1)
    year_from: int | None = None
    year_to: int | None = None
    prefer_keywords: list[str] = field(default_factory=list)
    avoid_keywords: list[str] = field(default_factory=list)
    subscribed_only: bool = False
    streaming_only: bool = False
    exclude: set[int] = field(default_factory=set)

    def is_empty(self) -> bool:
        return not (self.genres or self.max_runtime or self.min_runtime or self.languages or self.countries
                    or self.year_from or self.year_to or self.prefer_keywords or self.avoid_keywords
                    or self.subscribed_only or self.streaming_only)

    def describe(self) -> str:
        names = {gid: n[0] for gid, n in GENRES.items()}
        parts = []
        if self.genres:
            parts.append("gênero: " + (" + " if self.all_genres else " ou ").join(names[g] for g in self.genres))
        if self.min_runtime or self.max_runtime:
            parts.append(f"duração: {self.min_runtime or 0}–{self.max_runtime or '∞'} min")
        if self.languages:
            parts.append("idioma: " + "/".join(self.languages))
        if self.countries:
            parts.append("país: " + "/".join(self.countries))
        if self.year_from or self.year_to:
            parts.append(f"anos: {self.year_from or '…'}–{self.year_to or '…'}")
        if self.prefer_keywords:
            parts.append("prefere: " + ", ".join(self.prefer_keywords))
        if self.avoid_keywords:
            parts.append("evita: " + ", ".join(self.avoid_keywords))
        if self.subscribed_only:
            parts.append("só nos meus serviços")
        elif self.streaming_only:
            parts.append("só streaming")
        return " · ".join(parts) or "sem restrições"


def build(genre=None, max_runtime=None, min_runtime=None, language=None, country=None, years=None,
          prefer=None, avoid=None, subscribed_only=False, streaming_only=False, exclude=None,
          all_genres=False) -> Context:
    y0, y1 = parse_years(years)
    return Context(
        genres=parse_genres(genre or []), all_genres=all_genres, max_runtime=max_runtime, min_runtime=min_runtime,
        languages=[x.lower() for x in _split(language)], countries=[x.upper() for x in _split(country)],
        year_from=y0, year_to=y1, prefer_keywords=_split(prefer), avoid_keywords=_split(avoid),
        subscribed_only=subscribed_only, streaming_only=streaming_only,
        exclude={int(x) for x in _split(exclude)},
    )


# --- keywords -------------------------------------------------------------------------------------

def keyword_ids(con: duckdb.DuckDBPyConnection, terms: list[str], whole_word: bool) -> dict[int, str]:
    """Keywords do cache que casam com os termos: nome exato (preferidas) ou termo como palavra
    dentro do nome (evitadas: 'rape' também pega 'rape and revenge')."""
    if not terms:
        return {}
    wanted = [_norm(t) for t in terms]
    pats = [re.compile(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])") for t in wanted]
    out = {}
    for kid, name in con.execute("SELECT DISTINCT keyword_id, name FROM film_keywords").fetchall():
        n = _norm(name or "")
        if (any(p.search(n) for p in pats) if whole_word else n in wanted):
            out[kid] = name
    return out


def search_keywords(con: duckdb.DuckDBPyConnection, term: str, limit: int = 30) -> list[tuple[str, int]]:
    return con.execute("""
        SELECT name, count(DISTINCT tmdb_id) AS n FROM film_keywords
        WHERE strip_accents(lower(name)) LIKE '%' || ? || '%'
        GROUP BY name ORDER BY n DESC, name LIMIT ?""", [_norm(term), limit]).fetchall()


# --- discover --------------------------------------------------------------------------------------

async def provider_ids(tmdb, cfg: dict) -> list[int]:
    """Ids TMDB dos serviços assinados na região (variantes com anúncios incluídas, canais não)."""
    region = cfg["availability"]["region"]
    data = await tmdb.get("/watch/providers/movie", cfg["tmdb"]["providers_ttl_days"], watch_region=region)
    subs = cfg["availability"]["provedores_assinados"]
    return sorted(p["provider_id"] for p in data.get("results", []) if is_subscribed(p["provider_name"], subs))


def discover_params(ctx: Context, cfg: dict, providers: list[int]) -> list[dict]:
    """Uma consulta por ordenação: as mais bem avaliadas (com piso de votos) e as mais populares."""
    n = cfg["now"]
    base: dict = {"include_adult": "false", "vote_count.gte": n["discover_min_votes"], "language": "en-US"}
    if ctx.genres:
        base["with_genres"] = ("," if ctx.all_genres else "|").join(map(str, ctx.genres))
    if ctx.max_runtime:
        base["with_runtime.lte"] = ctx.max_runtime
    if ctx.min_runtime:
        base["with_runtime.gte"] = ctx.min_runtime
    if len(ctx.languages) == 1:
        base["with_original_language"] = ctx.languages[0]
    if ctx.countries:
        base["with_origin_country"] = "|".join(ctx.countries)
    if ctx.year_from:
        base["primary_release_date.gte"] = f"{ctx.year_from}-01-01"
    if ctx.year_to:
        base["primary_release_date.lte"] = f"{ctx.year_to}-12-31"
    if ctx.subscribed_only or ctx.streaming_only:
        base["watch_region"] = cfg["availability"]["region"]
        base["with_watch_monetization_types"] = "flatrate|free|ads"
        if ctx.subscribed_only and providers:
            base["with_watch_providers"] = "|".join(map(str, providers))
    return [{**base, "sort_by": "vote_average.desc", "vote_count.gte": n["discover_quality_votes"]},
            {**base, "sort_by": "popularity.desc"}]


async def discover(tmdb, ctx: Context, cfg: dict) -> set[int]:
    if ctx.is_empty():
        return set()
    providers = await provider_ids(tmdb, cfg) if ctx.subscribed_only else []
    ttl = cfg["tmdb"]["providers_ttl_days"]  # resultados dependem de disponibilidade: cache curto
    out = set()
    for params in discover_params(ctx, cfg, providers):
        for page in range(1, cfg["now"]["discover_pages"] + 1):
            data = await tmdb.get("/discover/movie", ttl, page=page, **params)
            out |= {x["id"] for x in data.get("results", []) if not x.get("adult")}
            if page >= data.get("total_pages", 0):
                break
    return out


# --- filtro e ranking ------------------------------------------------------------------------------

def matching(con: duckdb.DuckDBPyConnection, ctx: Context, avoid_ids: list[int], prefer_ids: list[int]
             ) -> dict[int, list[str]]:
    """{tmdb_id: keywords preferidas presentes} para os candidatos elegíveis que passam nos filtros.
    Também grava a tabela temporária context_ok, usada por score.ranked(only=...)."""
    con.execute("""
        CREATE OR REPLACE TEMP TABLE context_ok AS
        SELECT s.tmdb_id,
               (SELECT list(k.name ORDER BY k.name) FROM film_keywords k
                 WHERE k.tmdb_id = s.tmdb_id AND list_contains($prefer, k.keyword_id)) AS hits
        FROM scores s JOIN film_meta m USING (tmdb_id)
        WHERE s.eligible
          AND NOT list_contains($exclude, s.tmdb_id)
          AND (len($genres) = 0 OR (SELECT count(DISTINCT g.genre_id) FROM film_genres g
                WHERE g.tmdb_id = s.tmdb_id AND list_contains($genres, g.genre_id))
                >= CASE WHEN $all_genres THEN len($genres) ELSE 1 END)
          AND ($max_rt IS NULL OR (m.runtime > 0 AND m.runtime <= $max_rt))
          AND ($min_rt IS NULL OR m.runtime >= $min_rt)
          AND (len($langs) = 0 OR list_contains($langs, m.original_language))
          AND (len($countries) = 0 OR EXISTS (SELECT 1 FROM film_countries c
                WHERE c.tmdb_id = s.tmdb_id AND list_contains($countries, c.iso)))
          AND ($y0 IS NULL OR m.year >= $y0)
          AND ($y1 IS NULL OR m.year <= $y1)
          AND NOT EXISTS (SELECT 1 FROM film_keywords k
                WHERE k.tmdb_id = s.tmdb_id AND list_contains($avoid, k.keyword_id))
    """, {"exclude": sorted(ctx.exclude), "genres": ctx.genres, "all_genres": ctx.all_genres, "max_rt": ctx.max_runtime,
          "min_rt": ctx.min_runtime, "langs": ctx.languages, "countries": ctx.countries,
          "y0": ctx.year_from, "y1": ctx.year_to, "avoid": avoid_ids, "prefer": prefer_ids})
    return {tid: hits or [] for tid, hits in con.execute("SELECT tmdb_id, hits FROM context_ok").fetchall()}


def warnings(ctx: Context, avoid_kw: dict[int, str], prefer_kw: dict[int, str], found: int, wanted: int
             ) -> list[str]:
    out = []
    matched = {_norm(v) for v in prefer_kw.values()}
    for t in ctx.prefer_keywords:
        if _norm(t) not in matched:
            out.append(f"keyword preferida sem correspondência exata: {t!r} (veja `recs keywords {t}`)")
    for t in ctx.avoid_keywords:
        if not any(_norm(t) in _norm(v) for v in avoid_kw.values()):
            out.append(f"keyword evitada sem correspondência: {t!r}")
    if found < wanted:
        out.append(f"só {found} filmes passaram nos filtros; afrouxe alguma restrição")
    return out


def rerank(rows: list[dict], hits: dict[int, list[str]], bonus: float) -> list[dict]:
    for r in rows:
        r["prefer_hits"] = hits.get(r["tmdb_id"], [])
        k = len(r["prefer_hits"])
        r["context_score"] = r["score"] * (1 + bonus * k) if r["score"] > 0 else r["score"]
    return sorted(rows, key=lambda r: r["context_score"], reverse=True)
