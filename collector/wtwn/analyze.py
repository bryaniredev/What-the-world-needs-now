"""Heuristic analysis: pain score, themes, SaaS fit, keywords and clusters.

Works with no API key. When ANTHROPIC_API_KEY is set, ai.py refines the
clusters into named problems; these heuristics still supply the trends.
"""
import math
import re
from collections import Counter, defaultdict

# (regex, weight, label). Phrases people use when a need is unmet.
SIGNALS = [
    (r"\bi(?:'d| would) (?:happily |gladly )?pay\b", 5, "would pay"),
    (r"\bshut up and take my money\b", 5, "would pay"),
    (r"\bi wish (?:there (?:was|were)|someone would|i could|it (?:had|would))\b", 4, "wishes it existed"),
    (r"\bis there (?:a|an|any) (?:tool|app|software|service|way|plugin|extension|saas)\b", 4, "asking for a tool"),
    (r"\b(?:does anyone|anyone) (?:know|recommend|use) (?:a|an|of a|any)\b", 2, "asking for a tool"),
    (r"\blooking for (?:a |an )?(?:tool|app|software|service|solution|platform)\b", 3, "asking for a tool"),
    (r"\bwhy is there no\b|\bwhy (?:isn't|is not) there\b|\bstill no (?:good )?way\b|\bno good (?:way|tool|solution)\b", 4, "nothing exists"),
    (r"\bhow do (?:you|people|i) (?:even )?(?:handle|manage|deal with|keep track)\b", 2, "workflow question"),
    (r"\bmanual(?:ly)?\b|\bby hand\b|\bcopy[- ](?:and[- ])?paste\b", 2, "manual work"),
    (r"\bspreadsheet|excel|google sheets?\b", 1, "spreadsheet workaround"),
    (r"\bworkaround|duct tape|hack(?:ed|y) together|cobbled\b", 2, "workaround"),
    (r"\bwaste[sd]? (?:hours|so much time|time)|takes (?:forever|hours)|time[- ]consuming|tedious\b", 3, "time sink"),
    (r"\bfrustrat\w*|annoying|nightmare|hate|painful|pain in the|drives me (?:crazy|nuts)|fed up\b", 1, "frustration"),
    (r"\btoo expensive|overpriced|price (?:hike|increase)|can't afford|costs? (?:a fortune|too much)\b", 3, "too expensive"),
    (r"\balternative to\b|\bswitch(?:ing|ed)? (?:away )?from\b|\bcancel(?:led|ing)? (?:my )?subscription\b", 3, "looking to switch"),
    (r"\bmissing (?:a )?(?:feature|basic)|doesn't (?:support|have|allow|let)|does not (?:support|have|allow)|no option to|can't even\b", 2, "missing feature"),
    (r"\bfeature request\b|\bplease add\b|\bwould love (?:to see|if)\b", 2, "feature request"),
    (r"\bbuggy|keeps crashing|crash(?:es|ed)|broken|stopped working|unusable\b", 1, "unreliable"),
    (r"\bcustomer (?:service|support) (?:is|was) (?:terrible|awful|non-?existent)|no response from support\b", 2, "bad support"),
]
_SIG = [(re.compile(p, re.I), w, l) for p, w, l in SIGNALS]

