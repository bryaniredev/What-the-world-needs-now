"""Generate a synthetic raw-items fixture (for tests and local UI previews)."""
import json
import random
import sys
import time

TEMPLATES = [
    ("reddit", "r/smallbusiness", "discussion", "Is there a tool to stop chasing late invoices?",
     "I spend hours every week manually emailing clients about overdue invoices. I'd pay for something that automates follow up."),
    ("reddit", "r/landlord", "discussion", "Tenant maintenance requests are a nightmare",
     "Texts, emails, calls... I track maintenance requests in a spreadsheet. Is there an app for small landlords that isn't overpriced?"),
    ("hackernews", "Ask HN", "discussion", "Ask HN: How do you keep track of SOC 2 evidence?",
     "We copy-paste screenshots into a Google Drive folder. Why is there no good way to collect compliance evidence automatically?"),
    ("app_store", "QuickBooks", "review", "Bank sync broken again",
     "Bank feeds stopped working and I had to reconcile everything manually. Customer support is terrible. Too expensive for this."),
    ("shopify_apps", "klaviyo-email-marketing", "review", "Price increase is insane",
     "They doubled the price with no warning. Looking for an alternative to this for a small store."),
    ("github", "someorg/somerepo", "feature_request", "Feature request: export reports to CSV",
     "Please add CSV export for reports. Right now I copy and paste tables into Excel by hand."),
    ("jobs", "Remotive · Acme", "job", "Data entry and invoice reconciliation assistant",
     "You will manually update records in our spreadsheet, reconcile invoices against bank statements, and compile reports weekly."),
    ("stackexchange", "softwarerecs", "discussion", "Looking for software to schedule cleaning staff shifts",
     "Is there a tool that handles shift scheduling for a small cleaning business with SMS reminders? We use a whiteboard."),
    ("reddit", "r/Teachers", "discussion", "Grading takes forever",
     "I waste hours every weekend on grading. I wish there was a way to batch feedback on essays without copying comments by hand."),
    ("reddit", "r/personalfinance", "discussion", "Rent is crazy and my landlord won't fix anything",
     "Housing in my city is insane. Frustrating situation, no idea what to do."),
    ("jobs", "The Muse · Metro Motors", "job", "Service Manager",
     "Responsibilities: Schedule service appointments. Ensure compliance with health and safety regulations. "
     "Process warranty claims and track vehicle repair status."),
    ("app_store", "Notion", "review", "Good but",
     "Pretty good app overall, I like it."),
    ("app_store", "Notion", "review", "Almost there",
     "Nice app but it doesn't support offline mode and the price increase made it too expensive."),
    ("reddit", "r/Contractor", "discussion", "How do you all handle job costing?",
     "We track job costs in a giant spreadsheet and it takes forever. Is there a tool that isn't overpriced?"),
]


def make(n=60, seed=1, now=None):
    rnd = random.Random(seed)
    now = now or time.time()
    out = []
    for i in range(n):
        s, ch, k, t, x = rnd.choice(TEMPLATES)
        out.append({
            "id": f"{s}:fx{seed}-{i}", "source": s, "channel": ch, "kind": k,
            "url": "https://example.com/" + str(i), "title": t, "text": x,
            "created": int(now - rnd.randint(0, 86000)), "engagement": rnd.randint(0, 300),
            "rating": (3 if t in ("Good but", "Almost there") else 1) if k == "review" else None,
        })
        if s == "jobs" and ch.startswith("The Muse"):
            out[-1]["manual_hits"] = 0
            out[-1]["industry"] = "car dealership"
    return out


if __name__ == "__main__":
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    json.dump(make(seed=seed), sys.stdout, indent=1)
