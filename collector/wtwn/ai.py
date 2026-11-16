"""Optional Claude pass: turn the week's leads into named, de-duplicated problems,
re-using names from earlier weeks so trends line up.

Runs only when ANTHROPIC_API_KEY is set. Any failure falls back to the
niche-and-theme grouping from analyze.py.
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
                    "niche": {"type": "string", "description": "who has the problem; reuse the niche label from the leads when it fits"},
                    "theme": {"type": "string", "description": "problem area; reuse a theme label from the leads when it fits"},
                    "item_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["key", "title", "summary", "who", "why_unmet", "solution_idea", "mvp_features", "search_keyword",
                             "costs", "saas_fit", "niche", "theme", "item_ids"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["problems"],
    "additionalProperties": False,
}

SYSTEM = """You are given this week's leads: public posts in which someone states a need that isn't being met.
They come from communities of practitioners (dentists, landlords, contractors, bookkeepers, shop owners and so on),
merchant and IT forums, businesses paying freelancers for custom tools, and "what problem needs solving" threads.
Each has the niche it came from and the sentence where the person states the need. Your reader is a solo developer
looking for a real, specific, currently unmet problem worth building a business around.

Group the leads into distinct problems (aim for 10-30). Work at the level of a niche and a job to be done:
"Solo law firms have no affordable way to do trust accounting" is the right altitude. "App X crashes after the
update", "feature Y is missing from product Z" and other complaints about one product are too granular; fold them
into the underlying need or leave them out. Prefer problems where several different people in the same niche
describe the same need, where someone says they would pay, where a business is already paying a freelancer or a
person to do it, or where people say they tried the existing tools and none fit. A problem needs at least two
leads unless one lead shows unusually strong demand. Leave out self-promotion, idea-validation posts by founders,
jokes, and anything you cannot tie to a concrete need.

For each problem say who has it (the niche, as specifically as the evidence allows), why existing tools fail them
according to the evidence, whether it costs them time, money or both, and what a bare-minimum product would be.
Do not invent facts that are not in the leads.

Rate saas_fit: high = software could clearly solve it and these people already pay for adjacent tools; medium =
software helps but is not the whole answer; low = structural, physical, regulatory or interpersonal. Keep low-fit
problems when many people share them; the reader wants to hear about them too.

When a problem matches one in the list of known problems, reuse its exact key and title so it can be tracked over
time. Otherwise invent a short, specific kebab-case key. Use only lead ids that appear in the input. Write plainly
and concretely; no hype."""


def refine(items, known, cfg):
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None, "skipped (no ANTHROPIC_API_KEY)"
    try:
        import anthropic
    except ImportError:
        return None, "anthropic package not installed"

    top = sorted(items, key=lambda x: -x.get("opp", x["pain_score"]))[: cfg.get("max_items_sent", 220)]
    payload = [
        {
            "id": it["id"], "niche": it["niche"], "theme": it["themes"][0], "where": it["channel"],
            "signals": it.get("signal_labels", []), "engagement": it["engagement"],
            "need": it["need"], "title": it["title"], "text": it["text"][:600],
        }
        for it in top
    ]
    known_list = [{"key": k, "title": v["title"]} for k, v in list(known.items())[:300]]
    user = (
        "Known problems from earlier weeks (reuse keys when it's the same problem):\n"
        + json.dumps(known_list, ensure_ascii=False)
        + "\n\nThis week's leads:\n"
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
