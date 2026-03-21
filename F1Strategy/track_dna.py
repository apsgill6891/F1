"""
Track DNA Module
Analyses historical race data for a given circuit using FastF1.
Extracts: safety car windows, pit stop timing, tyre compound performance,
overtaking difficulty, pit lane delta, and competitor strategy tendencies.
"""

import fastf1
import fastf1.core
import pandas as pd
import numpy as np
from pathlib import Path
import warnings
warnings.filterwarnings("ignore")

# Cache directory for FastF1
CACHE_DIR = Path(__file__).parent / "data" / "fastf1_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
fastf1.Cache.enable_cache(str(CACHE_DIR))

# Suzuka GPS coordinates for weather
CIRCUIT_COORDS = {
    "Suzuka": {"lat": 34.8431, "lon": 136.5407, "laps": 53, "pit_delta": 22.5},
    "Monza": {"lat": 45.6156, "lon": 9.2811, "laps": 53, "pit_delta": 17.0},
    "Monaco": {"lat": 43.7347, "lon": 7.4205, "laps": 78, "pit_delta": 22.0},
    "Silverstone": {"lat": 52.0786, "lon": -1.0169, "laps": 52, "pit_delta": 19.5},
    "COTA": {"lat": 30.1328, "lon": -97.6411, "laps": 56, "pit_delta": 21.0},
}

# Years of data to pull
ANALYSIS_YEARS = [2023, 2024]


def load_race_session(year: int, circuit: str):
    """Load a race session; return None if unavailable."""
    try:
        session = fastf1.get_session(year, circuit, "R")
        session.load(telemetry=False, weather=True, messages=True)
        return session
    except Exception as e:
        print(f"  [skip] {year} {circuit}: {e}")
        return None


def extract_safety_car_windows(session) -> list[dict]:
    """Return list of SC/VSC deployments with lap number and type."""
    events = []
    try:
        rcm = session.race_control_messages
    except Exception:
        return events
    if rcm is None:
        return events

    sc_msgs = rcm[
        session.race_control_messages["Message"].str.contains(
            "SAFETY CAR|VIRTUAL SAFETY CAR|VSC|SC DEPLOYED|RED FLAG",
            case=False, na=False
        )
    ]

    for _, row in sc_msgs.iterrows():
        msg = row["Message"].upper()
        if "RED FLAG" in msg:
            event_type = "RED FLAG"
        elif "VIRTUAL" in msg or "VSC" in msg:
            event_type = "VSC"
        else:
            event_type = "SC"

        lap = row.get("Lap", None)
        if lap is None or (hasattr(lap, '__class__') and 'NaT' in str(lap)):
            lap = "unknown"

        events.append({
            "type": event_type,
            "lap": lap,
            "message": row["Message"][:80],
        })

    return events


def extract_pit_windows(session) -> pd.DataFrame:
    """Return per-driver pit stop laps and compound changes."""
    try:
        laps = session.laps
        if laps is None or laps.empty:
            return pd.DataFrame()
    except Exception:
        return pd.DataFrame()
    pits = laps[laps["PitInTime"].notna()][
        ["Driver", "LapNumber", "Compound", "TyreLife", "Team"]
    ].copy()
    pits = pits.rename(columns={"LapNumber": "StopOnLap"})
    return pits


def compound_performance(session) -> pd.DataFrame:
    """Avg lap time per compound (filtered for representative laps)."""
    try:
        laps = session.laps.pick_quicklaps()
        if laps is None or laps.empty:
            return pd.DataFrame()
        laps = laps[laps["Compound"].notna()]
    except Exception:
        return pd.DataFrame()

    stats = (
        laps.groupby("Compound")["LapTime"]
        .agg(["count", "mean", "std"])
        .reset_index()
    )
    stats["mean_s"] = stats["mean"].dt.total_seconds()
    stats["std_s"] = stats["std"].dt.total_seconds()
    stats = stats.rename(columns={"count": "sample_laps"})
    return stats[["Compound", "sample_laps", "mean_s", "std_s"]]


def team_strategy_tendency(pit_df: pd.DataFrame) -> pd.DataFrame:
    """Summarise typical first stop lap and number of stops per team."""
    if pit_df.empty:
        return pd.DataFrame()

    first_stop = pit_df.groupby(["Team", "Driver"])["StopOnLap"].min().reset_index()
    first_stop = first_stop.rename(columns={"StopOnLap": "FirstStopLap"})
    stop_count = pit_df.groupby(["Team", "Driver"]).size().reset_index(name="TotalStops")

    merged = first_stop.merge(stop_count, on=["Team", "Driver"])
    summary = merged.groupby("Team").agg(
        AvgFirstStop=("FirstStopLap", "mean"),
        AvgStops=("TotalStops", "mean"),
    ).round(1).reset_index()
    return summary


