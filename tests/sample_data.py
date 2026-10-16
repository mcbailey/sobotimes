"""Fictional sample data used by the tests and the design preview.

None of this describes real meetings. Video ids are made up.
"""
from __future__ import annotations

VIDEOS = [
    {
        "id": "sampleSB1013",
        "title": "Select Board Meeting 10/13/2026",
        "description": "Recorded live at the Town House Hearing Room.",
        "published_at": "2026-10-13T14:30:00Z",
        "duration_s": 7800,
        "live": "none",
    },
    {
        "id": "sampleSC1008",
        "title": "School Committee Meeting October 8, 2026",
        "description": "",
        "published_at": "2026-10-10T14:00:00Z",
        "duration_s": 7500,
        "live": "none",
    },
    {
        "id": "samplePB1007",
        "title": "Planning Board 10-7-26",
        "description": "",
        "published_at": "2026-10-09T15:30:00Z",
        "duration_s": 6720,
        "live": "none",
    },
    {
        "id": "sampleSB1006",
        "title": "Select Board Meeting 10/6/2026",
        "description": "Agenda: FY28 budget guidance, Neary feasibility study update, sidewalk bid award.",
        "published_at": "2026-10-08T13:00:00Z",
        "duration_s": 9660,
        "live": "none",
    },
    {
        "id": "sampleHF2026",
        "title": "Southborough Harvest Fair 2026 Highlights",
        "description": "",
        "published_at": "2026-10-05T18:00:00Z",
        "duration_s": 1500,
        "live": "none",
    },
    {
        "id": "sampleBH0930",
        "title": "Board of Health Meeting 9/30/2026 (full day workshop)",
        "description": "",
        "published_at": "2026-10-02T12:00:00Z",
        "duration_s": 6 * 3600,
        "live": "none",
    },
    {
        "id": "sampleZB1001",
        "title": "Zoning Board of Appeals 10/1/2026",
        "description": "",
        "published_at": "2026-10-03T12:00:00Z",
        "duration_s": 5400,
        "live": "none",
    },
    {
        "id": "sampleCC1001",
        "title": "Conservation Commission Meeting 10/1/2026",
        "description": "",
        "published_at": "2026-10-03T11:00:00Z",
        "duration_s": 3300,
        "live": "none",
    },
    {
        "id": "sampleSB0929",
        "title": "Select Board Meeting 9/29/2026",
        "description": "",
        "published_at": "2026-10-01T13:00:00Z",
        "duration_s": 8400,
        "live": "none",
    },
]


def _ts(seconds):
    """Model output uses H:MM:SS strings, as the schema asks."""
    h, rem = divmod(seconds, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}"


def _t(title, category, importance, start, summary, details=(), outcome=None, why=None, end=None):
    return {
        "title": title,
        "category": category,
        "importance": importance,
        "summary": summary,
        "key_details": list(details),
        "outcome": outcome,
        "why_it_matters": why,
        "start": _ts(start),
    }