# theme -> keywords. Order matters only for display.
THEMES = {
    "Invoicing & payments": ["invoice", "invoicing", "payment", "billing", "stripe", "paypal", "chargeback", "payout", "late pay", "accounts receivable"],
    "Accounting & bookkeeping": ["bookkeep", "accounting", "quickbooks", "xero", "reconcil", "ledger", "tax", "receipt", "expense", "cpa", "1099"],
    "Scheduling & booking": ["schedul", "booking", "appointment", "calendar", "calendly", "no-show", "reservation", "shift"],
    "Sales & CRM": ["crm", "lead", "pipeline", "prospect", "salesforce", "hubspot", "cold email", "outreach", "follow up", "follow-up", "quote"],
    "Marketing & email": ["marketing", "newsletter", "email list", "mailchimp", "klaviyo", "campaign", "seo", "ads", "ppc", "landing page"],
    "Social & content": ["social media", "instagram", "tiktok", "youtube", "content calendar", "linkedin", "posting", "creator"],
    "E-commerce & inventory": ["inventory", "shopify", "sku", "etsy", "amazon seller", "woocommerce", "product listing", "stock", "dropship", "storefront"],
    "Shipping & logistics": ["shipping", "fulfil", "shipment", "tracking number", "freight", "warehouse", "delivery", "dispatch", "truck", "returns"],
    "Customer support": ["customer support", "helpdesk", "ticket", "live chat", "zendesk", "refund", "complaint", "customer service"],
    "HR, hiring & payroll": ["hiring", "recruit", "applicant", "resume", "payroll", "onboarding", "employee", "timesheet", "pto", "interview"],
    "Projects & tasks": ["project management", "task", "asana", "trello", "jira", "monday.com", "todo", "to-do", "kanban", "deadline"],
    "Docs, notes & knowledge": ["notion", "documentation", "wiki", "knowledge base", "notes", "evernote", "sop", "confluence"],
    "Data, reporting & spreadsheets": ["spreadsheet", "excel", "google sheet", "report", "dashboard", "analytics", "csv", "data entry", "pivot"],
    "Integrations & automation": ["integrat", "zapier", "automat", "api", "webhook", "sync", "workflow", "make.com", "n8n"],
    "Developer tooling": ["github", "deploy", "ci/cd", "kubernetes", "docker", "debug", "logging", "monitoring", "sdk", "codebase", "pull request"],
    "Security, privacy & compliance": ["security", "privacy", "gdpr", "hipaa", "soc 2", "soc2", "compliance", "password", "2fa", "audit"],
    "Meetings & communication": ["meeting", "zoom", "slack", "teams", "notification", "email inbox", "inbox", "transcri"],
    "Property & real estate": ["tenant", "landlord", "rent", "property", "lease", "realtor", "listing", "hoa", "maintenance request"],
    "Healthcare & clinics": ["patient", "clinic", "ehr", "emr", "insurance claim", "prior auth", "nurse", "doctor", "dental", "pharmacy", "medical billing"],
    "Education & teaching": ["teacher", "student", "grading", "classroom", "lesson plan", "school", "tutor", "course"],
    "Legal & contracts": ["contract", "legal", "lawyer", "attorney", "nda", "e-sign", "esign", "court", "paralegal"],
    "Field service & trades": ["contractor", "plumb", "electrician", "hvac", "job site", "estimate", "landscap", "cleaning business", "technician"],
    "Restaurants & hospitality": ["restaurant", "menu", "kitchen", "pos", "point of sale", "hotel", "catering", "food cost"],
    "Personal finance & life admin": ["budget", "savings", "debt", "subscriptions", "bill", "credit card", "personal finance", "household"],
    "Pricing & cost complaints": ["too expensive", "price increase", "pricing", "overpriced", "subscription fee", "per seat"],
    "Reliability & quality": ["bug", "crash", "slow", "broken", "outage", "downtime", "glitch", "update ruined"],
}

# Words suggesting software can help vs. structural/physical problems.
SAAS_POSITIVE = [
    "tool", "app", "software", "saas", "dashboard", "automate", "automation", "integrat", "sync", "track",
    "spreadsheet", "excel", "manually", "workflow", "report", "export", "import", "api", "plugin", "extension",
    "template", "crm", "invoice", "schedul", "notification", "remind", "database", "portal", "online", "platform",
]
SAAS_NEGATIVE = [
    "government", "law ", "legislation", "landlord won't", "my boss", "coworker", "salary", "wage", "rent is",
    "housing", "healthcare cost", "insurance denied", "supply chain shortage", "tariff", "union", "physical", "injury",
]

STOP = set("""
a about above after again against all am an and any are aren't as at be because been before being below between
both but by can can't cannot could couldn't did didn't do does doesn't doing don't down during each few for from
further had hadn't has hasn't have haven't having he her here hers herself him himself his how i i'm i've i'd if in
into is isn't it it's its itself just let's me more most my myself no nor not now of off on once only or other our
ours ourselves out over own same she should so some such than that that's the their theirs them themselves then
there there's these they they're this those through to too under until up very was wasn't we we're were weren't
what what's when where which while who whom why with won't would wouldn't you you're your yours yourself also get
got like really one use using used want need way thing things know think make go going even much many lot still
every week weeks month months year years today daily anyone someone something anything people also new time day work able just https http www com
""".split())

KIND_LABEL = {"discussion": "Discussion", "review": "1-2★ review", "feature_request": "Feature request", "job": "Job post"}


