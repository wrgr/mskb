
import argparse
from pathlib import Path

import pandas as pd

from .openalex_client import OpenAlexClient
from .utils import ensure_dir, invert_abstract_index, load_config, save_json, stable_hash


def _paper_row(work: dict, channel: str, query: str = "", seed_title: str = "", seed_doi: str = "") -> dict:
    oa_id = work.get("id", "")
    doi = work.get("doi") or ""
    title = work.get("title") or ""
    abstract = invert_abstract_index(work.get("abstract_inverted_index", {}))
    authorships = work.get("authorships", [])
    first_author = ""
    if authorships:
        first_author = ((authorships[0].get("author") or {}).get("display_name")) or ""
    venue = ((work.get("primary_location") or {}).get("source") or {}).get("display_name") or ""

    concepts = work.get("concepts", []) or []
    concept_names = ";".join(c.get("display_name", "") for c in concepts[:10])

    topics = work.get("topics", []) or []
    topic_names = ";".join(t.get("display_name", "") for t in topics[:5])

    return {
        "candidate_id": stable_hash(oa_id, doi or title),
        "openalex_id": oa_id,
        "doi": doi,
        "title": title,
        "year": work.get("publication_year"),
        "abstract": abstract,
        "venue": venue,
        "channel": channel,
        "query": query,
        "seed_title": seed_title,
        "seed_doi": seed_doi,
        "first_author": first_author,
        "cited_by_count": work.get("cited_by_count", 0),
        "concepts": concept_names,
        "topics": topic_names,
        "is_retrieved": True,
    }


def run(config_path: str) -> None:
    cfg = load_config(config_path)
    root = Path(config_path).resolve().parent
    outdir = root / cfg["output_dir"] / "raw"
    ensure_dir(outdir)

    client = OpenAlexClient(
        base_url=cfg["openalex_base_url"],
        email=cfg["email"],
        per_page=cfg["retrieval"]["per_page"],
        cache_dir=outdir / "openalex_cache",
    )

    rows = []
    citation_edges = []

    core_seeds = pd.read_csv(root / "seeds" / "core_seeds.csv")
    framing_seeds = pd.read_csv(root / "seeds" / "framing_seeds.csv")

    if cfg["retrieval"]["use_seed_channel"]:
        for _, seed in core_seeds.iterrows():
            doi = str(seed["doi"]) if pd.notna(seed["doi"]) else ""
            title = seed["title"]
            if not doi:
                continue
            work = client.get_work_by_doi(doi)
            if not work:
                continue
            rows.append(_paper_row(work, "seed_resolution", seed_doi=doi, seed_title=title))
            refs = [r.split("/")[-1] for r in work.get("referenced_works", []) if r]
            for ref in client.get_multiple_works(refs):
                rows.append(_paper_row(ref, "seed_reference", seed_doi=doi, seed_title=title))
                citation_edges.append({"source_openalex_id": work.get("id", ""), "target_openalex_id": ref.get("id", ""), "edge_type": "CITES"})
            for citing in client.get_citing_works(work.get("id", ""), max_pages=cfg["retrieval"]["max_pages_cited_by"]):
                rows.append(_paper_row(citing, "seed_cited_by", seed_doi=doi, seed_title=title))
                citation_edges.append({"source_openalex_id": citing.get("id", ""), "target_openalex_id": work.get("id", ""), "edge_type": "CITES"})

    if cfg["retrieval"]["use_lexical_channel"]:
        for query in cfg["queries"]["lexical"]:
            for work in client.search_works(query, max_results=cfg["retrieval"]["max_search_results_per_query"]):
                rows.append(_paper_row(work, "lexical", query=query))

    if cfg["retrieval"]["use_dataset_channel"]:
        for query in cfg["queries"]["dataset"]:
            for work in client.search_works(query, max_results=cfg["retrieval"]["max_search_results_per_query"]):
                rows.append(_paper_row(work, "dataset", query=query))

    candidates = pd.DataFrame(rows).drop_duplicates(subset=["openalex_id", "doi", "title", "channel"])
    candidates.to_csv(outdir / "candidate_papers.csv", index=False)

    pd.DataFrame(citation_edges).drop_duplicates().to_csv(outdir / "seed_citation_edges.csv", index=False)

    save_json({"n_candidates": int(len(candidates)), "n_seed_edges": int(len(citation_edges)), "n_core_seeds": int(len(core_seeds)), "n_framing_seeds": int(len(framing_seeds))}, outdir / "retrieval_stats.json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    run(args.config)