SUMMARIES = {
    "sampleSB1006": {
        "is_public_meeting": True,
        "body": "Select Board",
        "meeting_date": "2026-10-06",
        "headline": "The board told departments to hold next year's budget increases to 2.5 percent while it weighs whether school building costs will require an override.",
        "summary": "The Select Board issued budget guidance for fiscal 2028, heard an update on the Neary School feasibility study, and awarded a contract to rebuild sidewalks on Route 85. Members disagreed about whether to signal an override this early, and the guidance passed 4-1. The board also reviewed the cemetery expansion committee's first report.",
        "topics": [
            _t("Routine business", "Town administration", "low", 95, "The board approved minutes from September 22 and accepted a $500 gift to the library.", outcome="Approved unanimously."),
            _t("FY28 budget guidance", "Budget & taxes", "high", 540,
               "The town administrator proposed asking every department to hold fiscal 2028 increases to 2.5 percent. Two members argued the guidance should acknowledge that school building costs may push the town toward an operational override.",
               ["Guidance caps department increases at 2.5 percent", "Projected gap of about $1.1 million before any cuts", "Override question deferred until the feasibility study cost estimate arrives in January"],
               outcome="Guidance adopted 4-1.",
               why="Sets the starting point for next year's tax bills and department services.", end=2700),
            _t("Neary School feasibility study update", "Schools", "high", 2760,
               "The project consultant presented three options: renovate, add on, or build new on the current site. Cost estimates are not ready, but the consultant said the new-construction option would likely need a debt exclusion vote.",
               ["Three options still under study", "Cost estimates due in January", "Community forum planned for November 12"],
               outcome="No vote; update only.",
               why="Whichever option is chosen will shape school capacity and tax bills for decades.", end=4800),
            _t("Route 85 sidewalk reconstruction contract", "Roads & infrastructure", "high", 4860,
               "The public works director recommended the low bidder for rebuilding about 1.2 miles of sidewalk along Route 85, paid for from Chapter 90 state funds and free cash approved at spring Town Meeting.",
               ["Low bid: $412,000 from a regional contractor", "Work starts in April and finishes by August", "Some evening lane closures expected"],
               outcome="Contract awarded 5-0.", end=5900),
            _t("Cemetery expansion committee report", "Town administration", "medium", 6000,
               "The committee reported that the cemetery will run out of plots in about six years and listed two town-owned parcels for possible expansion.",
               ["About 6 years of plots remain", "Two candidate parcels under review"], outcome="Committee will return with a recommendation in the spring.", end=7300),
            _t("Public comment", "Other", "medium", 7350,
               "Three residents spoke. Two raised traffic safety near the Neary School during drop-off, and one asked the board to keep the override discussion public.", end=8100),
        ],
        "votes": [
            {"motion": "Adopt FY28 budget guidance capping department increases at 2.5 percent", "result": "passed", "tally": "4-1", "time": "0:43:30"},
            {"motion": "Award the Route 85 sidewalk reconstruction contract ($412,000)", "result": "passed", "tally": "5-0", "time": "1:37:20"},
        ],
        "public_comment": [
            {"summary": "A resident of Parkerville Road asked for a crossing guard at the Neary School entrance.", "time": "2:03:20"},
            {"summary": "A resident urged the board to hold override discussions in open session, not subcommittee.", "time": "2:10:20"},
        ],
        "upcoming": [
            {"what": "Warrant closes for the November Special Town Meeting", "when": "October 20"},
            {"what": "Neary School community forum", "when": "November 12"},
        ],
        "caveats": None,
    },
    "samplePB1007": {
        "is_public_meeting": True,
        "body": "Planning Board",
        "meeting_date": "2026-10-07",
        "headline": "Hearing on a 24-unit housing proposal for Turnpike Road was continued to October 21 after abutters raised drainage concerns.",
        "summary": "The Planning Board opened its site plan review of a proposed 24-unit residential project on Turnpike Road and continued it after residents and the town engineer questioned the stormwater design. Members also discussed a first draft of an accessory dwelling unit bylaw intended for spring Town Meeting.",
        "topics": [
            _t("Turnpike Road 24-unit residential site plan", "Development & zoning", "high", 300,
               "The developer presented plans for 24 townhouse-style units with 52 parking spaces. The town engineer asked for revised stormwater calculations, and several abutters described flooding in their back yards after heavy rain.",
               ["24 units on about 4.5 acres", "6 units designated affordable", "Peer review of drainage requested at the developer's expense"],
               outcome="Hearing continued to October 21.",
               why="The project would be one of the larger housing developments in town in recent years.", end=3900),
            _t("Accessory dwelling unit bylaw draft", "Development & zoning", "high", 3960,
               "Members reviewed a draft bylaw aligning town rules with the state law allowing accessory apartments by right. Debate focused on parking requirements and whether to cap unit size at 900 square feet.",
               ["Draft caps units at 900 square feet", "One parking space per unit proposed", "Public hearing targeted for February"],
               outcome="Staff will revise the draft for the November 4 meeting.", end=6000),
            _t("Routine business", "Town administration", "low", 6050, "The board approved minutes and signed a lot release for a completed subdivision.", outcome="Approved."),
        ],
        "votes": [{"motion": "Continue the Turnpike Road site plan hearing to October 21", "result": "continued", "tally": "5-0", "time": "1:04:10"}],
        "public_comment": [{"summary": "Abutters on a neighboring street described standing water after storms and asked for an independent drainage review.", "time": "0:40:00"}],
        "upcoming": [{"what": "Turnpike Road hearing continues", "when": "October 21"}, {"what": "Revised ADU bylaw draft", "when": "November 4"}],
        "caveats": "Audio drops out for about two minutes near 1:10:00.",
    },
    "sampleSC1008": {
        "is_public_meeting": True,
        "body": "School Committee",
        "meeting_date": "2026-10-08",
        "headline": "The Trottier School roof replacement is on schedule and under budget, and the committee set its calendar for building the FY28 school budget.",
        "summary": "The committee heard that the Trottier roof project should finish before Thanksgiving, reviewed spring MCAS results, and adopted a budget calendar that ends with a public hearing in February.",
        "topics": [
            _t("Trottier School roof replacement", "Schools", "medium", 420,
               "The facilities director said the roof replacement is about 80 percent complete and tracking $60,000 under its $2.3 million budget.",
               ["About 80 percent complete", "Expected completion before Thanksgiving"], end=1900),
            _t("FY28 school budget calendar", "Budget & taxes", "high", 1950,
               "The superintendent outlined the budget process and warned that special education tuition costs are rising faster than the town's 2.5 percent guidance.",
               ["Budget public hearing in February", "Special education tuition up about 9 percent"],
               outcome="Calendar adopted 5-0.", why="Signals a likely gap between school needs and the Select Board's budget guidance.", end=4100),
            _t("Spring MCAS results", "Schools", "medium", 4150,
               "Scores held steady in English and rose slightly in math in grades 3 through 6.", end=6400),
            _t("Routine business", "Town administration", "low", 6450, "The committee accepted donations and approved a field trip."),
        ],
        "votes": [{"motion": "Adopt the FY28 budget calendar", "result": "passed", "tally": "5-0", "time": "1:07:30"}],
        "public_comment": [],
        "upcoming": [{"what": "School budget public hearing", "when": "February"}],
        "caveats": None,
    },
    "sampleSB0929": {
        "is_public_meeting": True,
        "body": "Select Board",
        "meeting_date": "2026-09-29",
        "headline": "The police chief asked for two additional officers, citing overtime costs that have doubled in three years.",
        "summary": "The board heard a staffing request from the police department and reviewed a draft master plan for Fayville Park. No votes were taken on either item.",
        "topics": [
            _t("Police staffing request", "Public safety", "high", 600,
               "The chief requested two new officer positions, saying overtime spending has doubled since 2023 and shifts are often staffed at minimum levels.",
               ["Overtime about $480,000 last year", "Two positions would cost about $210,000 a year with benefits"],
               outcome="Request referred to the FY28 budget process.", why="Would add to next year's budget pressure.", end=3600),
            _t("Fayville Park master plan draft", "Parks, recreation & open space", "medium", 3700,
               "The recreation commission presented a draft plan with a new playground, walking loop and improved parking, to be built in phases.",
               ["Phase one estimated at $650,000", "Community survey closes October 15"], end=6300),
            _t("Routine business", "Town administration", "low", 6400, "Approved one-day liquor licenses for two community events."),
        ],
        "votes": [],
        "public_comment": [],
        "upcoming": [{"what": "Fayville Park survey closes", "when": "October 15"}],
        "caveats": None,
    },
    "sampleZB1001": {
        "is_public_meeting": True,
        "body": "Zoning Board of Appeals",
        "meeting_date": "2026-10-01",
        "headline": "The board continued the comprehensive permit hearing for a proposed 40B apartment project to allow traffic peer review.",
        "summary": "The Zoning Board of Appeals heard updated plans for a 40B apartment project and continued the hearing so a traffic consultant can review the developer's study.",
        "topics": [
            _t("40B apartment project hearing", "Development & zoning", "high", 240,
               "The developer reduced the project from 120 to 108 units and moved the driveway farther from the intersection. Board members said they need the traffic peer review before discussing conditions.",
               ["Reduced from 120 to 108 units", "27 units affordable", "Traffic peer review expected by late October"],
               outcome="Hearing continued to October 29.", why="Under the state 40B law the town's ability to deny the project is limited, so conditions set here matter.", end=4800),
        ],
        "votes": [{"motion": "Continue the hearing to October 29", "result": "continued", "tally": "5-0", "time": "1:19:10"}],
        "public_comment": [],
        "upcoming": [{"what": "40B hearing continues", "when": "October 29"}],
        "caveats": None,
    },
    "sampleCC1001": {
        "is_public_meeting": True,
        "body": "Conservation Commission",
        "meeting_date": "2026-10-01",
        "headline": "Approved a wetlands permit to replace a failing culvert on a town road.",
        "summary": "The commission issued an order of conditions for a culvert replacement and reviewed two small residential projects near wetlands.",
        "topics": [
            _t("Culvert replacement order of conditions", "Environment & conservation", "medium", 300,
               "Public works will replace an undersized culvert with a larger box culvert that meets state stream-crossing standards.",
               ["Work window July to September 2027"], outcome="Approved 6-0.", end=1500),
            _t("Residential projects near wetlands", "Environment & conservation", "low", 1550, "Two homeowners received approvals for a deck and a shed within the wetland buffer."),
        ],
        "votes": [{"motion": "Issue order of conditions for the culvert replacement", "result": "passed", "tally": "6-0", "time": "0:24:10"}],
        "public_comment": [],
        "upcoming": [],
        "caveats": None,
    },
}