def _kw_rx(kws):
    """Short keywords must match whole words ("pos" != "possible"); longer ones match word prefixes."""
    parts = [re.escape(k.strip()) + (r"\b" if len(k.strip()) <= 4 else "") for k in kws]
    return [re.compile(r"\b" + p, re.I) for p in parts]


_THEME_RX = {t: _kw_rx(k) for t, k in THEMES.items()}
_POS_RX = _kw_rx(SAAS_POSITIVE)
_NEG_RX = _kw_rx(SAAS_NEGATIVE)


def _norm(text):
    return re.sub(r"[^a-z0-9'\- ]+", " ", text.lower())


def signals_for(text):
    hits, score = [], 0
    for rx, w, label in _SIG:
        if rx.search(text):
            if label not in hits:
                hits.append(label)
            score += w
    return score, hits


def themes_for(text):
    scored = []
    for theme, rxs in _THEME_RX.items():
        n = sum(1 for rx in rxs if rx.search(text))
        if n:
            scored.append((n, theme))
    scored.sort(reverse=True)
    return [th for _, th in scored[:3]] or ["Other"]


def saas_fit_for(text, kind):
    pos = sum(1 for rx in _POS_RX if rx.search(text))
    neg = sum(1 for rx in _NEG_RX if rx.search(text))
    if kind in ("review", "feature_request"):
        pos += 2  # complaints about software are by definition software-shaped
    if kind == "job":
        pos += 1
    v = pos - 2 * neg
    return "high" if v >= 3 else "medium" if v >= 1 else "low"


def keywords_for(text, n=8):
    words = [w.strip("'-") for w in _norm(text).split()]
    words = [w for w in words if len(w) > 2 and w not in STOP and not w.isdigit()]
    grams = Counter()
    for a, b in zip(words, words[1:]):
        grams[f"{a} {b}"] += 1
    for w in words:
        grams[w] += 0.25
    return [g for g, _ in grams.most_common(n)]


def score_item(it):
    text = f"{it['title']} {it['text']}"
    s, sig = signals_for(text)
    if it["kind"] == "review":
        r = it.get("rating") or 5
        s += 3 if r <= 1 else 2 if r == 2 else 1
    elif it["kind"] == "feature_request":
        s += 3
    elif it["kind"] == "job":
        s += 3
    pain = s + math.log1p(max(0, it.get("engagement", 0))) * 1.2
    it["signals"] = sig
    it["pain_score"] = round(pain, 2)
    it["themes"] = themes_for(text)
    it["saas_fit"] = saas_fit_for(text, it["kind"])
    it["keywords"] = keywords_for(text)
    it["kind_label"] = KIND_LABEL.get(it["kind"], it["kind"])
    it["costs"] = costs_for(sig)
    if it["kind"] in ("review", "feature_request"):
        it["complaints"] = complaint_types_for(text)
    uses = spreadsheet_uses_for(text)
    if uses:
        it["spreadsheet_uses"] = uses
    if it["kind"] == "job":
        it["duties"] = duties_for(it["text"])
    return it


def keep_item(it, min_score):
    """Is this a pain point worth showing? Engagement alone is not pain."""
    if it["kind"] == "job":
        return it.get("manual_hits", 2) >= 2  # other job posts only feed the duties table
    if it["kind"] == "review" and (it.get("rating") or 1) >= 3:
        return bool(GAP_TYPES & set(it.get("complaints", [])))  # 3-star: only when it names a gap
    return it["pain_score"] >= min_score and (bool(it["signals"]) or it["kind"] != "discussion")


def _short(t, n=90):
    t = re.sub(r"\s+", " ", t or "").strip()
    return t if len(t) <= n else t[: n - 1].rsplit(" ", 1)[0] + "\u2026"


def _cluster_summary(gram, members, items):
    others = [t for t in dict.fromkeys(_short(items[i]["title"], 70) for i in members[1:]) if t
              and t != _short(items[members[0]]["title"], 70)][:2]
    base = f"{len(members)} posts mention \u201c{gram}\u201d."
    return base + (" Also: " + "; ".join(others) if others else "")


