"""Turns raw posts into leads: keeps only posts that state an unmet need, pulls out
the sentence that states it, and tags each with a niche, a theme and a SaaS fit.

Works with no API key. With ANTHROPIC_API_KEY set, ai.py turns the kept items into
named problems; everything here still supplies the filtering and the trends.
"""
import math
import re
from collections import Counter, defaultdict

TOOL = (r"(?:tool|tools|app|apps|software|service|platform|plugin|plug-in|extension|system|solution|"
        r"product|website|crm|saas|add-?on|integration|template|script|bot|database|tracker|portal)")
GAP = r"[^.?!\n]{0,60}?"

# (key, label, weight, pattern). A post needs STRONG weight >= 3 to be kept.
STRONG = [
    ("pay", "would pay for it", 5,
     r"\b(?:i|we)(?:'d| would|'ll| will) (?:happily |gladly |literally |definitely |totally |absolutely |honestly )?pay\b"
     r"|\b(?:willing|happy|glad) to pay\b|\btake my money\b|\bwould pay (?:good money|for)\b|\bworth paying for\b"),
    ("ask_tool", "asking for a tool", 4,
     rf"\b(?:is|are) there (?:a|an|any|some)\b(?!\s+(?:\w+\s+){{0,2}}(?:reason|chance|point|difference|downside|risk|benefit|evidence|proof|hope|possibility|issue|problem|limit)s?\b){GAP}\b{TOOL}\b"
     rf"|\b(?:does|do|has|have) (?:anyone|anybody|any of you|you guys|y'all)(?: here)? (?:know|use|have|recommend|found|tried)\b{GAP}\b{TOOL}\b"
     rf"|\b(?:anyone|anybody)(?: here)? (?:know|use|using|recommend|found|have)\b{GAP}\b{TOOL}\b"
     rf"|\blooking for (?:a |an |some |any |the best |good |decent )?{GAP}\b{TOOL}\b"
     rf"|\b(?:what|which)\b[^.?!\n]{{0,30}}?\b{TOOL}\b[^.?!\n]{{0,40}}?\b(?:do you|are you|does everyone|do y'all|do you all|do you guys|would you|should i|should we|is best|are people|do people|do other)\b"
     rf"|\b(?:what|which)\b[^.?!\n]{{0,30}}?\b{TOOL}\b[^.?!\n]{{0,30}}?\b(?:is|are|works?) (?:good|best|better|the best|recommended|worth)\b"
     rf"|\b(?:recommend|recommendation|recommendations|suggestions?)\b[^.?!\n]{{0,40}}?\b{TOOL}\b"
     rf"|\b{TOOL}\b[^.?!\n]{{0,25}}\b(?:recommendations?|suggestions?)\b"
     rf"|\bneed (?:a|an|some)\b[^.?!\n]{{0,40}}?\b{TOOL}\b (?:that|to|for|which)\b"),
    ("wish", "wishes it existed", 4,
     r"\bi (?:really |just |so |honestly )?wish (?:there (?:was|were|is)|someone would|somebody would|i could|we could|it (?:was|were) possible|i had|we had)\b"
     r"|\bif only there (?:was|were)\b|\bsomeone (?:should|needs to|please) (?:build|make|create|invent)\b"
     r"|\bwhy (?:is there no|isn't there|isnt there|hasn't anyone|has no ?one|hasn't someone|does no ?one|doesn't anyone)\b"
     r"|\bdoes (?:this|that|something like (?:this|that)|such a (?:thing|tool|app)|anything like (?:this|that)) (?:even |already |actually )?exist\b"),
    ("nothing_fits", "nothing on the market fits", 4,
     r"\b(?:nothing|none of (?:them|these|those)|no (?:tool|app|software|product|solution|system)s?) (?:seems? to |really |quite |that |out there )*(?:fits?|works?|does (?:this|that|what|it)|exists?|handles?|supports?|do(?:es)? what)\b"
     r"|\b(?:tried|looked at|tested|demoed|trialed) (?:everything|them all|a (?:bunch|ton|dozen|lot|few)|so many|several|\d+ (?:different )?(?:apps|tools|crms|platforms|options|products|systems))\b"
     r"|\b(?:can't|cannot|couldn't|could not|haven't been able to|unable to|struggling to) find (?:a|an|any|anything|one|something)\b"),
    ("better_way", "there must be a better way", 3,
     r"\bthere (?:has|must|have|'s got|has got) to be (?:a|an) (?:better|easier|faster|simpler) way\b"
     r"|\b(?:a|any) (?:better|easier|faster|more efficient|smarter) way (?:to|of)\b"),
    ("how_handle", "asking how others cope", 3,
     r"\bhow (?:do|does|are|did|is) (?:you|y'all|you all|you guys|everyone|everybody|other \w+(?: \w+)?|others|people|most \w+|your (?:team|office|shop|practice|company|firm|crew)) "
     r"(?:all |guys |even |actually |currently |folks )*(?:handle|handling|manage|managing|deal with|dealing with|keep track of|keeping track of|track|tracking|"
     r"organi[sz]e|organi[sz]ing|stay on top of|staying on top of|automate|automating|streamline|bill|invoice|schedule|scheduling|collect|store|document|price|quote)\b"),
    ("manual", "doing it by hand", 3, None),         # computed: manual work + pain
    ("spreadsheet", "outgrown a spreadsheet", 3, None),  # computed: spreadsheet + pain
    ("switch", "wants to leave a product", 3,
     r"(?i:alternatives? to|replacement for|substitute for|switch(?:ing|ed)? (?:away )?from|mov(?:e|ing|ed) (?:away )?from|migrat(?:e|ing|ed) (?:away )?from) (?=[A-Z0-9])"),
    ("ask_way", "asking if it's possible", 2,
     r"\bis there (?:a|any|an easy|an easier|a better|some|a simple) way to\b|\bany way to\b"),
    ("time_sink", "costs hours", 3,
     r"\b(?:spend|spending|spent|wastes?|wasting|wasted|takes? (?:me|us)|taking (?:me|us)|eats? up|lose|losing)\b[^.?!\n]{0,40}\b(?:hours|all day|forever|half (?:my|the|a) day|whole day|entire day|days|weekends?)\b"),
]
WEAK = [
    ("frustration", "frustrated", 1,
     r"\bfrustrat|\bnightmare\b|\bpain in the\b|\bdriv(?:es|ing) me (?:crazy|nuts|insane)\b|\bfed up\b|\bsick of\b|\bso annoying\b|\bhate (?:that|how|having|doing|when)\b"),
    ("too_expensive", "too expensive", 1,
     r"\btoo expensive\b|\boverpriced\b|\bprice (?:hike|increase)\b|\bcan't afford\b|\bcosts? (?:a fortune|too much)\b|\bpric(?:ed|ing) (?:us|me) out\b"),
]
_STRONG = [(k, l, w, re.compile(p, re.I) if p and "(?i:" not in p else (re.compile(p) if p else None)) for k, l, w, p in STRONG]
_WEAK = [(k, l, w, re.compile(p, re.I)) for k, l, w, p in WEAK]
LABEL = {k: l for k, l, _, _ in STRONG + WEAK}
LABEL.update({"gig": "paying for custom work", "idea_thread": "answer to “what problem needs solving?”"})

_MANUAL = re.compile(r"\bmanual(?:ly)?\b|\bby hand\b|\bcopy(?:ing)?(?: and |[- ]and[- ]|/| ?& ?| )past(?:e|ing)\b|\bdata entry\b|\bre-?(?:enter|type|key)(?:ing)?\b"
                     r"|\bdouble[- ]entry\b|\bpen and paper\b|\bpaper (?:forms?|files?|records?|logs?|notes|tickets|invoices)\b|\bwhiteboard\b|\bsticky notes\b|\bpost-?its?\b", re.I)
_SHEET = re.compile(r"\bspread ?sheets?\b|\bexcel\b|\bgoogle sheets?\b", re.I)
_PAIN = re.compile(r"\bhours\b|\bevery (?:single )?(?:day|week|month|time)\b|\btedious\b|\btime[- ]consuming\b|\bwast(?:e|ing)\b|\bnightmare\b|\b(?:sick|tired) of\b|\bhate\b"
                   r"|\bkilling (?:me|us)\b|\bdrowning\b|\boverwhelm|\bburn(?:ed|t|ing)? out\b|\bpainful\b|\ba mess\b|\bmessy\b|\berror[- ]prone\b|\bmistakes\b"
                   r"|\bfalls? through the cracks\b|\bslips? through\b|\bcan't keep up\b|\bcannot keep up\b|\bunmanageable\b|\bout of hand\b|\boutgr(?:ew|own|owing)\b"
                   r"|\bclunky\b|\bjanky\b|\bduct tape\b|\bheld together\b|\bbreaking\b|\binefficient\b|\bfrustrat", re.I)