WEEKS = {
    "2026-10-05": {
        "synopsis": "The Select Board set guidance for next year's budget, asking departments to hold increases to 2.5 percent while the town weighs whether school building costs will require an override. The School Committee warned that special education costs are already rising faster than that. The board also awarded a $412,000 contract to rebuild sidewalks along Route 85. At the Planning Board, a 24-unit housing proposal on Turnpike Road was continued to October 21 over drainage concerns, and work began on an accessory apartment bylaw for spring Town Meeting.",
        "highlights": [
            {"title": "FY28 budget guidance adopted", "why": "Departments are asked to hold increases to 2.5 percent; the town projects a gap of about $1.1 million, and an override decision waits on school building costs in January.", "body": "Select Board", "importance": "high", "video_id": "sampleSB1006", "start": "0:09:00"},
            {"title": "Turnpike Road housing hearing continued", "why": "Abutters and the town engineer questioned drainage for the 24-unit plan; the hearing resumes October 21.", "body": "Planning Board", "importance": "high", "video_id": "samplePB1007", "start": "0:05:00"},
            {"title": "School costs outpacing budget guidance", "why": "Special education tuition is up about 9 percent, well above the 2.5 percent guidance.", "body": "School Committee", "importance": "high", "video_id": "sampleSC1008", "start": "0:32:30"},
            {"title": "Route 85 sidewalks to be rebuilt", "why": "A $412,000 contract was awarded; work runs April through August with some evening lane closures.", "body": "Select Board", "importance": "medium", "video_id": "sampleSB1006", "start": "1:21:00"},
        ],
        "looking_ahead": [
            {"what": "Warrant closes for the November Special Town Meeting", "when": "October 20", "body": "Select Board"},
            {"what": "Turnpike Road housing hearing continues", "when": "October 21", "body": "Planning Board"},
            {"what": "Neary School community forum", "when": "November 12", "body": None},
        ],
    },
    "2026-09-28": {
        "synopsis": "Public safety and housing led the week. The police chief asked for two more officers, citing overtime costs that have doubled since 2023, and the request now goes into next year's budget talks. The Zoning Board of Appeals continued its hearing on a 40B apartment project, now 108 units, until a traffic review is complete. The Select Board also saw a phased plan for Fayville Park, with a resident survey open through October 15.",
        "highlights": [
            {"title": "Police request two more officers", "why": "Overtime reached about $480,000 last year; the positions would add about $210,000 a year.", "body": "Select Board", "importance": "high", "video_id": "sampleSB0929", "start": "0:10:00"},
            {"title": "40B apartment project scaled back", "why": "The developer cut the plan to 108 units and moved the driveway; the hearing resumes October 29 after traffic peer review.", "body": "Zoning Board of Appeals", "importance": "high", "video_id": "sampleZB1001", "start": "0:04:00"},
            {"title": "Fayville Park master plan", "why": "Phase one is estimated at $650,000; the community survey closes October 15.", "body": "Select Board", "importance": "medium", "video_id": "sampleSB0929", "start": "1:01:40"},
        ],
        "looking_ahead": [
            {"what": "Fayville Park survey closes", "when": "October 15", "body": "Recreation Commission"},
            {"what": "40B hearing continues", "when": "October 29", "body": "Zoning Board of Appeals"},
        ],
    },
}