def heuristic_clusters(items, max_clusters=25):
    """Group items that share a distinctive bigram. Cheap and stable across days."""
    gram_items = defaultdict(set)
    for i, it in enumerate(items):
        for g in it["keywords"]:
            if " " in g:
                gram_items[g].add(i)
    candidates = sorted(
        ((g, ids) for g, ids in gram_items.items() if len(ids) >= 2),
        key=lambda x: (-sum(items[i]["pain_score"] for i in x[1]), x[0]),
    )
    used, clusters = set(), []
    for g, ids in candidates:
        fresh = ids - used
        if len(fresh) < 2:
            continue
        used |= fresh
        members = sorted(fresh, key=lambda i: -items[i]["pain_score"])
        th = Counter(t for i in members for t in items[i]["themes"]).most_common(1)[0][0]
        fits = Counter(items[i]["saas_fit"] for i in members).most_common(1)[0][0]
        clusters.append({
            "key": re.sub(r"[^a-z0-9]+", "-", g).strip("-"),
            "title": _short(items[members[0]]["title"] or items[members[0]]["text"]),
            "search_keyword": f"{g} software",
            "summary": _cluster_summary(g, members, items),
            "theme": th,
            "saas_fit": fits,
            "item_ids": [items[i]["id"] for i in members],
            "sources": sorted({items[i]["source"] for i in members}),
            "score": round(sum(items[i]["pain_score"] for i in members), 2),
            "method": "keyword",
        })
        if len(clusters) >= max_clusters:
            break
    return clusters


# --------------------------------------------------------- incumbent gaps
# What paying customers say is wrong with a product (1-3 star reviews, feature requests).
COMPLAINTS = {
    "missing_feature": r"\bmissing|doesn't (?:support|have|allow|let)|does not (?:support|have|allow|let)|no (?:way|option) to|\black(?:s|ing)\b|i wish (?:it|they|there)|please add|would love (?:to see|if)|feature request|can't even|cannot even|needs? (?:a|an|the) option",
    "hard_to_use": r"\bconfusing|hard to (?:use|figure|understand|navigate|set ?up|find)|complicated|not intuitive|unintuitive|clunky|learning curve|user[- ]unfriendly|too many (?:steps|clicks)",
    "too_expensive": r"\bexpensive|overpriced|price (?:increase|hike)|pricey|hidden fees?|not worth (?:the|it)|charg(?:ed|es|ing) (?:me|us)|raised (?:the|their) price|paywall",
    "unreliable": r"\bbug(?:gy|s)?\b|crash|broken|stopped working|glitch|doesn't work|does not work|not working|lost (?:all )?(?:my |our )?data|keeps (?:failing|logging)",
    "integrations": r"\bintegrat|\bsync|connect(?:ion|or)?s?\b|\bapi\b|zapier|\bexport|\bimport",
    "bad_support": r"\bsupport (?:is|was|team)|customer service|no response|never (?:replied|responded|answered|heard back)|ticket",
    "slow": r"\bslow|\blag(?:gy)?\b|takes forever|loading",
}
COMPLAINT_LABEL = {
    "missing_feature": "Missing feature", "hard_to_use": "Hard to use", "too_expensive": "Too expensive",
    "unreliable": "Unreliable", "integrations": "Integrations", "bad_support": "Bad support", "slow": "Slow",
}
GAP_TYPES = {"missing_feature", "hard_to_use", "too_expensive", "integrations"}
_COMPLAINT_RX = {k: re.compile(v, re.I) for k, v in COMPLAINTS.items()}


def complaint_types_for(text):
    return [k for k, rx in _COMPLAINT_RX.items() if rx.search(text)]


def costs_for(signals):
    """Problems are grounded in time or money spent."""
    out = []
    if set(signals) & {"time sink", "manual work", "workaround", "spreadsheet workaround"}:
        out.append("time")
    if set(signals) & {"too expensive", "would pay", "looking to switch"}:
        out.append("money")
    return out


# ------------------------------------------------- Job Search Method (duties)
_DUTY_VERBS = (r"manag(?:e|es|ing)|maintain(?:s|ing)?|track(?:s|ing)?|coordinat(?:e|es|ing)|schedul(?:e|es|ing)|"
               r"process(?:es|ing)?|prepar(?:e|es|ing)|reconcil(?:e|es|ing)|updat(?:e|es|ing)|monitor(?:s|ing)?|"
               r"compil(?:e|es|ing)|enter(?:s|ing)?|handl(?:e|es|ing)|organiz(?:e|es|ing)|overse(?:e|es|eing)|"
               r"administer(?:s|ing)?|generat(?:e|es|ing)|verif(?:y|ies|ying)|audit(?:s|ing)?|invoic(?:e|es|ing)|"
               r"dispatch(?:es|ing)?|record(?:s|ing)?|log(?:s|ging)?|follow(?:s|ing)? up on|respond(?:s|ing)? to")
