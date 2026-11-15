"""Generate a synthetic raw-items fixture (for tests and local UI previews)."""
import json
import random
import sys
import time

# (source, channel, kind, niche_hint, implied, title, text)
TEMPLATES = [
    ("reddit", "r/Dentistry", "discussion", "Dental practices", None, "How do you all handle after-hours emergency calls?",
     "We're a 3 dentist practice and the answering service is a nightmare. Is there any software that routes calls and logs them into the patient chart? Tried a bunch of tools and nothing fits."),
    ("reddit", "r/landscaping", "discussion", "Landscaping & lawn care", None, "Scheduling crews is killing me",
     "I run a landscaping company with 4 crews. Every week I spend hours manually moving jobs around a whiteboard and texting guys. There has to be a better way."),
    ("reddit", "r/Landlord", "discussion", "Landlords & property managers", None, "Tenant maintenance requests are a nightmare",
     "Texts, emails, calls... I track maintenance requests in a spreadsheet and things fall through the cracks. Is there an app for small landlords that isn't overpriced?"),
    ("reddit", "r/HVAC", "discussion", "HVAC, plumbing & electrical", None, "Alternatives to ServiceTitan for a small shop?",
     "ServiceTitan is too expensive for a 5 tech shop and way too complicated. We just need dispatch and invoicing."),
    ("reddit", "r/Lawyertalk", "discussion", "Lawyers & paralegals", None, "Trust accounting for solos",
     "We keep track of client retainers in a giant Google Sheet and it's getting out of hand. I'd happily pay for something that did trust accounting for a solo attorney."),
    ("freelance", "Freelancer · budget 250–750 USD", "gig", None, "gig", "Need automation for order intake",
     "We are a wholesale bakery. Our staff manually copy orders from emails into an Excel sheet every day. I need someone to build a system that reads the emails and fills the spreadsheet."),
    ("forums", "Shopify Community", "discussion", "E-commerce sellers", None, "Is there an app that splits orders by supplier?",
     "Looking for an app that automatically splits an order into separate purchase orders per supplier. I do this manually every day and it takes hours."),
    ("hackernews", "Ask HN · What problem do you wish was solved?", "discussion", None, "idea_thread", "",
     "Scheduling staff shifts for a small clinic. My wife spends every Sunday night copying availability from texts into a spreadsheet to track who can work. Nothing on the market fits a practice with 12 nurses."),
    ("stackexchange", "Software Recommendations", "discussion", None, "ask_tool", "Software to schedule cleaning staff shifts with SMS reminders",
     "We are a small cleaning business and use a whiteboard. I need something that handles shift scheduling and texts the staff."),
    ("bluesky", "Bluesky", "discussion", None, None, "",
     "I wish there was an app that let me share a grocery list with my elderly mom's caregivers and see what has been bought already"),
    # ---- things that must be filtered out
    ("reddit", "r/Landlord", "discussion", "Landlords & property managers", None, "I built an app for landlords",
     "Hey all, I built a tool that tracks rent. Would you use this? Is there a tool like it already? Feedback on my landing page welcome."),
    ("reddit", "r/productivity", "discussion", None, None, "Yahoo mail won't load after the update",
     "It keeps crashing after the latest update. Is there a way to roll it back? How do I fix this, it wastes hours of my day."),
    ("reddit", "r/personalfinance", "discussion", "Personal finance", None, "Rent keeps going up",
     "Housing in my city is insane and my landlord won't fix anything. Frustrating situation, no idea what to do."),
    ("hackernews", "Hacker News · Big tech", "discussion", None, None, "",
     "The alternative to a toilet-flushing app is a flushing button, which is obviously the better design for everybody involved here."),
]


def make(n=60, seed=1, now=None):
    rnd = random.Random(seed)
    now = now or time.time()
    out = []
    for i in range(n):
        s, ch, k, niche, implied, t, x = TEMPLATES[i % len(TEMPLATES)] if i < len(TEMPLATES) else rnd.choice(TEMPLATES)
        it = {"id": f"{s}:fx{seed}-{i}", "source": s, "channel": ch, "kind": k,
              "url": f"https://example.com/{seed}/{i}", "title": t, "text": x,
              "created": int(now - rnd.randint(0, 600000)), "engagement": rnd.randint(0, 300)}
        if niche:
            it["niche_hint"] = niche
        if implied:
            it["implied"] = implied
        out.append(it)
    return out


if __name__ == "__main__":
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    json.dump(make(seed=seed), sys.stdout, indent=1)