# Issues the fake links call assigns, by a phrase in the topic's title or
# upcoming item: id -> (name, category, description, phrases).
ISSUES = {
    "fy28-budget": ("FY28 town budget", "Budget & taxes",
                    "Next year's operating budget, including school costs and a possible override.", ["FY28"]),
    "neary-school-project": ("Neary School building project", "Schools",
                             "Whether to renovate or replace the Neary Elementary School.", ["Neary"]),
    "turnpike-road-housing": ("Turnpike Road 24-unit housing", "Housing",
                              "A proposed 24-unit residential development on Turnpike Road.", ["Turnpike Road"]),
    "adu-bylaw": ("Accessory apartment bylaw", "Zoning & development",
                  "A zoning bylaw to allow accessory dwelling units.", ["ADU", "Accessory dwelling"]),
    "40b-apartments": ("40B apartment project", "Housing",
                       "A comprehensive permit for a 108-unit apartment project.", ["40B"]),
    "fayville-park": ("Fayville Park master plan", "Parks, trails & recreation",
                      "A phased plan to rebuild Fayville Park.", ["Fayville"]),
    "route-85-sidewalks": ("Route 85 sidewalks", "Roads, water & infrastructure",
                           "Rebuilding the sidewalks along Route 85.", ["Route 85"]),
}
_CATEGORY_WORDS = {"Routine": "Governance & committees", "MCAS": "Schools", "roof": "Buildings & facilities",
                   "Police": "Public safety", "Culvert": "Roads, water & infrastructure", "wetlands": "Environment & conservation",
                   "Cemetery": "Governance & committees", "Public comment": "Other", "Town Meeting": "Town Meeting & elections"}