def sc_probability_by_window(sc_events: list[dict], total_laps: int) -> dict:
    """
    Bucket SC/VSC/Red Flag events into thirds of the race and return
    probability estimates based on historical occurrences.
    """
    windows = {
        "early (L1-L17)": [],
        "mid (L18-L35)": [],
        "late (L36+)": [],
    }

    for ev in sc_events:
        try:
            lap = int(ev["lap"])
        except (ValueError, TypeError):
            continue

        third = total_laps // 3
        if lap <= third:
            windows["early (L1-L17)"].append(ev["type"])
        elif lap <= third * 2:
            windows["mid (L18-L35)"].append(ev["type"])
        else:
            windows["late (L36+)"].append(ev["type"])

    return {k: {"count": len(v), "types": v} for k, v in windows.items()}


def analyse_circuit(circuit: str = "Suzuka") -> dict:
    """
    Full historical analysis for a circuit across ANALYSIS_YEARS.
    Returns a structured dict with all insights.
    """
    print(f"\n[Track DNA] Loading historical data for {circuit}...")
    info = CIRCUIT_COORDS.get(circuit, {"laps": 53, "pit_delta": 21.0})
    total_laps = info["laps"]

    all_sc_events = []
    all_pits = []
    compound_stats = []
    team_tendencies = []
    race_count = 0

    for year in ANALYSIS_YEARS:
        print(f"  -> {year}...")
        session = load_race_session(year, circuit)
        if session is None:
            continue

        # Count race as found only if laps loaded
        try:
            _ = session.laps
            race_count += 1
        except Exception:
            print(f"  [skip] {year} {circuit}: session loaded but laps unavailable")
            continue

        sc_events = extract_safety_car_windows(session)
        all_sc_events.extend(sc_events)

        pit_df = extract_pit_windows(session)
        if not pit_df.empty:
            pit_df["Year"] = year
            all_pits.append(pit_df)

        comp = compound_performance(session)
        comp["Year"] = year
        compound_stats.append(comp)

        if not pit_df.empty:
            team_tend = team_strategy_tendency(pit_df)
            team_tendencies.append(team_tend)

    # Aggregate
    pits_combined = pd.concat(all_pits) if all_pits else pd.DataFrame()
    compounds_combined = pd.concat(compound_stats) if compound_stats else pd.DataFrame()

    # Pit window distribution
    pit_window_dist = {}
    if not pits_combined.empty:
        pits_combined["Window"] = pd.cut(
            pits_combined["StopOnLap"],
            bins=[0, 15, 25, 35, 99],
            labels=["Early (1-15)", "Standard (16-25)", "Late (26-35)", "Very Late (36+)"]
        )
        pit_window_dist = pits_combined["Window"].value_counts().to_dict()

    # SC probability
    sc_prob = sc_probability_by_window(all_sc_events, total_laps)
    sc_rate = len([e for e in all_sc_events if e["type"] == "SC"]) / max(race_count, 1)
    vsc_rate = len([e for e in all_sc_events if e["type"] == "VSC"]) / max(race_count, 1)
    rf_rate = len([e for e in all_sc_events if e["type"] == "RED FLAG"]) / max(race_count, 1)

    # Compound summary
    compound_summary = {}
    if not compounds_combined.empty:
        compound_summary = (
            compounds_combined.groupby("Compound")["mean_s"]
            .mean()
            .round(3)
            .to_dict()
        )

    # Team tendencies
    team_summary = pd.DataFrame()
    if team_tendencies:
        team_summary = (
            pd.concat(team_tendencies)
            .groupby("Team")
            .agg({"AvgFirstStop": "mean", "AvgStops": "mean"})
            .round(1)
            .reset_index()
        )

    return {
        "circuit": circuit,
        "years_analysed": ANALYSIS_YEARS,
        "races_found": race_count,
        "pit_delta_seconds": info["pit_delta"],
        "total_laps": total_laps,
        "safety_car": {
            "sc_per_race": round(sc_rate, 2),
            "vsc_per_race": round(vsc_rate, 2),
            "red_flag_per_race": round(rf_rate, 2),
            "by_window": sc_prob,
            "all_events": all_sc_events,
        },
        "pit_windows": pit_window_dist,
        "compound_avg_lap_s": compound_summary,
        "team_tendencies": team_summary.to_dict("records") if not team_summary.empty else [],
        "raw_pits": pits_combined,
    }
