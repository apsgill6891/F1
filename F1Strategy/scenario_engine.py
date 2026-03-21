"""
Scenario Engine
Generates strategic recommendations for key race events:
  - Safety Car (SC) deployment by lap window
  - Virtual Safety Car (VSC) deployment
  - Red Flag
  - Rival boxes first (undercut threat)
  - VSC vs SC distinction (critical: ~8-10s benefit vs ~25s)

Each scenario returns:
  - recommended action
  - alternative actions
  - risk rating (LOW / MEDIUM / HIGH)
  - historical precedent summary
"""

from dataclasses import dataclass, field


@dataclass
class ScenarioInput:
    circuit: str
    team: str
    driver: str
    current_lap: int
    total_laps: int
    current_position: int
    current_compound: str       # SOFT / MEDIUM / HARD
    tyre_age_laps: int
    pit_delta_seconds: float    # pit lane loss time for this circuit
    gap_ahead_seconds: float    # gap to car in front
    gap_behind_seconds: float   # gap to car behind
    championship_position: int  # affects risk tolerance
    championship_gap_points: int
    weather_condition: str      # DRY / WET / MIXED
    sc_events_this_race: list = field(default_factory=list)  # SC events already in this race
    starting_compound: str = "MEDIUM"


@dataclass
class Recommendation:
    action: str
    rationale: str
    alternatives: list[str]
    risk: str  # LOW / MEDIUM / HIGH
    historical_note: str


# ── Compound logic helpers ────────────────────────────────────────────────────

COMPOUND_ORDER = ["SOFT", "MEDIUM", "HARD", "INTERMEDIATE", "WET"]

def _next_compound(current: str, weather: str = "DRY") -> str:
    if weather in ("WET", "MIXED"):
        return "INTERMEDIATE" if current not in ("INTERMEDIATE", "WET") else "WET"
    order = ["SOFT", "MEDIUM", "HARD"]
    idx = order.index(current) if current in order else 1
    return order[min(idx + 1, len(order) - 1)]

def _optimal_compound(tyre_age: int, remaining_laps: int, weather: str, temp_c: float = 25) -> str:
    if weather in ("WET",):
        return "WET"
    if weather in ("MIXED",):
        return "INTERMEDIATE"
    if remaining_laps <= 15:
        return "SOFT"
    if remaining_laps <= 30 or temp_c > 33:
        return "MEDIUM"
    return "HARD"


# ── SC vs VSC benefit calculator ─────────────────────────────────────────────

def pit_benefit(sc_type: str, pit_delta: float) -> float:
    """
    Returns approximate net time benefit of pitting under a safety car event.
    SC: cars bunch up, effective pit cost ~pit_delta - ~20s = net benefit
    VSC: cars slow to ~40% pace, effective saving ~8-12s depending on circuit
    """
    if sc_type == "SC":
        return max(pit_delta - 20.0, 0)   # typical field bunching saves ~20s
    elif sc_type == "VSC":
        return max(pit_delta - 10.0, 0)   # VSC saves less: ~10s pace reduction
    return pit_delta  # green flag — full cost


# ── Individual scenario functions ─────────────────────────────────────────────