def _section(text, start, end):
    return text.split(start, 1)[1].split(end, 1)[0]


def _issue_for(text):
    for iid, (_, _, _, phrases) in ISSUES.items():
        if any(ph.lower() in (text or "").lower() for ph in phrases):
            return iid
    return None


def fake_links(prompt: str) -> dict:
    """What a careful links call would return for the sample meetings."""
    import json
    from datetime import date
    from digest.timeutil import resolve_when

    tracked = {i["id"] for i in json.loads(_section(prompt, "Issues already tracked (JSON):\n", "\n\nThis week's")
                                             .replace(" (none yet)", ""))}
    meetings = json.loads(_section(prompt, "by their ref:\n", "\n\nReturn JSON"))
    out = {"new_issues": [], "topics": [], "votes": [], "upcoming": [], "statuses": []}
    used = {}
    for m in meetings:
        ref_date = date.fromisoformat(m["meeting_date"])
        for t in m["topics"]:
            iid = _issue_for(t["title"])
            cat = ISSUES[iid][1] if iid else next(
                (c for w, c in _CATEGORY_WORDS.items() if w.lower() in t["title"].lower()), "Other")
            out["topics"].append({"ref": t["ref"], "issue": iid, "category": cat})
            if iid:
                used[iid] = t.get("outcome") or t["title"]
        for x in m.get("votes", []):
            out["votes"].append({"ref": x["ref"], "issue": _issue_for(x["motion"] or "")})
        for u in m["upcoming"]:
            d = resolve_when(u["when"], ref_date)
            out["upcoming"].append({"ref": u["ref"], "date": d.isoformat() if d else None, "issue": _issue_for(u["what"])})
    for iid, latest in used.items():
        if iid not in tracked:
            name, cat, desc, _ = ISSUES[iid]
            out["new_issues"].append({"id": iid, "name": name, "description": desc, "category": cat})
        out["statuses"].append({"issue": iid, "status": latest})
    return out


def fake_issue_status(prompt: str) -> dict:
    """A status built from the record: every board that discussed it gets a position."""
    import json
    record = json.loads(prompt.split("Record (JSON):\n", 1)[1].split("\n\nReturn JSON", 1)[0])
    boards = [b["board"] for b in record["by_board"]]
    last = record["by_board"][0]["latest"][0] if record["by_board"] else {}
    return {
        "status": last.get("outcome") or last.get("summary") or "Under discussion.",
        "positions": [{"body": b, "stance": "undecided", "detail": "Discussed it."} for b in boards],
        "next": "",
        "significance": 4 if "budget" in prompt.lower() else 2,
    }


def fake_month(prompt: str) -> dict:
    import json
    meetings = json.loads(prompt.split("Meetings:\n", 1)[1].split("\n\nReturn JSON", 1)[0])
    items = [
        {"title": t["title"], "why": t.get("outcome") or t["summary"], "body": m["body"], "importance": "high",
         "issue": t.get("issue"), "video_id": m["video_id"], "start": t["start"]}
        for m in meetings for t in m["topics"] if t["importance"] == "high"
    ]
    return {"headline": "Budget pressure and housing proposals dominated the month.",
            "synopsis": "Boards set budget guidance and weighed two housing projects. More hearings are scheduled.",
            "top_items": items}
