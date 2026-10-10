"""Consulta determinística compartilhada pela CLI e pelo modo de exploração."""

from dataclasses import asdict

from recs import availability, candidates, context, eligibility, enrich, profile, score, feedback as feedback_mod, ratings as ratings_mod


def structured_context(ctx):
    return {**asdict(ctx), "exclude": sorted(ctx.exclude)}


async def query(con, tmdb, cfg, ctx, n, root, feedback, ratings=None):
    seen = candidates.seen_ids(con) | feedback_mod.excluded(feedback) | ratings_mod.excluded(ratings or {})
    pool = await candidates.generate(con, tmdb, cfg, seen, root / "seeds")
    discovered = await context.discover(tmdb, ctx, cfg) - seen
    for tid in discovered:
        pool.add(tid, "discover")
    candidates.save(con, pool)
    st = await enrich.fetch_movies(con, tmdb, sorted(pool.sources), cfg["tmdb"]["metadata_ttl_days"],
                                  region=cfg["availability"]["region"])
    if st.fetched:
        enrich.derive(con)
        profile.build_film_features(con)
    eligibility.build(con, cfg)
    avoid_kw = context.keyword_ids(con, ctx.avoid_keywords, whole_word=True)
    prefer_kw = context.keyword_ids(con, ctx.prefer_keywords, whole_word=False)
    hits, filter_counts = context.filter_counts(con, ctx, sorted(avoid_kw), sorted(prefer_kw))
    diagnostic = {
        "retrieved": len(pool.sources),
        "enriched": con.execute("SELECT count(*) FROM eligibility").fetchone()[0],
        "eligible": con.execute("SELECT count(*) FROM eligibility WHERE eligible").fetchone()[0],
        "context_matched": len(hits),
        "filters": filter_counts,
        "retrieval_sources": candidates.source_counts(pool),
    }
    score.compute(con, cfg, eligibility_ready=True)
    ranked = context.rerank(score.ranked(con, only="context_ok"), hits, cfg["now"]["prefer_bonus"])
    diagnostic["ranked"] = len(ranked)
    rows, diagnostic["availability"] = await availability.select(con, tmdb, ranked, cfg, ctx, n)
    diagnostic["returned"] = len(rows)
    genres = dict(con.execute("SELECT tmdb_id, list(name ORDER BY name) FROM film_genres GROUP BY 1").fetchall())
    for r in rows:
        r["reasons"] = score.reasons(con, r["tmdb_id"])
        r["genres"] = genres.get(r["tmdb_id"], [])
    warnings = context.warnings(ctx, avoid_kw, prefer_kw, len(rows), n)
    if diagnostic["availability"]["stop_reason"] == "limit":
        warnings.append("Limite de verificação de disponibilidade atingido; há candidatos não verificados.")
    return rows, diagnostic, warnings