# Posts by people selling something, not people with a problem.
_PROMO = re.compile(
    r"\b(?:i|we)(?:'ve| have)? (?:just |recently |finally |also )?(?:built|made|created|launched|developed|released|shipped|coded|vibe[- ]?coded)\b[^.?!\n]{0,50}"
    r"\b(?:app|tool|saas|platform|extension|plugin|software|site|website|product|bot|solution|startup|service|mvp|agent)\b"
    r"|\b(?:i'm|i am|we're|we are|i've been|we've been|currently) (?:building|working on|developing|launching|creating|validating) (?:a|an|my|our)\b"
    r"|\bmy (?:new |own |little |first )?(?:app|saas|startup|tool|product|side project|platform|extension|plugin|mvp)\b"
    r"|\b(?:our|my) (?:beta|waitlist|landing page)\b|\bfeedback on (?:my|our|this)\b|\broast my\b"
    r"|\bwould (?:you|anyone|people|this|it) (?:actually |ever |guys )?(?:use|pay for|be interested|find (?:this|it) useful|be useful)\b"
    r"|\bvalidat(?:e|ing) (?:my|an|this|the|a) (?:idea|problem|concept)\b|\b(?:beta )?testers? (?:wanted|needed)\b"
    r"|\blooking for (?:beta|early) (?:testers|users|adopters)\b|\bco-?founder\b|\b(?:dm|pm) me\b|\bsign ?up (?:here|now|today)\b"
    r"|\blink in (?:bio|comments|profile)\b|\bpromo code\b|\bdiscount code\b|\baffiliate\b|\bcheck (?:it|us|this) out\b|\bshow hn\b"
    r"|\bwe(?:'re| are) hiring\b|\[hiring\]|\[for hire\]|\bmarket research\b|\bquick survey\b|\bfill out (?:this|my|a) survey\b"
    r"|\bwhat (?:problems?|pain points?) (?:do you|are you|would you)\b|\bwhat would you (?:want|like) (?:in|from) (?:a|an)\b", re.I)
# One product's bug or account trouble: real, but not a niche worth building for.
_CAREER = re.compile(r"\bshould i learn\b|\bto learn first\b|\bimprove my (?:profile|resume|cv|skills)\b|\bwhere do i start\b|\bcomplete beginner\b|"
                     r"\bcareer (?:advice|change|path)\b|\bjob board\b|\b(?:contract|temp) roles?\b|\bstudy guide\b|\bexam\b|\bcertification (?:course|exam)\b", re.I)
_SUPPORT = re.compile(
    r"\berror (?:code|message)\b|\bnot working\b|\bstopped working\b|\bwon't (?:load|open|sync|connect|let me|start|install)\b"
    r"|\bcan't (?:log ?in|login|sign in|access my)\b|\bkeeps (?:crashing|freezing)\b|\bafter (?:the |an |this )?(?:latest |recent |new )?update\b"
    r"|\bpassword reset\b|\b2fa\b|\btwo[- ]factor\b|\baccount (?:locked|banned|suspended|disabled|hacked)\b|\brefund\b"
    r"|\bhow do i (?:fix|reset|change|enable|disable|turn (?:on|off)|get rid of)\b", re.I)

SENT = re.compile(r"(?<=[.!?])\s+|\n+")

# --------------------------------------------------------------------- niches
# Used when the source doesn't already say who is talking (a subreddit does).
NICHES = [
    ("Dental practices", r"\bdental\b|\bdentists?\b|\bhygienists?\b|\borthodont"),
    ("Veterinary clinics", r"\bveterinar|\bvet (?:clinic|tech|practice)\b|\banimal hospital\b"),
    ("Pharmacies", r"\bpharmac"),
    ("Therapists & counsellors", r"\btherapists?\b|\bcounsel(?:l)?ors?\b|\bpsychologists?\b|\btherapy practice\b|\bclient notes\b"),
    ("Medical practices & clinics", r"\b(?:medical|private) practice\b|\bclinics?\b|\bphysicians?\b|\bpatients?\b|\behr\b|\bemr\b|\bmedical billing\b|\burgent care\b"),
    ("Nursing & home care", r"\bnurses?\b|\bnursing\b|\bhome health\b|\bassisted living\b|\bhome care\b"),
    ("Short-term rental hosts", r"\bairbnb\b|\bvrbo\b|\bshort[- ]term rentals?\b|\bvacation rentals?\b|\bstr hosts?\b"),
    ("Landlords & property managers", r"\blandlords?\b|\btenants?\b|\brental propert|\bproperty manag|\brent roll\b|\bleases?\b"),
    ("Real estate agents", r"\brealtors?\b|\breal estate agents?\b|\bbrokerage\b|\bmls\b|\blisting agents?\b"),
    ("HVAC, plumbing & electrical", r"\bhvac\b|\bplumb(?:er|ers|ing)\b|\belectricians?\b|\bservice calls?\b|\bfield techs?\b"),
    ("Landscaping & lawn care", r"\blandscap|\blawn care\b|\bmowing\b|\bsnow removal\b|\birrigation\b"),
    ("Cleaning & home services", r"\bcleaning (?:business|company|service|clients)\b|\bmaid\b|\bjanitorial\b|\bpressure wash|\bpest control\b|\bhandyman\b|\bjunk removal\b"),
    ("Construction & contractors", r"\bcontractors?\b|\bconstruction\b|\bsubcontractors?\b|\bjob ?sites?\b|\bremodel|\brenovation\b|\bchange orders?\b|\btake-?offs?\b"),
    ("Auto repair & dealerships", r"\bauto (?:repair|shop|body)\b|\bmechanic shop\b|\bdetailing\b|\bdealerships?\b|\btire shop\b|\brepair orders?\b"),
    ("Restaurants, bars & cafés", r"\brestaurants?\b|\bbar owner\b|\bcaf[eé]s?\b|\bcoffee shop\b|\bkitchen staff\b|\bfood trucks?\b|\bcatering\b|\bbakery\b|\bline cooks?\b"),
    ("Trucking & freight", r"\btruck(?:ing|ers?)\b|\bfreight\b|\bdispatch(?:er|ers|ing)?\b|\bowner[- ]operators?\b|\bcarriers?\b|\bbills? of lading\b"),
    ("Logistics & warehousing", r"\bwarehouses?\b|\blogistics\b|\bsupply chain\b|\bpallets?\b|\b3pl\b|\bcycle counts?\b"),
    ("Manufacturing & machining", r"\bmanufactur|\bmachine shop\b|\bcnc\b|\bfabricat|\bproduction (?:line|floor|schedule)\b|\bbill of materials\b|\bwork orders?\b"),
    ("E-commerce sellers", r"\bshopify\b|\bwoocommerce\b|\be-?commerce\b|\bonline store\b|\bdropship|\betsy\b|\bamazon (?:fba|seller)\b|\bebay\b|\bskus?\b|\bfulfil?lment\b"),
    ("Retail shops", r"\bretail (?:store|shop)\b|\bboutique\b|\bbrick[- ]and[- ]mortar\b|\bstorefront\b|\bshop owner\b|\bpoint of sale\b|\bpos system\b|\bconsignment\b"),
    ("Tax preparers", r"\btax (?:prep|preparers?|season|returns?|pros?|practice)\b|\benrolled agent\b"),
    ("Accountants & bookkeepers", r"\baccountants?\b|\bbookkeep|\bcpas?\b|\baccounting firm\b|\bmonth[- ]end\b|\breconcil|\bquickbooks\b|\bxero\b"),
    ("Insurance agents", r"\binsurance (?:agents?|agency|brokers?)\b|\bclaims adjusters?\b|\bunderwrit"),
    ("Financial advisors", r"\bfinancial (?:advisors?|advisers?|planners?)\b|\bwealth manag|\bria\b"),
    ("Lawyers & paralegals", r"\blawyers?\b|\battorneys?\b|\blaw firm\b|\bparalegals?\b|\blegal (?:practice|assistant)\b|\bcase management\b|\bdocket"),
    ("Childcare providers", r"\bdaycare\b|\bchildcare\b|\bpreschool\b|\bnann(?:y|ies)\b"),
    ("Teachers & schools", r"\bteachers?\b|\bclassroom\b|\bgrading\b|\blesson plans?\b|\bschool district\b|\bmy students\b|\biep\b"),
    ("Professors & researchers", r"\bprofessors?\b|\bfaculty\b|\bphd\b|\bpostdoc\b|\bmy lab\b|\bresearch (?:group|lab|team)\b|\bdissertation\b|\bgrant (?:proposal|application)s?\b"),
    ("Nonprofits & fundraising", r"\bnonprofits?\b|\bnon-profits?\b|\bdonors?\b|\bfundrais|\b501\(?c\)?\b|\bcharity\b|\bgrant writing\b|\bvolunteers?\b"),
    ("Churches, clubs & HOAs", r"\bchurch\b|\bcongregation\b|\bministry\b|\bhoa\b|\bhomeowners association\b|\bclub members\b|\byouth league\b|\bbooster club\b"),
    ("Event & wedding pros", r"\bwedding (?:planner|photograph|venue|dj|vendors?)\b|\bevent (?:planner|planning|venue|production)\b|\bcaterers?\b|\bflorists?\b"),
    ("Photographers & videographers", r"\bphotograph(?:er|ers|y business)\b|\bvideograph|\bclient galler"),
    ("Fitness studios & trainers", r"\bpersonal train|\bgym (?:owner|members)\b|\byoga studio\b|\bpilates\b|\bfitness studio\b|\bmartial arts\b"),
    ("Salons, spas & beauty", r"\bsalons?\b|\bbarbers?\b|\bstylists?\b|\bestheticians?\b|\bmed ?spa\b|\bnail techs?\b|\blash\b|\btattoo\b"),
    ("Farms & ranches", r"\bfarm(?:s|ers?|ing)?\b|\branch\b|\blivestock\b|\bcrops?\b|\borchard\b|\bbeekeep|\bgreenhouse\b"),
    ("IT admins & MSPs", r"\bsysadmins?\b|\bmsp\b|\bhelp ?desk\b|\bactive directory\b|\bendpoints?\b|\bit (?:department|manager|admin|team)\b"),
    ("HR & recruiting", r"\brecruit(?:er|ers|ing)\b|\bapplicants?\b|\bonboarding\b|\bhr (?:team|department|manager)\b|\bpayroll\b|\btimesheets?\b"),
    ("Sales teams", r"\bsales (?:team|reps?|pipeline)\b|\bcold (?:call|email)\b|\bprospecting\b"),
    ("Customer support teams", r"\bsupport (?:team|tickets|agents)\b|\bhelp center\b|\bcustomer success\b"),
    ("Marketing & agencies", r"\bagency\b|\bmarketing team\b|\bseo\b|\bppc\b|\bsocial media manag|\bcontent calendar\b|\bclient reporting\b"),
    ("Freelancers & consultants", r"\bfreelanc|\bconsultants?\b|\bsolopreneur\b|\bmy clients\b"),
    ("Musicians, podcasters & creators", r"\bmusicians?\b|\bmy band\b|\bpodcast|\byoutube channel\b|\bstreamers?\b|\bcreators?\b"),
    ("Caregivers", r"\bcaregiv|\belderly (?:parent|mother|father|mom|dad)\b|\baging parents?\b|\bdementia\b"),
    ("ADHD & neurodivergent", r"\badhd\b|\bautis|\bexecutive (?:dys)?function"),
    ("Health tracking & chronic illness", r"\bchronic\b|\bsymptoms?\b|\bmedications?\b|\bdiabet|\bmigraines?\b"),
    ("Parents & families", r"\bmy (?:kids?|child|children|son|daughter|toddler)\b|\bco-?parent|\bfamily (?:calendar|schedule)\b|\bchores\b"),
    ("Students", r"\bcollege\b|\buniversity\b|\bstudying\b|\bexams?\b|\bhomework\b|\bcoursework\b"),
    ("Job seekers", r"\bjob (?:search|hunt|applications?)\b|\bresumes?\b|\bcover letters?\b"),
    ("Personal finance", r"\bbudget(?:ing)?\b|\bdebt\b|\bsavings\b|\bcredit cards?\b|\bsubscriptions\b|\bnet worth\b"),
    ("Homeowners & DIY", r"\bhomeowners?\b|\bhome (?:maintenance|renovation|improvement)\b|\bmy house\b"),
    ("Pet owners", r"\bmy (?:dog|cat|pets?)\b"),
    ("Travelers", r"\bitinerar|\btrip planning\b|\bflights?\b|\btravel(?:ing|ling)?\b"),
    ("Developers & technical teams", r"\bdevelopers?\b|\bengineering team\b|\bdevops\b|\bcodebase\b|\brepos?\b|\bapi\b|\bdeploy|\bkubernetes\b|\bci/cd\b"),
]
_NICHES = [(n, re.compile(p, re.I)) for n, p in NICHES]
GENERAL = "General"


