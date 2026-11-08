"""Optional Claude pass: turn the day's raw complaints into named, de-duplicated
problems, re-using names from earlier days so trends line up.

Runs only when ANTHROPIC_API_KEY is set. Any failure falls back to the
keyword clusters from analyze.py.
"""
import json
import os

SCHEMA = {
    "type": "object",
    "properties": {
        "problems": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "kebab-case id; reuse a known key when it is the same problem"},
                    "title": {"type": "string"},
                    "summary": {"type": "string"},
                    "who": {"type": "string", "description": "who has this problem"},
                    "why_unmet": {"type": "string", "description": "why existing tools fail them, from the evidence"},
                    "solution_idea": {"type": "string"},
                    "mvp_features": {"type": "array", "items": {"type": "string"},
                                     "description": "the 3 must-have features of a bare-minimum product, most important first"},
                    "search_keyword": {"type": "string",
                                       "description": "what a buyer would type into Google, e.g. 'tenant maintenance request software'"},
                    "costs": {"type": "string", "enum": ["time", "money", "both", "unclear"]},
                    "saas_fit": {"type": "string", "enum": ["high", "medium", "low"]},
                    "theme": {"type": "string"},
                    "item_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["key", "title", "summary", "who", "why_unmet", "solution_idea", "mvp_features", "search_keyword",
                             "costs", "saas_fit", "theme", "item_ids"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["problems"],
    "additionalProperties": False,
}

SYSTEM = """You analyse public complaints, questions, low-star reviews, upvoted feature requests and job posts
collected today. Your reader is a solo developer looking for real, currently unmet problems that many people share.

Group the items into distinct problems (aim for 8-25). A problem needs evidence from at least two items unless a
single item shows unusually strong demand (many upvotes, explicit willingness to pay). Ignore spam, self-promotion,
and posts that merely announce a product.

Strong evidence: the same complaint repeated by different people and sources; emotional language; explicit wishes
("I wish it could...", "is there a tool..."); paying customers of an existing product saying it is missing something,
hard to use, unreliable or too expensive for what it does (an opening for a leaner alternative); companies paying
people to do repetitive work. Say whether the problem costs people time, money, or both: problems that cost time or
money are the ones people pay to solve.

Rate saas_fit: high = software could clearly solve it and people already pay for adjacent tools; medium = software
helps but is not the whole answer; low = structural, physical, regulatory or interpersonal. Keep low-fit problems
when many people share them; the reader wants to hear about them too.

When a problem matches one in the list of known problems, reuse its exact key and title so it can be tracked over
time. Otherwise invent a short, specific kebab-case key. Use only item ids that appear in the input. Write plainly
and concretely; no hype."""


def refine(items, known, cfg):
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None, "skipped (no ANTHROPIC_API_KEY)"
    try:
        import anthropic
    except ImportError:
        return None, "anthropic package not installed"

    top = sorted(items, key=lambda x: -x["pain_score"])[: cfg.get("max_items_sent", 180)]
    payload = [
        {
            "id": it["id"], "source": it["source"], "where": it["channel"], "type": it["kind_label"],
            "engagement": it["engagement"], "title": it["title"], "text": it["text"][:700],
            **({"stars": it["rating"]} if it.get("rating") else {}),
            **({"complaint_types": it["complaints"]} if it.get("complaints") else {}),
        }
        for it in top
    ]
    known_list = [{"key": k, "title": v["title"]} for k, v in list(known.items())[:300]]
    user = (
        "Known problems from earlier days (reuse keys when it's the same problem):\n"
        + json.dumps(known_list, ensure_ascii=False)
        + "\n\nToday's items:\n"
        + json.dumps(payload, ensure_ascii=False)
    )
    client = anthropic.Anthropic()
    kwargs = dict(
        model=cfg.get("model", "claude-opus-5-5"),
        max_tokens=16000,
        system=SYSTEM,
        messages=[{"role": "user", "content": user}],
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
    )
    try:
        # Server-side fallback re-runs the request on another model if this one declines.
        resp = client.beta.messages.create(betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs)
    except anthropic.BadRequestError:
        resp = client.messages.create(**kwargs)
    except anthropic.APIError as e:
        return None, f"API error: {e}"
    if resp.stop_reason == "refusal":
        return None, "model declined"
    if resp.stop_reason == "max_tokens":
        return None, "output truncated"
    text = next((b.text for b in resp.content if b.type == "text"), "")
    data = json.loads(text)
    valid = {it["id"]: it for it in items}
    problems = []
    for p in data.get("problems", []):
        ids = [i for i in p["item_ids"] if i in valid]
        if not ids:
            continue
        p["item_ids"] = ids
        p["sources"] = sorted({valid[i]["source"] for i in ids})
        p["score"] = round(sum(valid[i]["pain_score"] for i in ids), 2)
        p["method"] = "ai"
        problems.append(p)
    problems.sort(key=lambda p: -p["score"])
    return problems, f"ok ({resp.model})"
