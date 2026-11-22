"""Transparent local BM25 retrieval; no embeddings or external search required."""
from collections import Counter
import json
import math
import hashlib
from pathlib import Path
import re
from .documents import active_chunks

DATA = Path(__file__).resolve().parents[1] / "data" / "knowledge.json"


def tokens(text):
    return re.findall(r"[a-z0-9]+", text.lower())


def retrieve_with_snapshot(query, limit=3):
    docs = json.loads(DATA.read_text(encoding="utf-8")) + active_chunks()
    fingerprint = hashlib.sha256(json.dumps(docs, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    bags = [Counter(tokens(d["title"] + " " + d["text"])) for d in docs]
    average = sum(sum(b.values()) for b in bags) / len(bags)
    results = []
    for doc, bag in zip(docs, bags):
        score = 0.0
        for term in set(tokens(query)):
            count = bag[term]
            frequency = sum(term in b for b in bags)
            weight = math.log(1 + (len(bags) - frequency + .5) / (frequency + .5))
            score += weight * count * 2.2 / (count + 1.2 * (.25 + .75 * sum(bag.values()) / average))
        if score > 0:
            results.append({**doc, "score": round(score, 4)})
    selected = []
    for doc in sorted(results, key=lambda d: (-d["score"], d["id"])):
        parent = doc.get("document_id", doc["id"])
        if sum(d.get("document_id", d["id"]) == parent for d in selected) < 2:
            selected.append(doc)
        if len(selected) == limit:
            break
    return {"documents": selected, "snapshot": {"sha256": fingerprint, "chunk_count": len(docs),
            "query": query, "method": "BM25", "version": "verifynet-bm25-v2", "limit": limit}}


def retrieve(query, limit=3):
    return retrieve_with_snapshot(query, limit)["documents"]