def detect_niche(text):
    best, best_n = None, 0
    for name, rx in _NICHES:
        n = len(rx.findall(text))
        if n > best_n:
            best, best_n = name, n
    return best


# --------------------------------------------------------------------- themes
# theme -> (search phrase for validation, keywords)
THEMES = {
    "Scheduling & booking": ("scheduling software", ["schedul", "booking", "appointment", "calendar", "no-show", "no show", "reservation", "shift", "dispatch"]),
    "Invoicing & getting paid": ("invoicing software", ["invoice", "invoicing", "payment", "billing", "late pay", "accounts receivable", "deposit", "collect payment", "past due"]),
    "Bookkeeping & tax": ("bookkeeping software", ["bookkeep", "accounting", "reconcil", "ledger", "tax", "receipt", "expense", "1099", "month-end", "chart of accounts"]),
    "Estimates, quotes & proposals": ("estimating software", ["estimate", "quote", "proposal", "bid", "takeoff", "take-off", "pricing jobs"]),
    "Leads, CRM & follow-up": ("crm", ["crm", "lead", "pipeline", "prospect", "follow up", "follow-up", "outreach", "referral"]),
    "Client communication & reminders": ("client communication software", ["reminder", "text message", "sms", "client portal", "client communication", "notify", "notification", "intake form", "intake"]),
    "Inventory & stock": ("inventory management software", ["inventory", "stock", "sku", "parts", "reorder", "barcode", "cycle count"]),
    "Orders, shipping & fulfilment": ("order management software", ["order", "shipping", "fulfil", "shipment", "tracking number", "freight", "delivery", "returns", "label"]),
    "Staff, hiring & payroll": ("workforce management software", ["hiring", "recruit", "applicant", "payroll", "onboarding", "employee", "timesheet", "time tracking", "pto", "staffing", "crew"]),
    "Jobs, projects & tasks": ("job management software", ["project", "task", "work order", "job tracking", "checklist", "deadline", "kanban", "punch list", "to-do", "todo"]),
    "Documents, forms & records": ("document management software", ["document", "paperwork", "form", "pdf", "contract", "signature", "e-sign", "records", "filing", "template", "notes"]),
    "Reporting & spreadsheets": ("reporting software", ["spreadsheet", "excel", "google sheet", "report", "dashboard", "analytics", "csv", "data entry", "pivot"]),
    "Connecting tools & automation": ("workflow automation software", ["integrat", "zapier", "automat", "api", "webhook", "sync", "workflow", "import", "export"]),
    "Compliance, licences & audits": ("compliance software", ["compliance", "regulation", "audit", "license", "licence", "certification", "inspection", "hipaa", "gdpr", "osha", "permit"]),
    "Marketing, reviews & social": ("marketing software", ["marketing", "newsletter", "email list", "campaign", "seo", "ads", "social media", "reviews", "google business", "content"]),
    "Customer support": ("help desk software", ["customer support", "helpdesk", "help desk", "ticket", "live chat", "complaint", "customer service"]),
    "Online store & listings": ("ecommerce software", ["product listing", "listings", "storefront", "checkout", "cart", "variants", "catalog", "marketplace"]),
    "Money, budgets & subscriptions": ("budgeting app", ["budget", "savings", "debt", "subscriptions", "bills", "net worth", "cash flow", "spending"]),
    "Health, habits & care": ("health tracking app", ["symptom", "medication", "habit", "sleep", "diet", "meal", "workout", "care plan", "appointments for"]),
    "Learning & teaching": ("education software", ["grading", "lesson", "course", "curriculum", "study", "flashcard", "homework", "assignment"]),
    "Meetings, email & messaging": ("team communication software", ["meeting", "inbox", "email", "slack", "teams", "transcri", "voicemail", "phone calls"]),
    "Property & maintenance": ("property management software", ["tenant", "rent", "lease", "maintenance request", "work order", "turnover", "inspection", "hoa"]),
    "Pricing & affordability": ("affordable alternative", ["too expensive", "price increase", "pricing", "overpriced", "per seat", "per user", "subscription fee", "can't afford"]),
}