def safety_car_scenario(inp: ScenarioInput, sc_type: str = "SC") -> Recommendation:
    """SC or VSC deployed. Should we box?"""
    remaining = inp.total_laps - inp.current_lap
    benefit = pit_benefit(sc_type, inp.pit_delta_seconds)
    window_label = (
        "early" if inp.current_lap <= inp.total_laps // 3
        else "mid" if inp.current_lap <= inp.total_laps * 2 // 3
        else "late"
    )

    already_stopped = len(inp.sc_events_this_race)
    needs_stop = inp.tyre_age_laps > 15 or remaining > 20
    benefit_positive = benefit > 5.0

    # Tyre still has life and we're early — can go long
    if not needs_stop and window_label == "early":
        action = "STAY OUT — tyres still fresh, extend the stint"
        rationale = (
            f"Tyre age only {inp.tyre_age_laps} laps on {inp.current_compound}. "
            f"{sc_type} benefit is {benefit:.1f}s, not worth burning a stop early. "
            f"Aim for a longer first stint."
        )
        alternatives = [
            "BOX if rival ahead pits (covers undercut threat)",
            "WAIT one lap to assess if SC period extends",
        ]
        risk = "LOW"
        hist = "Staying out under early SC has historically set up undercut opportunities later."

    # Clear benefit and we need the stop
    elif benefit_positive and needs_stop:
        target_compound = _optimal_compound(inp.tyre_age_laps, remaining, inp.weather_condition)
        action = f"BOX NOW — fit {target_compound}"
        rationale = (
            f"{sc_type} gives ~{benefit:.1f}s effective saving vs green-flag pit. "
            f"With {remaining} laps remaining on aged {inp.current_compound} "
            f"({inp.tyre_age_laps} laps old), this is a free stop."
        )
        alternatives = [
            f"STAY OUT if you're in P{inp.current_position} with clean air and want to extend",
            "WAIT one lap if safety car end timing is unclear",
        ]
        risk = "LOW" if sc_type == "SC" else "MEDIUM"
        hist = (
            "At Suzuka, teams that box under SC in mid-race typically gain 2-4 positions "
            "through the pit cycle. VSC benefit is smaller (~8s) — calculate carefully."
        )

    # VSC — marginal benefit, position-dependent
    elif sc_type == "VSC" and benefit < 8.0:
        action = "STAY OUT — VSC benefit too small to justify stop"
        rationale = (
            f"VSC saves only ~{benefit:.1f}s vs pit delta of {inp.pit_delta_seconds}s. "
            f"Net benefit marginal. Position loss risk outweighs gain."
        )
        alternatives = [
            "BOX only if tyres are critically degraded (>30 laps on compound)",
            "BOX if rival behind is threatening and you need track position swap",
        ]
        risk = "MEDIUM"
        hist = "VSC is often overvalued by teams. Half of VSC pit stops lose net track position."

    # Late race — depends on championship
    else:
        action = "STAY OUT — protect track position in final stint"
        rationale = (
            f"Only {remaining} laps left. Pitting risks losing P{inp.current_position}. "
            f"Manage tyre to the flag unless critical failure risk."
        )
        alternatives = [
            "BOX if championship gap allows risk (fighting for title = stay out; mid-field = gamble)",
            "BOX if rain is imminent to switch to Intermediates",
        ]
        risk = "HIGH"
        hist = "Late SC pits only pay off when you're outside points and have nothing to lose."

    return Recommendation(action=action, rationale=rationale, alternatives=alternatives,
                          risk=risk, historical_note=hist)


def red_flag_scenario(inp: ScenarioInput) -> Recommendation:
    """Red flag — free tyre change opportunity."""
    remaining = inp.total_laps - inp.current_lap
    target = _optimal_compound(0, remaining, inp.weather_condition)

    action = f"USE FREE TYRE CHANGE — fit {target}"
    rationale = (
        f"Red flag gives a FREE tyre change — always use it. "
        f"With {remaining} laps remaining, {target} is optimal. "
        f"Current gap advantage is reset; focus on restart execution."
    )
    alternatives = [
        "If wet, fit INTERMEDIATE regardless of target",
        "Consider SOFT if remaining laps <15 and dry — attack mode",
    ]
    risk = "LOW"
    hist = (
        "Red flags reset gaps. Teams that switch to the right compound here gain 1-3 positions "
        "on average. Never waste a free tyre change — the only debate is WHICH tyre, not WHETHER."
    )
    return Recommendation(action=action, rationale=rationale, alternatives=alternatives,
                          risk=risk, historical_note=hist)