_STOP_AT = r"(?=[,.;:()\n•\-–—]|\s+(?:and|or|to|with|for|in|on|across|using|as|by|within|from|that|while|including|per|via|at|against|into|between|throughout|under|over|before|after|when|where|according|so|such)\b|$)"
_DUTY_RX = re.compile(r"\b(?:" + _DUTY_VERBS + r")\s+((?:[a-z&/'-]+\s+){0,4}?[a-z&/'-]+)" + _STOP_AT, re.I)
_COMPLIANCE_RX = re.compile(r"\bensur(?:e|es|ing) compliance with\s+((?:[a-z&/'-]+\s+){0,5}?[a-z&/'-]+)" + _STOP_AT.replace(r"and|or|", r"or|"), re.I)
_LEAD = {"the", "all", "our", "a", "an", "any", "daily", "weekly", "monthly", "various", "multiple", "new", "existing",
         "accurate", "timely", "company", "company's", "client", "your", "their", "its", "day-to-day", "high", "large",
         "complex", "internal", "external", "relevant", "appropriate", "necessary", "key", "other", "incoming", "outgoing"}
_GENERIC = {"tasks", "duties", "projects", "project", "team", "teams", "work", "others", "them", "it", "time", "issues",
            "relationships", "needs", "requests", "information", "process", "processes", "operations", "activities",
            "responsibilities", "people", "staff", "business", "day", "role", "things", "efforts", "this", "these",
            "customers", "clients", "customer", "client", "employees", "members", "partners", "stakeholders", "leadership",
            "records", "reports", "data", "documents", "documentation", "files", "emails", "calls", "paperwork", "details",
            "correspondence", "inquiries", "accounts", "systems", "status", "changes", "updates", "deadlines", "schedules"}


def _clean_phrase(p):
    words = [w for w in re.sub(r"[^a-z&/' -]", " ", p.lower()).split()]
    while words and words[0] in _LEAD:
        words.pop(0)
    while words and (words[-1] in _LEAD or words[-1] in STOP):
        words.pop()
    if not words or len(words) > 4 or all(w in _GENERIC or w in STOP for w in words):
        return None
    if len(words) == 1 and (words[0] in _GENERIC or len(words[0]) < 4):
        return None
    return " ".join(words)


def duties_for(text):
    found = []
    for m in _COMPLIANCE_RX.finditer(text):
        ph = _clean_phrase(m.group(1))
        if ph:
            found.append(re.sub(r"\s+(?:regulations|requirements|standards|laws|rules|policies)$", "", ph) + " compliance")
    for m in _DUTY_RX.finditer(text):
        ph = _clean_phrase(m.group(1))
        if ph and ph not in found and not ph.endswith("compliance"):
            found.append(ph)
    return found[:12]


def software_keyword(phrase):
    return phrase if phrase.endswith(("software", "system", "tool")) else f"{phrase} management software"


# ------------------------------------------- What-They're-Using-Excel-For Method
_SHEET = r"(?:spread ?sheets?|excel(?: sheets?| files?)?|google sheets?|a (?:shared |giant |massive |huge )?sheet)"
_SHEET_VERB = (r"(?:track(?:ing)?|manag(?:e|ing)|keep(?:ing)? track of|log(?:ging)?|plan(?:ning)?|calculat(?:e|ing)|"
               r"organiz(?:e|ing)|record(?:ing)?|monitor(?:ing)?|schedul(?:e|ing)|budget(?:ing)?|run(?:ning)?|store|storing)")
_SHEET_RX = [
    re.compile(_SHEET + r"\s+(?:to|for)\s+(?:" + _SHEET_VERB + r"\s+)?((?:[a-z'/-]+\s+){0,3}?[a-z'/-]+)" + _STOP_AT, re.I),
    re.compile(r"\b" + _SHEET_VERB + r"\s+((?:[a-z'/-]+\s+){0,3}?[a-z'/-]+)\s+(?:in|on|with|using|via)\s+(?:a |an |our |my |the |one )?(?:big |giant |shared |massive |huge |single )?" + _SHEET, re.I),
]


def spreadsheet_uses_for(text):
    out = []
    for rx in _SHEET_RX:
        for m in rx.finditer(text):
            ph = _clean_phrase(m.group(1))
            if ph and ph not in out and ph not in ("everything", "stuff", "data"):
                out.append(ph)
    return out[:5]