def _kw_rx(kws):
    """Short keywords must match whole words ("pos" != "possible"); longer ones match word prefixes."""
    return [re.compile(r"\b" + re.escape(k.strip()) + (r"\b" if len(k.strip()) <= 4 else ""), re.I) for k in kws]


_THEME_RX = {t: _kw_rx(k) for t, (_, k) in THEMES.items()}
OTHER = "Other needs"


def themes_for(text):
    scored = []
    for theme, rxs in _THEME_RX.items():
        n = sum(1 for rx in rxs if rx.search(text))
        if n:
            scored.append((n, theme))
    scored.sort(key=lambda x: -x[0])
    return [th for _, th in scored[:2]] or [OTHER]


SAAS_POSITIVE = _kw_rx([
    "tool", "app", "software", "saas", "dashboard", "automate", "automation", "integrat", "sync", "track",
    "spreadsheet", "excel", "manually", "workflow", "report", "export", "import", "api", "plugin", "extension",
    "template", "crm", "invoice", "schedul", "notification", "remind", "database", "portal", "online", "platform"])
SAAS_NEGATIVE = _kw_rx([
    "government", "legislation", "landlord won't", "my boss", "coworker", "salary", "wages", "rent is",
    "housing market", "insurance denied", "shortage", "tariff", "union", "injury", "lawsuit", "burnout", "understaffed"])


def saas_fit_for(text, signals):
    pos = sum(1 for rx in SAAS_POSITIVE if rx.search(text))
    neg = sum(1 for rx in SAAS_NEGATIVE if rx.search(text))
    base = 2 if set(signals) & {"ask_tool", "pay", "spreadsheet", "manual", "switch", "gig"} else 0
    v = base + pos - 2 * neg
    return "high" if v >= 3 else "medium" if v >= 1 else "low"