def undercut_threat_scenario(inp: ScenarioInput) -> Recommendation:
    """Rival behind us just pitted — undercut threat."""
    remaining = inp.total_laps - inp.current_lap
    gap = inp.gap_behind_seconds
    pit_cost = inp.pit_delta_seconds
    net_threat = pit_cost - gap  # positive = rival emerges ahead of us after pit

    if net_threat < -5:
        action = "STAY OUT — gap too large, undercut won't work against you"
        rationale = (
            f"Rival needs to make up {gap:.1f}s in {remaining} laps after pitting. "
            f"With {pit_cost:.1f}s pit loss, they emerge {abs(net_threat):.1f}s behind. Safe."
        )
        alternatives = ["Plan your own stop for the next 3-5 laps optimally"]
        risk = "LOW"
        hist = "Undercuts at Suzuka require <12s gap to be effective due to long pit lane."

    elif net_threat < 5:
        action = "REACT — box next lap to cover the undercut"
        rationale = (
            f"Gap is {gap:.1f}s — rival on fresh tyres could close this. "
            f"Cover by pitting next lap. You hold track position advantage."
        )
        alternatives = [
            "STAY OUT if tyre pace is strong — trade undercut for overcut",
            "PUSH hard for 2 laps to extend gap before pitting",
        ]
        risk = "MEDIUM"
        hist = "Reactive undercut covers are successful ~70% of the time when executed within 2 laps."

    else:
        action = "BOX IMMEDIATELY — undercut threat is real"
        rationale = (
            f"Gap of only {gap:.1f}s means rival on fresh tyres WILL emerge ahead after their pit. "
            f"Box this lap to cover."
        )
        alternatives = [
            "PUSH 1 lap max if you're approaching a natural tyre cliff for best of both",
        ]
        risk = "HIGH"
        hist = "At Suzuka, gaps under 10s rarely survive an undercut attempt with fresh softs."

    return Recommendation(action=action, rationale=rationale, alternatives=alternatives,
                          risk=risk, historical_note=hist)


def overcut_scenario(inp: ScenarioInput) -> Recommendation:
    """We stay out while rivals pit — can we make overcut work?"""
    remaining = inp.total_laps - inp.current_lap
    gap_to_rival = inp.gap_ahead_seconds

    if inp.tyre_age_laps < 10:
        action = "OVERCUT viable — stay out and push"
        rationale = (
            f"Tyre only {inp.tyre_age_laps} laps old — still in the performance window. "
            f"Push for 5-8 laps while rival on out-lap, then box with clear air."
        )
        alternatives = ["Abandon if pace drops more than 1.5s/lap vs rivals"]
        risk = "MEDIUM"
        hist = "Overcuts work best when the driver can maintain pace within 0.5s of qualifying pace."
    else:
        action = "OVERCUT risky — tyres too old to maintain the delta"
        rationale = (
            f"Tyre already {inp.tyre_age_laps} laps old. Rival on fresh rubber will pull away "
            f"faster than you can build a gap. Overcut unlikely to succeed."
        )
        alternatives = ["Box within 2 laps — accept reactive undercut"]
        risk = "HIGH"
        hist = "Overcuts on old tyres fail ~80% of the time — tyre deg compounds vs fresh rubber pace."

    return Recommendation(action=action, rationale=rationale, alternatives=alternatives,
                          risk=risk, historical_note=hist)


def weather_change_scenario(inp: ScenarioInput, incoming_condition: str) -> Recommendation:
    """Weather is changing — intermediate or wet call."""
    if incoming_condition == "WET":
        action = "BOX for WETS at first sign of heavy rain"
        rationale = "Full wets required in heavy rain. Staying on slicks risks aquaplaning."
        alternatives = ["INTERMEDIATE if rain is light — 'damp' threshold", "Split strategy if uncertain"]
        risk = "HIGH"
        hist = "Teams that wait too long for wet calls lose 10-30 seconds per lap vs correct tyre."
    else:
        action = "BOX for INTERMEDIATES — mixed conditions imminent"
        rationale = "Intermediates cover the widest range of wet conditions."
        alternatives = ["Stay out 1-2 laps to read track evolution", "Gamble on slicks if rain expected to pass quickly"]
        risk = "MEDIUM"
        hist = "Intermediate call in mixed conditions is the most contested — use track temperature as the key metric."

    return Recommendation(action=action, rationale=rationale, alternatives=alternatives,
                          risk=risk, historical_note=hist)


# ── Scenario runner ────────────────────────────────────────────────────────────

SCENARIOS = {
    "sc": ("Safety Car Deployed", lambda inp: safety_car_scenario(inp, "SC")),
    "vsc": ("Virtual Safety Car Deployed", lambda inp: safety_car_scenario(inp, "VSC")),
    "red_flag": ("Red Flag", red_flag_scenario),
    "undercut": ("Rival Behind Pitted — Undercut Threat", undercut_threat_scenario),
    "overcut": ("We Stay Out — Overcut Attempt", overcut_scenario),
}


def run_all_scenarios(inp: ScenarioInput) -> dict[str, Recommendation]:
    """Run all standard scenarios for given race state."""
    results = {}
    for key, (label, fn) in SCENARIOS.items():
        results[key] = {"label": label, "rec": fn(inp)}
    return results