def costs_for(signals, text):
    """Problems are grounded in time or money spent."""
    out = []
    if set(signals) & {"time_sink", "manual", "spreadsheet", "better_way"}:
        out.append("time")
    if set(signals) & {"pay", "too_expensive", "gig"} or re.search(r"\bcost(?:s|ing)? (?:me|us)\b|\blos(?:e|ing|t) (?:money|customers|clients|revenue)\b", text, re.I):
        out.append("money")
    return out


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
looking wish tool app software there's i'll thanks thank please help anybody advice question
""".split())


def keywords_for(text, n=8):
    words = [w.strip("'-") for w in re.sub(r"[^a-z0-9'\- ]+", " ", text.lower()).split()]
    words = [w for w in words if len(w) > 2 and w not in STOP and not w.isdigit()]
    grams = Counter()
    for a, b in zip(words, words[1:]):
        grams[f"{a} {b}"] += 1
    return [g for g, _ in grams.most_common(n)]


# ----------------------------------------------------------- signals + need
# A signal only counts when the sentence it sits in is about software or a work process.
# "Looking for a better tool" from a carpenter, "we've tried everything" from a parent and
# "I'd pay the fine" are the same words as a lead, but not leads.
SOFT = re.compile(
    r"\b(?:apps?|software|saas|crm|erp|plugins?|plug-ins?|extensions?|add-?ons?|platforms?|web ?apps?|websites?|spread ?sheets?|excel|"
    r"google (?:sheets?|docs|forms?|calendar)|airtable|notion|zapier|quickbooks|xero|automat\w+|integrat\w+|dashboards?|templates?|"
    r"databases?|portals?|apis?|sync(?:s|ed|ing)?|cloud[- ]based|ios|android|chrome|subscriptions?|scripts?|macros?|bots?|chatgpt|"
    r"point of sale|pos system|online (?:tool|system|portal|booking|form|scheduler|calendar)s?|e-?sign\w*|text reminders?|sms)\b", re.I)
_UNAMB = re.compile(r"\b(?:apps?|software|saas|crm|plugins?|plug-ins?|extensions?|platforms?|websites?|add-?ons?|integrations?|bots?|databases?|portals?|scripts?)\b", re.I)
_TOOLN = re.compile(rf"\b{TOOL}\b", re.I)
_FIRST = re.compile(r"\b(?:i|we|my|our|i'm|we're|i've|we've|me|us|anyone else|anybody else)\b", re.I)
_NEG = re.compile(r"\b(?:not|never|isn't|aren't|wasn't)\b|n't\b", re.I)
# Trades where "tool", "system" or "solution" usually means something you hold or install.
PHYSICAL_NICHES = {"Construction & contractors", "HVAC, plumbing & electrical", "Landscaping & lawn care", "Auto repair & dealerships",
                   "Manufacturing & machining", "Farms & ranches", "Salons, spas & beauty", "Cleaning & home services"}
_BUSINESS = re.compile(
    r"\b(?:my|our) (?:business|company|shop|store|clinic|practice|firm|agency|team|office|restaurant|warehouse|clients?|customers?|patients?|"
    r"staff|employees|crews?|techs|tenants|students|members|donors|vendors|suppliers|bookkeeper|accountant|jobs|properties|units|listings)\b"
    r"|\bi (?:run|own|manage|operate)\b|\bwe (?:run|are a|have \d+)\b|\bwe're a\b|\bsmall business\b|\bself[- ]employed\b|\bsolo (?:practice|practitioner|attorney|shop)\b", re.I)
_CLAUSE = re.compile(rf"\b{TOOL}\b[^.?!]{{0,20}}?\b(?:that|which|to|for|where|so)\b\s+\w+\s+\w+", re.I)
_PAY_OBJ = re.compile(r"pay (?:\w+ ){0,3}?for (?:something|anything|one|this|that|it|a|an)\b", re.I)
_WISH_COULD = re.compile(r"\bi (?:really |just |so |honestly )?wish (?:i could|we could|i had|we had|it (?:was|were) possible)\b", re.I)
_WISH_EXISTS = re.compile(
    r"\bi (?:really |just |so |honestly )?wish (?:there (?:was|were|is)|someone would|somebody would)\b"
    r"|\bif only there (?:was|were)\b|\bsomeone (?:should|needs to|please) (?:build|make|create|invent)\b"
    r"|\bwhy (?:is there no|isn't there|isnt there|hasn't anyone|has no ?one|hasn't someone|does no ?one|doesn't anyone)\b"
    r"|\bdoes (?:this|that|something like (?:this|that)|such a (?:thing|tool|app)|anything like (?:this|that)) (?:even |already |actually )?exist\b", re.I)
_RX = {k: rx for k, _, _, rx in _STRONG if rx is not None}
_W = {k: w for k, _, w, _ in STRONG}
_HOW = re.compile(
    r"\bhow (?:do|does|are|did|is) (?:you|y'all|you all|you guys|everyone|everybody|other \w+(?: \w+)?|others|people|most \w+|your (?:team|office|shop|practice|company|firm|crew)) "
    r"(?:all |guys |even |actually |currently |folks )*(?:handle|handling|manage|managing|keep track of|keeping track of|track|tracking|"
    r"organi[sz]e|organi[sz]ing|stay on top of|staying on top of|automate|automating|streamline|bill|invoice|schedule|scheduling|collect|store|document|price|quote)\b", re.I)

# Who is speaking as a private person, not as someone doing a job.
CONSUMER_NICHES = {"Caregivers", "ADHD & neurodivergent", "Health tracking & chronic illness", "Parents & families", "Students",
                   "Job seekers", "Personal finance", "Homeowners & DIY", "Pet owners", "Travelers"}
CONSUMER_THEMES = {"Money, budgets & subscriptions", "Health, habits & care", "Pricing & affordability"}
_WORK_KW = [rx for t, rxs in _THEME_RX.items() if t not in CONSUMER_THEMES for rx in rxs]


def _work_topic(s):
    return any(rx.search(s) for rx in _WORK_KW)


def _sentences(title, text):
    parts = ([title.strip()] if title and title.strip() else []) + [x.strip() for x in SENT.split(text or "")]
    return [x for x in parts if 20 <= len(x) <= 500]


def _qualify(sent, c):
    """Signals in this sentence that are about software or a work process. c = facts about the whole post."""
    hits = []
    soft_post, work, pain_post, topic_post = c["soft"], c["work"], c["pain"], c["topic"]
    soft, first = bool(SOFT.search(sent) or _UNAMB.search(sent)), bool(_FIRST.search(sent))
    topic = _work_topic(sent)
    m = _RX["ask_tool"].search(sent)
    if m and not _NEG.search(sent[max(0, m.start() - 24):m.start() + 4]):
        # "tool", "system", "solution" need backing: software in the sentence or title, or a work topic.
        if _UNAMB.search(m.group(0)) or soft or c["soft_title"] or (
                soft_post and topic if c["physical"] else work and (topic or topic_post)):
            hits.append("ask_tool")
    if (_WISH_EXISTS.search(sent) and (soft or (work and topic))) or (_WISH_COULD.search(sent) and soft):
        hits.append("wish")
    if _RX["pay"].search(sent) and (soft or (soft_post and _PAY_OBJ.search(sent))):
        hits.append("pay")
    if _RX["nothing_fits"].search(sent) and soft:
        hits.append("nothing_fits")
    # "Alternatives to X" is a search for a replacement. "Moving from X" needs software context (it may be a city).
    if _RX["switch"].search(sent) and products_for(sent) and (soft_post or (work and re.search(r"(?i)\balternatives? to\b|\breplacement for\b", sent))):
        hits.append("switch")
    if _HOW.search(sent) and work and (topic or soft):
        hits.append("how_handle")
    if _MANUAL.search(sent) and first and work and (pain_post or _PAIN.search(sent)) and (topic_post or soft_post):
        hits.append("manual")
    if _SHEET.search(sent) and first and (_PAIN.search(sent) or (work and pain_post)):
        hits.append("spreadsheet")
    if _RX["time_sink"].search(sent) and first and work and (topic or soft or _MANUAL.search(sent)):
        hits.append("time_sink")
    if _RX["better_way"].search(sent) and work and (topic or soft):
        hits.append("better_way")
    if _RX["ask_way"].search(sent) and work and (topic or soft):
        hits.append("ask_way")
    return hits


# Founders fishing for pain points or demand, written to look like a peer's question.
_RESEARCH = re.compile(
    r"\bwhat(?:'s| is| are) (?:your|the) (?:biggest|main|most|top|#1|number one|single biggest) (?:\w+ )?(?:pain|challenge|headache|frustration|problem|time[- ]?suck|bottleneck|struggle)"
    r"|\bwhat (?:do|would|did) you (?:wish|hate|dislike)\b|\bwhat would make (?:it|you|this)\b|\bdeal-?breakers?\b"
    r"|\bi (?:surveyed|interviewed|talked (?:to|with)|spoke (?:to|with)|asked) (?:over |about |around |nearly )?\d+\b|\b(?:doing|conducting) (?:some |a bit of |market |customer |user )*research\b"
    r"|\bnot (?:selling|promoting|pitching)\b|\bno (?:pitch|sales pitch|self[- ]promo(?:tion)?)\b|\bnot (?:a |an )?(?:ad|advert|promo|sales pitch|promotion)\b"
    r"|\bis there (?:any |a |real |enough )?(?:demand|market|appetite) for\b|\bwould (?:there be|this be|that be) (?:any |enough )?(?:interest|demand|useful|valuable)\b"
    r"|\b(?:thinking|considering) (?:of|about) (?:building|making|creating|developing)\b|\bi(?:'m| am) (?:a |an )?(?:developer|software engineer|founder|indie hacker|product manager|programmer|dev)\b"
    r"|\bhow (?:do|are) you (?:all |guys )?(?:currently )?(?:handl|manag|track|do)\w* (?:it|this|that) (?:right now|now|today|currently)\b"
    r"|\b(?:genuinely |just |honestly )?curious (?:how|what|if|whether) (?:others|other \w+|you|people|most|everyone|anyone)\b"
    r"|\bwould love (?:your|any|some|to (?:hear|get)) (?:your )?(?:feedback|thoughts|input) on (?:my|our|this|the idea)\b|\bhonest (?:feedback|opinions?)\b"
    r"|\bwhat (?:software|tools?|apps?) (?:do|are) you (?:currently |all |guys )?(?:pay|paying) for\b"
    r"|\bi(?:'m| am) (?:researching|exploring|validating|prototyping|designing) (?:a|an|the|whether|if)\b|\bfeel free to answer\b"
    r"|\blooking for (?:\w+ )?(?:ideas|problems|pain points) (?:for|to|that|worth)\b"
    r"|\byou(?:'ve| have)? (?:genuinely |always |ever |really )*wish(?:ed)? (?:someone|somebody|existed|there was)\b|\bwhat could save (?:you|your)\b"
    r"|\b(?:problem|app|tool|thing)s? (?:in your (?:daily )?life |at work )?(?:that )?you(?:'d| would)? (?:wish|want|pay)\b|\bhave you ever (?:wished|wanted|needed)\b"
    r"|\bweek of (?:january|february|march|april|may|june|july|august|september|october|november|december)\b|\bnews recap\b"
    r"|\bhow (?:do|are) you (?:all |guys )?currently\b|\b(?:about )?how much time do you (?:spend|waste)\b|\bwhat(?:'s| is) the most (?:frustrating|annoying|painful|time[- ]consuming)\b"
    r"|\bwhat(?:'s| is) the one thing (?:it|they|your)\b|\bquick (?:question|poll) for (?:all )?(?:the )?\w+ (?:owners|sellers|managers|pros)\b", re.I)


def score_item(it, min_strong=3):
    """Annotates the item. it['keep'] says whether it is a lead."""
    title, text = it.get("title") or "", it.get("text") or ""
    full = f"{title}\n{text}"
    it["keep"], it["signals"] = False, []
    if len(full) < 60:
        return it
    hint = it.get("niche_hint")
    niche = hint or detect_niche(full) or GENERAL
    soft_post, pain_post = bool(SOFT.search(full)), bool(_PAIN.search(full))
    # Speaking as someone doing a job: the community says so, or the post does ("my clients", "I run a...").
    work = bool(hint and hint not in CONSUMER_NICHES) or bool(_BUSINESS.search(full))
    c = {"soft": soft_post, "work": work, "pain": pain_post, "topic": _work_topic(full),
         "soft_title": bool(SOFT.search(title) or _UNAMB.search(title)), "physical": niche in PHYSICAL_NICHES}

    best, best_w, keys = None, 0, []
    for sent in _sentences(title, text):
        hits = _qualify(sent, c)
        if not hits:
            continue
        w = sum(_W[h] for h in hits) + (1.5 if _CLAUSE.search(sent) else 0) + (1 if len(sent) >= 60 else 0)
        if w > best_w:
            best, best_w = sent, w
        keys += [h for h in hits if h not in keys]
    implied = it.get("implied")  # the source itself is the signal (a gig, a software-request site, an idea thread)
    if implied and implied not in keys and (implied != "idea_thread" or soft_post or c["topic"]):
        keys.insert(0, implied)
    strong = sum({"gig": 4, "idea_thread": 3}.get(k, _W.get(k, 0)) for k in keys)
    it["signals"] = keys
    if strong < min_strong:
        return it
    if it["kind"] != "gig" and (_PROMO.search(full) or _RESEARCH.search(full)):
        it["dropped"] = "promo"
        return it
    if _SUPPORT.search(full) and not (set(keys) & {"pay", "wish", "nothing_fits", "gig"}):
        it["dropped"] = "support"
        return it
    if it["kind"] != "gig" and _CAREER.search(full):
        it["dropped"] = "career"
        return it

    weak = [k for k, _, _, rx in _WEAK if rx.search(full)]
    keys += weak
    themes = themes_for(full)
    # Business: speaking as someone doing a job. Everything else is a private person's wish.
    named = niche != GENERAL and niche not in CONSUMER_NICHES  # the text itself names a line of work
    it["segment"] = "business" if (work or named or it["kind"] == "gig") else "consumer"
    it["buyer_pts"] = (25 if (it["kind"] == "gig" or (hint and hint not in CONSUMER_NICHES)) else 20 if work else 16 if named
                       else 8 if niche == GENERAL else 6)
    it["niche"] = niche
    it["themes"] = themes
    it["saas_fit"] = saas_fit_for(full, keys)
    it["costs"] = costs_for(keys, full)
    if not best and it["kind"] == "gig":
        best = next((x for x in _sentences("", text) if re.search(r"\b(?:need|looking for|want|require|would like)\b", x, re.I)), None)
    need = re.sub(r"\s+", " ", best or title or text).strip()
    if best and title and title.strip() not in need and (len(need) < 70 or not _CLAUSE.search(need)):
        need = f"{title.strip().rstrip('.:')}: {need}"
    it["need"] = need[:320]
    if not title or title.lower().startswith("comment on"):
        it["title"] = short(it["need"], 110)
    it["keywords"] = keywords_for(full)
    it["signal_labels"] = [LABEL[k] for k in keys if k in LABEL]
    products = products_for(full)
    if products:
        it["products"] = products
        it["complaints"] = complaint_types_for(full)
    score = (min(strong, 12) + min(len(weak), 2) + (1.5 if best and _CLAUSE.search(best) else 0)
             + (1 if niche != GENERAL else 0) + (1 if themes[0] != OTHER and themes[0] not in CONSUMER_THEMES else 0)
             + min(2.0, 0.4 * math.log1p(max(0, it.get("engagement", 0)))))
    it["pain_score"] = round(score, 1)
    it["keep"] = True
    return it


def short(t, n=90):
    t = re.sub(r"\s+", " ", t or "").strip()
    return t if len(t) <= n else t[: n - 1].rsplit(" ", 1)[0] + "…"


# --------------------------------------------- products people want to leave
_PRODUCT = re.compile(
    r"(?i:alternatives? to|replacement for|substitute for|switch(?:ing|ed)? (?:away )?from|mov(?:e|ing|ed) (?:away )?from|"
    r"migrat(?:e|ing|ed) (?:away )?from|leaving|ditching|cancel(?:l)?(?:ing|ed)|fed up with|sick of|outgr(?:ew|own|owing)) "
    r"((?:[A-Z][A-Za-z0-9.+]*|[a-z]+[A-Z][A-Za-z0-9]*|[A-Z0-9]{2,})(?:[ -](?:[A-Z][A-Za-z0-9.+]*|[0-9]{1,4}))?)")
_NOT_PRODUCT = {"i", "the", "my", "we", "it", "this", "that", "they", "there", "these", "those", "our", "your", "you", "he",
                "she", "a", "an", "and", "but", "if", "so", "is", "any", "all", "what", "when", "how", "why", "one", "some",
                "us", "to", "in", "on", "for", "no", "not", "ai", "it's", "i'm", "usa", "uk", "us", "eu", "ceo", "saas", "crm",
                "erp", "pos", "hr", "it", "pc", "january", "february", "march", "april", "may", "june", "july", "august",
                "september", "october", "november", "december", "monday", "friday", "paper", "excel sheets"}


def products_for(text):
    out = []
    for m in _PRODUCT.finditer(text):
        name = m.group(1).strip(" .,-")
        if len(name) >= 3 and name.lower() not in _NOT_PRODUCT and name.split()[0].lower() not in _NOT_PRODUCT and name not in out:
            out.append(name)
    return out[:3]


COMPLAINTS = {
    "too_expensive": r"\bexpensive|overpriced|price (?:increase|hike)|pricey|hidden fees?|not worth (?:the|it)|raised (?:the|their) price|per (?:seat|user)|can't afford|cost",
    "missing_feature": r"\bmissing|doesn't (?:support|have|allow|let|do)|does not (?:support|have|allow|let|do)|no (?:way|option) to|\black(?:s|ing)\b|can't even|cannot even|limited|limitation",
    "hard_to_use": r"\bconfusing|hard to (?:use|figure|understand|navigate|set ?up|learn)|complicated|not intuitive|unintuitive|clunky|learning curve|too complex|overkill|bloated",
    "unreliable": r"\bbug(?:gy|s)?\b|crash|broken|glitch|unreliable|lost (?:all )?(?:my |our )?data|downtime|outage",
    "integrations": r"\bintegrat|\bsync|\bapi\b|zapier|\bexport|\bimport",
    "bad_support": r"\bsupport (?:is|was|team)|customer service|no response|never (?:replied|responded|answered|heard back)",
    "slow": r"\bslow\b|\blag(?:gy)?\b|takes forever",
    "acquired_or_changed": r"\bacquired|bought by|shutting down|sunset|discontinu|end of life|new owner|forced (?:upgrade|migration)|subscription[- ]only",
}
_COMPLAINT_RX = {k: re.compile(v, re.I) for k, v in COMPLAINTS.items()}


def complaint_types_for(text):
    return [k for k, rx in _COMPLAINT_RX.items() if rx.search(text)]


# ------------------------------------------- what people use spreadsheets for
_STOP_AT = (r"(?=[,.;:()\n•\-–—!?]|\s+(?:and|or|to|with|for|in|on|across|using|as|by|within|from|that|while|including|per|via|at|"
            r"but|because|so|which|is|are|was|it|i|we|then|when|where|since|until|though|if)\b|$)")
_SHEETW = r"(?:spread ?sheets?|excel(?: sheets?| files?| workbooks?)?|google sheets?|a (?:shared |giant |massive |huge |big )?sheet)"
_SHEET_VERB = (r"(?:track(?:ing)?|manag(?:e|ing)|keep(?:ing)? track of|log(?:ging)?|plan(?:ning)?|calculat(?:e|ing)|"
               r"organiz(?:e|ing)|record(?:ing)?|monitor(?:ing)?|schedul(?:e|ing)|run(?:ning)?|stor(?:e|ing)|maintain(?:ing)?|handl(?:e|ing))")
_SHEET_RX = [
    re.compile(_SHEETW + r"\s+(?:to|for)\s+" + _SHEET_VERB + r"\s+((?:[a-z'/-]+\s+){0,3}?[a-z'/-]+)" + _STOP_AT, re.I),
    re.compile(_SHEETW + r"\s+for\s+((?:[a-z'/-]+\s+){0,2}?[a-z'/-]+(?:s|ing))" + _STOP_AT, re.I),
    re.compile(r"\b" + _SHEET_VERB + r"\s+((?:[a-z'/-]+\s+){0,3}?[a-z'/-]+)\s+(?:in|on|with|using|via)\s+(?:a |an |our |my |the |one |multiple |several )?"
               r"(?:big |giant |shared |massive |huge |single |simple |basic |messy |complicated )?" + _SHEETW, re.I),
]
_LEAD = {"the", "all", "our", "a", "an", "any", "my", "your", "their", "its", "his", "her", "this", "these", "those", "some",
         "each", "every", "daily", "weekly", "monthly", "various", "multiple", "new", "existing", "different", "many", "of"}
_VAGUE = {"everything", "stuff", "things", "data", "it", "them", "this", "that", "information", "info", "all", "business",
          "work", "figure", "analyze", "calculate", "see", "make", "keep", "help", "everyone", "anything", "something",
          "numbers", "details", "items", "progress", "now", "years", "example", "me", "us", "myself", "ages", "lot", "lots"}


def spreadsheet_uses_for(text):
    out = []
    for rx in _SHEET_RX:
        for m in rx.finditer(text):
            words = re.sub(r"[^a-z&/' -]", " ", m.group(1).lower()).split()
            while words and words[0] in _LEAD:
                words.pop(0)
            while words and (words[-1] in _LEAD or words[-1] in STOP):
                words.pop()
            if not words or len(words) > 4 or all(w in _VAGUE or w in STOP for w in words):
                continue
            ph = " ".join(words)
            if len(ph) >= 4 and not any(ph in o or o in ph for o in out):
                out.append(ph)
    return out[:4]


# --------------------------------------------------------------- clustering
def _slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def search_keyword(niche, theme):
    base = THEMES.get(theme, ("software",))[0]
    return base if niche == GENERAL else f"{base} for {niche.lower().replace(' & ', ' and ')}"


def niche_clusters(items, max_clusters=60):
    """Group leads by who has the problem and what kind it is. The key is stable from week
    to week, so the same niche + problem area can be followed over time."""
    groups = defaultdict(list)
    for it in items:
        groups[(it["niche"], it["themes"][0])].append(it)
    clusters = []
    for (niche, theme), members in groups.items():
        members.sort(key=lambda x: -x.get("opp", x["pain_score"]))
        if len(members) < 2 and members[0].get("opp", 0) < 55:
            continue
        top = members[0]
        others = [o for o in dict.fromkeys(short(m["need"], 110) for m in members[1:6]) if o != short(top["need"], 110)]
        clusters.append({
            "key": f"{_slug(niche)}--{_slug(theme)}",
            "title": theme if niche == GENERAL else f"{niche}: {theme[0].lower() + theme[1:]}",
            "summary": f"\u201c{short(top['need'], 220)}\u201d" + (f" Also: \u201c{others[0]}\u201d" if others else ""),
            "niche": niche,
            "theme": theme,
            "saas_fit": Counter(m["saas_fit"] for m in members).most_common(1)[0][0],
            "costs": sorted({c for m in members for c in m.get("costs", [])}),
            "search_keyword": search_keyword(niche, theme),
            "item_ids": [m["id"] for m in members],
            "sources": sorted({m["source"] for m in members}),
            "method": "niche",
        })
    return clusters[:400]


# ------------------------------------------------------------------ replies
# What the replies say decides whether a need is unmet: "same here" versus "just use X".
_ME_TOO = re.compile(
    r"\bsame (?:here|boat|problem|issue|situation|question|thing|struggle)\b|\bme too\b|\bme as well\b|\bfollowing\b|"
    r"\balso (?:looking|interested|need|struggling|curious|searching|in the market)\b|\bin the same (?:boat|spot|situation|position)\b|"
    r"\bi(?:'d| would) (?:also )?(?:love|like) to know\b|\bcommenting to (?:follow|see|find)\b|\bremind ?me\b|^\+1\b|\bhaving the same\b|"
    r"\bwe have the same\b|\bbeen looking for (?:this|the same|something like)\b|\bi need this\b|\bcurious (?:too|as well)\b|"
    r"\bwould love (?:this|that|one)\b|\binterested (?:too|as well|in this)\b|\bwe struggle with (?:this|the same)\b|\bsaving this\b", re.I)
_NO_EXIST = re.compile(
    r"\b(?:doesn't|does not|don't think (?:it|that|one)) exist\b|\bnothing (?:like that|good|out there|exists)\b|"
    r"\bno (?:good|great|real|decent|perfect) (?:option|solution|tool|app|software|answer)s?\b|\b(?:haven't|have not|never) found (?:one|anything|a good)\b|"
    r"\bif you find (?:one|something|anything)\b|\blet me know (?:if|what) you find\b|\bbuilt (?:my|our) own\b|"
    r"\bended up (?:building|making|writing|using (?:excel|a spreadsheet|google sheets))\b|\bwe (?:just |still )?use (?:excel|a spreadsheet|spreadsheets|google sheets)\b", re.I)
_REC = re.compile(
    r"(?i:\b(?:use|using|used|try|tried|check out|look into|look at|looked at|recommend|suggest|love|like|switched to|moved to|went with|go with|"
    r"swear by|happy with|been on|signed up for|second|vouch for)\b) (?:(?i:the|a|an|our|their|out|with|by|into|at|for)\s+)?"
    r"((?:[A-Z][A-Za-z0-9.+]*|[a-z]+[A-Z][A-Za-z0-9]*)(?:[ -](?:[A-Z][A-Za-z0-9.+]*|[0-9]{1,4}))?)")
_MD_LINK = re.compile(r"\[([^\]]{2,40})\]\(https?://[^)\s]+\)")
_DOMAIN = re.compile(r"https?://(?:www\.|app\.)?([a-z0-9-]{3,30})\.(?:com|io|app|co|ai|net|org|so|dev|us|ca|uk)\b", re.I)
_VENDOR = re.compile(
    r"\b(?:i|we)(?:'ve| have)? (?:just |recently )?(?:built|made|created|developed|launched)\b|\bi(?:'m| am) (?:the|a) (?:founder|creator|developer|owner|ceo|co-?founder)\b|"
    r"\b(?:my|our) (?:app|tool|product|saas|platform|startup|company|software|team built)\b|\bdm me\b|\bshameless plug\b|\bfull disclosure\b|\bdisclaimer:? i\b|\bi work (?:for|at)\b", re.I)
_OBJECT = re.compile(
    r"\btoo (?:expensive|pricey|complicated|complex|much|clunky)\b|\bpricey\b|\boverkill\b|\bdoesn't (?:do|have|support|work|handle|integrate|let)\b|"
    r"\bdoes not (?:do|have|support|work|handle)\b|\b(?:i|we)(?:'ve| have)? (?:already )?tried (?:it|that|them|those|both)\b|\bnot (?:what|quite|really) (?:i|we)\b|"
    r"\balready (?:use|using|tried)\b|\bwon't work\b|\bno good\b|\bbut it (?:lacks|doesn't|can't|only)\b|\bonly (?:works|does|supports)\b|"
    r"\bstill (?:have to|need to|doesn't)\b|\bnone of (?:them|those|these)\b|\bhated it\b|\bcancel(?:l)?ed\b", re.I)
_OP_HAPPY = re.compile(
    r"\bthank(?:s| you)\b[^.!?\n]{0,60}\b(?:perfect|exactly|this is what|will (?:try|check|look|give)|great|awesome|helpful)\b|\bthat's (?:exactly|perfect)\b|"
    r"\bjust what i\b|\bsigned up\b|\bgoing (?:to go )?with\b|\bwill (?:check|try) (?:it|that|them|this) out\b|\bexactly what i (?:was looking for|needed)\b", re.I)
_NOT_TOOL = _NOT_PRODUCT | {"excel", "google sheets", "sheets", "google", "reddit", "youtube", "facebook", "linkedin", "amazon", "god", "ok", "yes",
                             "op", "edit", "eta", "lol", "imo", "fwiw", "tbh", "fyi", "diy", "pdf", "csv", "api", "llc", "cpa", "irs", "hipaa",
                             "github", "imgur", "wikipedia", "docs", "bit", "amzn", "discord", "twitter", "instagram", "tiktok"}

REPLY_LABEL = {
    "agree": "others say the same, no tool named", "open": "no tool suggested", "objections": "tools suggested, but not good enough",
    "one_tool": "one tool suggested", "solved": "likely solved already", "pitched": "only vendor pitches",
    "none": "no replies yet", "unread": "replies not read",
}
_UNMET_PTS = {"agree": 18, "objections": 16, "open": 12, "none": 8, "unread": 8, "pitched": 8, "one_tool": 6, "solved": 0}


def _tools_in(body):
    names = [m.group(1) for m in _REC.finditer(body)] + [m.group(1) for m in _MD_LINK.finditer(body)]
    names += [m.group(1).capitalize() for m in _DOMAIN.finditer(body)]
    first = body.strip().split("\n")[0].strip(" .!")
    if (2 < len(first) <= 30 and len(first.split()) <= 2 and len(body) < 50 and not _ME_TOO.search(first)
            and all(w[0].isupper() for w in first.split())):
        names.append(first)  # a reply that is just a product name
    out = []
    for n in names:
        n = n.strip(" .,-:!?")
        if len(n) >= 3 and n.lower() not in _NOT_TOOL and n.split()[0].lower() not in _NOT_TOOL and n.lower() not in [o.lower() for o in out]:
            out.append(n)
    return out


def reply_stats(it):
    """Turns it['replies_raw'] into it['replies']: how many agree, which tools were suggested, and a verdict."""
    raw = it.pop("replies_raw", None)
    total = it.get("n_replies") or (len(raw) if raw else 0)
    if raw is None or (not raw and total):
        it["replies"] = {"n": total, "read": 0, "status": "unread" if total else "none"}
        return it
    others = [r for r in raw if not r["op"]]
    op = [r for r in raw if r["op"]]
    me_too = sum(1 for r in others if _ME_TOO.search(r["b"]) or _NO_EXIST.search(r["b"]))
    tools, pitches = Counter(), 0
    for r in others:
        if _VENDOR.search(r["b"]):
            pitches += 1
            continue
        for t in _tools_in(r["b"]):
            tools[t] += 1
    objections = sum(1 for r in op if _OBJECT.search(r["b"])) * 2 + sum(1 for r in others if _OBJECT.search(r["b"]) and not _tools_in(r["b"]))
    happy = any(_OP_HAPPY.search(r["b"]) for r in op)
    if not raw:
        status = "none"
    elif tools:
        status = "solved" if happy else "objections" if objections >= 2 else "solved" if len(tools) >= 2 else "one_tool"
    elif pitches:
        status = "pitched"
    else:
        status = "agree" if me_too else "open"
    it["replies"] = {"n": max(total, len(raw)), "read": len(raw), "me_too": me_too, "tools": [t for t, _ in tools.most_common(5)],
                     "pitches": pitches, "objections": objections, "status": status}
    return it


# -------------------------------------------------------------- opportunity
# Not "how many people mention it" but "is there money behind it": who would pay, what it costs
# them now, whether anything already solves it, and how many are asking.
_PRICE = re.compile(r"[$£€]\s?\d[\d,]*(?:\.\d+)?\s?[kK]?(?:\s?(?:/|per|a|each)\s?(?:mo|month|yr|year|user|seat|location|licen[sc]e|week)\b)?")
_RECURRING = re.compile(r"(?:/|per|a|each)\s?(?:mo|month|yr|year|user|seat|location|licen[sc]e|week)\b", re.I)
_LOSS = re.compile(
    r"\blos(?:e|ing|t) (?:\w+ ){0,2}(?:money|customers|clients|revenue|sales|jobs|deals|leads|business)\b|"
    r"\bcost(?:s|ing)? (?:me|us) (?:\w+ ){0,3}(?:money|clients|customers|thousands|hundreds|[$£€])|\bfines?\b|\bpenalt(?:y|ies)\b|"
    r"\bchargebacks?\b|\bunbilled\b|\bmissed (?:billing|invoices|payments|deadlines?)\b|\bwrite-?offs?\b|\bmalpractice\b|\baudit(?:ed)?\b", re.I)
_HOURS = re.compile(r"\b(?:\d+|several|a few|a couple(?: of)?|many|countless|multiple)\+? (?:hours|hrs|days)\b(?: (?:a|per|every|each) (?:day|week|month))?", re.I)
_STAFF = re.compile(r"\b(?:my|our) (?:staff|team|employees|crew|crews|techs|technicians|admin|office manager|receptionist|bookkeeper|assistant|va|dispatcher|front desk)\b", re.I)
OPP_MAX = {"buyer": 25, "money": 20, "cost": 20, "unmet": 20, "demand": 15}


def opportunity(it):
    """0-100 for one lead, with the parts kept so the dashboard can show why."""
    full = f"{it['title']}\n{it['text']}"
    sig = set(it["signals"])
    money, anchors = 0, []
    if "pay" in sig:
        money += 8
        anchors.append("says they would pay")
    prices = [m.group(0).strip() for m in _PRICE.finditer(full)][:3]
    if prices:
        money += 5 + (2 if any(_RECURRING.search(x) for x in prices) else 0)
        anchors.append("prices mentioned: " + ", ".join(prices))
    if "too_expensive" in sig or "too_expensive" in it.get("complaints", []):
        money += 5
        anchors.append("current option is too expensive")
    if it["kind"] == "gig":
        usd = it.get("budget_usd") or 0
        money += 10 if usd >= 1000 else 7 if usd >= 250 else 4
        anchors.append(f"paying a freelancer ({it.get('budget') or 'budget not stated'})")
    if _LOSS.search(full):
        money += 6
        anchors.append("losing money or at risk of penalties")
    cost = min(12, 5 * len(sig & {"manual", "spreadsheet", "time_sink"}))
    hours = _HOURS.search(full)
    if hours:
        cost += 4
    if _STAFF.search(full):
        cost += 4
    rep = it.get("replies") or {"status": "none"}
    unmet = _UNMET_PTS.get(rep["status"], 8) + (4 if "nothing_fits" in sig else 0) + min(6, 2 * rep.get("me_too", 0))
    if rep["status"] == "solved":
        unmet = min(unmet, 4)
    parts = {
        "buyer": it.get("buyer_pts", 8),
        "money": min(20, money),
        "cost": min(20, cost),
        "unmet": min(20, unmet),
        "demand": min(15, round(3.2 * math.log1p(max(0, it.get("engagement", 0))))),
    }
    it["opp_parts"] = parts
    it["opp"] = min(100, sum(parts.values()) + (5 if it.get("events") else 0))
    if anchors:
        it["money_notes"] = anchors[:3]
    if hours:
        it["time_note"] = hours.group(0)
    return it


def problem_stats(p, members, weeks_seen=1):
    """Opportunity for a group of leads: the strongest evidence, plus how widely and how long it has been voiced."""
    members = sorted(members, key=lambda m: -m.get("opp", 0))
    top = members[:3]
    avg = lambda k: round(sum(m["opp_parts"][k] for m in top) / len(top))  # noqa: E731
    authors = {m.get("author") or m["id"] for m in members}
    sources = sorted({m["source"] for m in members})
    demand = min(12, round(4 * math.log2(1 + len(authors)))) + min(6, 3 * (len(sources) - 1)) + min(12, 3 * (weeks_seen - 1))
    parts = {"buyer": avg("buyer"), "money": avg("money"), "cost": avg("cost"), "unmet": avg("unmet"), "demand": min(30, demand)}
    base = sum(m["opp"] for m in top) / len(top)
    p["opp"] = min(100, round(0.7 * base + demand))
    p["opp_parts"] = parts
    p["segment"] = Counter(m["segment"] for m in members).most_common(1)[0][0]
    p["sources"] = sources
    p["people"] = len(authors)
    p["score"] = round(sum(m["pain_score"] for m in members), 1)
    statuses = Counter((m.get("replies") or {}).get("status", "none") for m in members)
    tools = Counter(t for m in members for t in (m.get("replies") or {}).get("tools", []))
    p["replies"] = {
        "me_too": sum((m.get("replies") or {}).get("me_too", 0) for m in members),
        "tools": [t for t, _ in tools.most_common(6)],
        "statuses": dict(statuses),
        "unmet": sum(statuses[k] for k in ("agree", "objections", "open")),
        "solved": statuses["solved"],
    }
    notes = [n for m in members for n in m.get("money_notes", [])]
    if notes:
        p["money_notes"] = list(dict.fromkeys(notes))[:3]
    return p


def rank_problems(problems):
    """Best opportunity first; catch-all buckets sink."""
    problems.sort(key=lambda c: -(c.get("opp", 0) * (0.6 if c.get("niche") == GENERAL else 1) * (0.7 if c.get("theme") == OTHER else 1)))
    return problems


# ----------------------------------------------------------- forced changes
# A product shutting down, raising prices, being bought or going down pushes all its users to look
# for something else at the same moment. So does a new rule with a deadline.
_EVP = r"((?:[A-Z][A-Za-z0-9.+]*|[a-z]+[A-Z][A-Za-z0-9]*|[A-Z0-9]{2,})(?:[ -](?:[A-Z][A-Za-z0-9.+]*|[0-9]{1,4}))?)"
_EVENT_RX = [
    ("shutdown", re.compile(_EVP + r"(?:'s)? (?i:(?:is |are |was |has been |will be |just |recently |now |officially )*(?:shutting down|shut down|sunsetting|"
                                   r"sunset(?:ted)?|discontinu\w+|being retired|retiring|end(?:ing)? of life|going away|closing down|no longer (?:supported|available|maintained)))")),
    ("shutdown", re.compile(r"(?i:shutdown|shut-down|sunset(?:ting)?|discontinuation|end of life|retirement|demise) of " + _EVP)),
    ("price_increase", re.compile(_EVP + r"(?:'s)? (?i:(?:is |are |just |recently |has |have |now )*(?:rais(?:ing|ed)|increas(?:ing|ed)|doubl(?:ing|ed)|tripl(?:ing|ed)|hik(?:ing|ed)) "
                                         r"(?:its |their |the |our |my )?(?:prices?|pricing|rates?|fees?|subscription))")),
    ("price_increase", re.compile(_EVP + r"(?:'s)? (?i:(?:new )?(?:price|pricing|fee|rate) (?:increase|hike|jump))")),
    ("acquisition", re.compile(_EVP + r" (?i:(?:was |has been |got |just |is being |being )+(?:acquired|bought|purchased|taken over) by)")),
    ("outage", re.compile(_EVP + r"(?:'s)? (?i:(?:is |was |has been |went |keeps going )?(?:outage|down again|is down|was down|went down|been down for))")),
]
_REGULATION = re.compile(
    r"\bnew (?:\w+ ){0,3}(?:regulations?|rules?|laws?|requirements?|mandate|legislation|reporting requirements?)\b|"
    r"\b(?:regulations?|rules?|law|mandate|requirements?) (?:that )?(?:takes?|taking|goes?|going|comes?|coming|went|came) (?:into )?effect\b|\bcompliance deadline\b|"
    r"\b(?:are now|is now|will be|will soon be) required to\b|\bmandatory (?:as of|from|starting|by)\b|"
    r"\beffective (?:january|february|march|april|may|june|july|august|september|october|november|december) \d", re.I)
_NOT_EVENT = _NOT_TOOL | {"server", "internet", "power", "site", "website", "system", "company", "store", "app", "account", "everything", "nothing",
                           "business", "service", "email", "phone", "wifi", "network", "support", "market", "economy", "government", "school", "office",
                           "who", "which", "since", "after", "when", "now", "also", "just", "then", "because", "while", "sales", "revenue", "traffic",
                           "prices", "costs", "rent", "wages", "demand", "work", "today", "yesterday", "last", "next"}
EVENT_LABEL = {"shutdown": "Shutting down", "price_increase": "Price increase", "acquisition": "Acquired", "outage": "Outage", "regulation": "New rule"}


def events_for(title, text, hint=None):
    """Forced changes mentioned in a post: [(type, subject)]."""
    full = f"{title}\n{text}"
    out = []
    for kind, rx in _EVENT_RX:
        for m in rx.finditer(full):
            name = m.group(1).strip(" .,-'")
            if name.endswith("'s"):
                name = name[:-2]
            if len(name) >= 3 and name.lower() not in _NOT_EVENT and name.split()[0].lower() not in _NOT_EVENT and (kind, name) not in out:
                out.append((kind, name))
    if hint and hint not in CONSUMER_NICHES:
        for sent in _sentences(title, text):
            if _REGULATION.search(sent):
                out.append(("regulation", short(sent, 160)))
                break
    return out[:4]
