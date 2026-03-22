"""
F1 Race Strategy Intelligence Tool
====================================
Usage:
    python main.py --circuit Suzuka --team RedBull --driver VER --race-date 2025-04-06

    # Run an interactive scenario at a specific race state:
    python main.py --circuit Suzuka --team RedBull --driver VER --race-date 2025-04-06 \
                   --scenario sc --lap 18 --position 2 --compound MEDIUM \
                   --tyre-age 14 --gap-ahead 8.5 --gap-behind 4.2

Outputs:
    - Console briefing (rich formatted)
    - outputs/<circuit>_<date>_briefing.txt
"""

import argparse
import json
from pathlib import Path
from datetime import datetime

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box
from rich.text import Text

from track_dna import analyse_circuit, CIRCUIT_COORDS
from weather import fetch_forecast
from scenario_engine import ScenarioInput, run_all_scenarios
from report import generate_html


# ── Embedded Suzuka historical data (fallback when network unavailable) ───────

SUZUKA_DEMO_DNA = {
    "circuit": "Suzuka",
    "years_analysed": [2023, 2024],
    "races_found": 2,
    "pit_delta_seconds": 22.5,
    "total_laps": 53,
    "safety_car": {
        "sc_per_race": 0.5,
        "vsc_per_race": 1.0,
        "red_flag_per_race": 0.0,
        "by_window": {
            "early (L1-L17)": {"count": 1, "types": ["SC"]},
            "mid (L18-L35)": {"count": 1, "types": ["VSC"]},
            "late (L36+)": {"count": 0, "types": []},
        },
        "all_events": [
            {"type": "SC", "lap": 8, "message": "SAFETY CAR DEPLOYED"},
            {"type": "VSC", "lap": 24, "message": "VIRTUAL SAFETY CAR DEPLOYED"},
        ],
    },
    "pit_windows": {
        "Early (1-15)": 4,
        "Standard (16-25)": 28,
        "Late (26-35)": 8,
        "Very Late (36+)": 2,
    },
    "compound_avg_lap_s": {
        "SOFT": 93.4,
        "MEDIUM": 94.1,
        "HARD": 95.3,
    },
    "team_tendencies": [
        {"Team": "Red Bull Racing", "AvgFirstStop": 17.5, "AvgStops": 2.0},
        {"Team": "Ferrari", "AvgFirstStop": 15.0, "AvgStops": 2.0},
        {"Team": "Mercedes", "AvgFirstStop": 21.0, "AvgStops": 2.0},
        {"Team": "McLaren", "AvgFirstStop": 18.5, "AvgStops": 2.0},
    ],
    "raw_pits": None,
    "_source": "embedded historical estimates",
}

console = Console()
OUTPUT_DIR = Path(__file__).parent / "outputs"
OUTPUT_DIR.mkdir(exist_ok=True)


# ── Team profiles ─────────────────────────────────────────────────────────────

TEAM_PROFILES = {
    "RedBull": {
        "name": "Red Bull Racing",
        "tyre_tendency": "Easy on fronts, pushes rears hard",
        "strategy_style": "Aggressive — tends to set the strategy pace",
        "typical_first_stop": "L16-L20",
        "undercut_risk": "HIGH — RB always threatens undercut",
    },
    "Ferrari": {
        "name": "Scuderia Ferrari",
        "tyre_tendency": "High degradation on mediums in heat",
        "strategy_style": "Reactive — often mirrors Red Bull",
        "typical_first_stop": "L14-L18",
        "undercut_risk": "MEDIUM",
    },
    "Mercedes": {
        "name": "Mercedes-AMG Petronas",
        "tyre_tendency": "Strong tyre management, rear-limited",
        "strategy_style": "Split strategy — uses both drivers as data points",
        "typical_first_stop": "L18-L24",
        "undercut_risk": "MEDIUM",
    },
    "McLaren": {
        "name": "McLaren Formula 1",
        "tyre_tendency": "Balanced — strong in medium compound",
        "strategy_style": "Opportunistic — capitalises on rivals' mistakes",
        "typical_first_stop": "L15-L20",
        "undercut_risk": "HIGH",
    },
    "Aston Martin": {
        "name": "Aston Martin F1",
        "tyre_tendency": "Struggles with tyre warm-up in cool conditions",
        "strategy_style": "Conservative",
        "typical_first_stop": "L18-L25",
        "undercut_risk": "LOW",
    },
}

DEFAULT_TEAM = {
    "name": "Unknown Team",
    "tyre_tendency": "No profile available",
    "strategy_style": "Unknown",
    "typical_first_stop": "L18-L22",
    "undercut_risk": "MEDIUM",
}

# ── Driver profiles ───────────────────────────────────────────────────────────

DRIVER_PROFILES = {
    "VER": {"name": "Max Verstappen", "tyre_mgmt": "Excellent", "overtaking": "Elite", "wet_delta": "+0.3s advantage", "incident_rate": "Low"},
    "LEC": {"name": "Charles Leclerc", "tyre_mgmt": "Medium", "overtaking": "Strong", "wet_delta": "Neutral", "incident_rate": "Medium — Lap 1 incidents"},
    "HAM": {"name": "Lewis Hamilton", "tyre_mgmt": "Elite", "overtaking": "Elite", "wet_delta": "+0.5s advantage", "incident_rate": "Very Low"},
    "NOR": {"name": "Lando Norris", "tyre_mgmt": "Good", "overtaking": "Strong", "wet_delta": "Neutral", "incident_rate": "Low"},
    "SAI": {"name": "Carlos Sainz", "tyre_mgmt": "Excellent", "overtaking": "Good", "wet_delta": "Neutral", "incident_rate": "Low"},
    "RUS": {"name": "George Russell", "tyre_mgmt": "Good", "overtaking": "Good", "wet_delta": "Neutral", "incident_rate": "Low"},
    "ALO": {"name": "Fernando Alonso", "tyre_mgmt": "Elite", "overtaking": "Elite", "wet_delta": "+0.4s advantage", "incident_rate": "Very Low"},
    "PIA": {"name": "Oscar Piastri", "tyre_mgmt": "Good", "overtaking": "Good", "wet_delta": "Neutral", "incident_rate": "Low"},
}

DEFAULT_DRIVER = {"name": "Driver", "tyre_mgmt": "Unknown", "overtaking": "Unknown", "wet_delta": "Unknown", "incident_rate": "Unknown"}


# ── Display helpers ───────────────────────────────────────────────────────────

def _risk_color(risk: str) -> str:
    return {"LOW": "green", "MEDIUM": "yellow", "HIGH": "red"}.get(risk, "white")


def print_track_dna(dna: dict):
    console.print(Panel(
        f"[bold cyan]{dna['circuit']} Track DNA[/bold cyan]\n"
        f"Years analysed: {dna['years_analysed']} | Races found: {dna['races_found']}\n"
        f"Total laps: {dna['total_laps']} | Pit lane delta: {dna['pit_delta_seconds']}s",
        box=box.ROUNDED,
        border_style="cyan",
    ))

    # Safety car summary
    sc = dna["safety_car"]
    sc_table = Table(title="Safety Car History", box=box.SIMPLE)
    sc_table.add_column("Event Type", style="bold")
    sc_table.add_column("Per Race Avg")
    sc_table.add_row("Full Safety Car (SC)", f"{sc['sc_per_race']:.2f}")
    sc_table.add_row("Virtual Safety Car (VSC)", f"{sc['vsc_per_race']:.2f}")
    sc_table.add_row("Red Flag", f"{sc['red_flag_per_race']:.2f}")
    console.print(sc_table)

    # SC by window
    window_table = Table(title="SC Deployment Windows", box=box.SIMPLE)
    window_table.add_column("Race Window")
    window_table.add_column("Events")
    window_table.add_column("Types")
    for window, data in sc["by_window"].items():
        types_str = ", ".join(set(data["types"])) if data["types"] else "none"
        window_table.add_row(window, str(data["count"]), types_str)
    console.print(window_table)

    # Pit windows
    if dna["pit_windows"]:
        pw_table = Table(title="Historical First Pit Stop Windows", box=box.SIMPLE)
        pw_table.add_column("Window")
        pw_table.add_column("Stop Count")
        for window, count in sorted(dna["pit_windows"].items(), key=lambda x: str(x[0])):
            pw_table.add_row(str(window), str(count))
        console.print(pw_table)

    # Compound performance
    if dna["compound_avg_lap_s"]:
        comp_table = Table(title="Compound Avg Lap Time (clean laps)", box=box.SIMPLE)
        comp_table.add_column("Compound")
        comp_table.add_column("Avg Lap (s)")
        for compound, avg in sorted(dna["compound_avg_lap_s"].items(), key=lambda x: x[1]):
            comp_table.add_row(compound, f"{avg:.3f}")
        console.print(comp_table)

    # Team tendencies
    if dna["team_tendencies"]:
        tend_table = Table(title="Team Strategy Tendencies (historical)", box=box.SIMPLE)
        tend_table.add_column("Team")
        tend_table.add_column("Avg First Stop Lap")
        tend_table.add_column("Avg Total Stops")
        for row in sorted(dna["team_tendencies"], key=lambda x: x.get("AvgFirstStop", 99)):
            tend_table.add_row(
                row.get("Team", "?"),
                str(row.get("AvgFirstStop", "?")),
                str(row.get("AvgStops", "?")),
            )
        console.print(tend_table)


def print_weather(wx: dict):
    f = wx["race_window_forecast"]
    color = "green" if "DRY" in wx["condition"] else "yellow" if "MIXED" in wx["condition"] else "red"

    console.print(Panel(
        f"[bold]Weather: {wx['circuit']} — Race Day {wx['race_date']}[/bold]\n\n"
        f"Condition:      [{color}]{wx['condition']}[/{color}]\n"
        f"Temp:           {f.get('temp_c', '?')}°C\n"
        f"Humidity:       {f.get('humidity_pct', '?')}%\n"
        f"Precip Prob:    {f.get('precip_prob_pct', '?')}%\n"
        f"Wind:           {f.get('wind_kph', '?')} kph\n"
        f"Cloud cover:    {f.get('cloud_pct', '?')}%\n\n"
        f"[italic]{wx['strategy_implication']}[/italic]",
        title="Race Day Forecast",
        border_style=color,
        box=box.ROUNDED,
    ))


def print_team_driver(team_key: str, driver_key: str):
    team = TEAM_PROFILES.get(team_key, DEFAULT_TEAM)
    driver = DRIVER_PROFILES.get(driver_key, DEFAULT_DRIVER)

    console.print(Panel(
        f"[bold]Team:[/bold] {team['name']}\n"
        f"Tyre tendency:    {team['tyre_tendency']}\n"
        f"Strategy style:   {team['strategy_style']}\n"
        f"Typical 1st stop: {team['typical_first_stop']}\n"
        f"Undercut threat:  {team['undercut_risk']}\n\n"
        f"[bold]Driver:[/bold] {driver['name']} ({driver_key})\n"
        f"Tyre management:  {driver['tyre_mgmt']}\n"
        f"Overtaking:       {driver['overtaking']}\n"
        f"Wet performance:  {driver['wet_delta']}\n"
        f"L1 incident rate: {driver['incident_rate']}",
        title="Team & Driver Profile",
        border_style="blue",
        box=box.ROUNDED,
    ))


def print_scenarios(all_recs: dict, inp: ScenarioInput):
    console.print("\n[bold underline]Scenario Engine — Race State Recommendations[/bold underline]")
    console.print(f"  Lap: [bold]{inp.current_lap}/{inp.total_laps}[/bold]  |  "
                  f"P{inp.current_position}  |  {inp.current_compound} ({inp.tyre_age_laps} laps)  |  "
                  f"Gap ahead: {inp.gap_ahead_seconds}s  |  Gap behind: {inp.gap_behind_seconds}s\n")

    for key, data in all_recs.items():
        label = data["label"]
        rec = data["rec"]
        risk_color = _risk_color(rec.risk)

        console.print(Panel(
            f"[bold green]Action:[/bold green] {rec.action}\n\n"
            f"[bold]Rationale:[/bold] {rec.rationale}\n\n"
            f"[bold]Alternatives:[/bold]\n" +
            "\n".join(f"  • {a}" for a in rec.alternatives) +
            f"\n\n[bold]Historical note:[/bold] [italic]{rec.historical_note}[/italic]",
            title=f"[{risk_color}][RISK: {rec.risk}][/{risk_color}]  {label}",
            border_style=risk_color,
            box=box.ROUNDED,
        ))


def _update_docs_index(docs_dir: Path):
    """Regenerate docs/index.html listing all available briefings."""
    briefings = sorted(docs_dir.glob("*_briefing.html"), reverse=True)
    rows = ""
    for f in briefings:
        parts = f.stem.split("_")
        circuit = parts[0] if len(parts) > 0 else "?"
        date = parts[1] if len(parts) > 1 else "?"
        driver = parts[2] if len(parts) > 2 else "?"
        rows += f"""
        <tr>
          <td><a href="{f.name}">{circuit}</a></td>
          <td>{date}</td>
          <td>{driver}</td>
          <td><a href="{f.name}" class="btn">Open Briefing &#8594;</a></td>
        </tr>"""

    index_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>F1 Strategy Briefings</title>
<style>
  body {{ background:#0d0d1a; color:#e0e0e0; font-family:'Segoe UI',Arial,sans-serif;
          max-width:800px; margin:40px auto; padding:0 20px; }}
  h1 {{ color:#fff; border-bottom:2px solid #e10600; padding-bottom:12px; margin-bottom:24px; }}
  .subtitle {{ color:#888; margin-top:-16px; margin-bottom:24px; font-size:13px; }}
  table {{ width:100%; border-collapse:collapse; }}
  th {{ text-align:left; color:#e10600; font-size:12px; text-transform:uppercase;
        letter-spacing:1px; padding:8px 12px; border-bottom:1px solid #2a2a4a; }}
  td {{ padding:10px 12px; border-bottom:1px solid #1a1a2e; }}
  tr:hover td {{ background:#1a1a2e; }}
  .btn {{ background:#e10600; color:#fff; padding:4px 14px; border-radius:4px;
          text-decoration:none; font-size:12px; }}
  .btn:hover {{ background:#ff2020; }}
  .empty {{ color:#555; padding:20px 0; }}
</style>
</head>
<body>
<h1>&#127937; F1 Strategy Briefings</h1>
<p class="subtitle">Generated by F1 Race Strategy Intelligence Tool</p>
<table>
  <thead><tr><th>Circuit</th><th>Race Date</th><th>Driver</th><th></th></tr></thead>
  <tbody>
    {"".join(rows) if rows else '<tr><td colspan="4" class="empty">No briefings yet. Run main.py to generate one.</td></tr>'}
  </tbody>
</table>
<p style="color:#444;font-size:11px;margin-top:32px;">
  Data: FastF1 / OpenF1 / Open-Meteo &nbsp;&#183;&nbsp; {datetime.now().strftime("%Y-%m-%d")}
</p>
</body>
</html>"""
    (docs_dir / "index.html").write_text(index_html, encoding="utf-8")


def save_briefing(dna: dict, wx: dict, team_key: str, driver_key: str,
                  scenarios: dict, inp: ScenarioInput, output_path: Path):
    """Save a plain-text briefing to file."""
    lines = [
        f"F1 Race Strategy Briefing",
        f"Circuit: {dna['circuit']} | Race Date: {wx['race_date']}",
        f"Team: {team_key} | Driver: {driver_key}",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "=" * 60,
        "",
        "TRACK DNA",
        f"  Pit delta: {dna['pit_delta_seconds']}s",
        f"  SC per race: {dna['safety_car']['sc_per_race']}",
        f"  VSC per race: {dna['safety_car']['vsc_per_race']}",
        f"  Red Flag per race: {dna['safety_car']['red_flag_per_race']}",
        "",
        "SC WINDOWS",
    ]
    for window, data in dna["safety_car"]["by_window"].items():
        lines.append(f"  {window}: {data['count']} events — {', '.join(set(data['types'])) or 'none'}")

    lines += ["", "PIT STOP DISTRIBUTION"]
    for window, count in dna["pit_windows"].items():
        lines.append(f"  {window}: {count} stops")

    lines += ["", "COMPOUND PERFORMANCE (avg lap s)"]
    for compound, avg in sorted(dna["compound_avg_lap_s"].items(), key=lambda x: x[1]):
        lines.append(f"  {compound}: {avg:.3f}s")

    lines += ["", "WEATHER", f"  Condition: {wx['condition']}",
              f"  Temp: {wx['race_window_forecast'].get('temp_c')}°C",
              f"  Precip prob: {wx['race_window_forecast'].get('precip_prob_pct')}%",
              f"  Note: {wx['strategy_implication']}", ""]

    lines += ["SCENARIOS", f"  Race state: Lap {inp.current_lap}/{inp.total_laps} | P{inp.current_position} | {inp.current_compound} {inp.tyre_age_laps}L"]
    for key, data in scenarios.items():
        rec = data["rec"]
        lines += [
            f"\n  [{rec.risk}] {data['label']}",
            f"  -> Action: {rec.action}",
            f"  -> {rec.rationale}",
            f"  -> History: {rec.historical_note}",
        ]

    output_path.write_text("\n".join(lines))
    console.print(f"\n[dim]Briefing saved to: {output_path}[/dim]")


# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(description="F1 Race Strategy Intelligence Tool")
    p.add_argument("--circuit", default="Suzuka", help="Circuit name")
    p.add_argument("--team", default="RedBull", help="Team key (e.g. RedBull, Ferrari, Mercedes)")
    p.add_argument("--driver", default="VER", help="Driver code (e.g. VER, HAM, LEC)")
    p.add_argument("--race-date", default=None, help="Race date YYYY-MM-DD (default: next Sunday)")
    # Race state for scenario engine
    p.add_argument("--lap", type=int, default=20, help="Current lap number")
    p.add_argument("--position", type=int, default=3, help="Current race position")
    p.add_argument("--compound", default="MEDIUM", help="Current tyre compound")
    p.add_argument("--tyre-age", type=int, default=15, help="Tyre age in laps")
    p.add_argument("--gap-ahead", type=float, default=6.0, help="Gap to car ahead (seconds)")
    p.add_argument("--gap-behind", type=float, default=5.0, help="Gap to car behind (seconds)")
    p.add_argument("--championship-pos", type=int, default=2, help="Driver championship position")
    p.add_argument("--championship-gap", type=int, default=15, help="Points gap to leader")
    p.add_argument("--no-weather", action="store_true", help="Skip weather fetch")
    p.add_argument("--demo", action="store_true", help="Use embedded historical data (no network needed)")
    return p.parse_args()


def main():
    args = parse_args()

    console.print(Panel(
        "[bold white]F1 Race Strategy Intelligence Tool[/bold white]\n"
        f"Circuit: [cyan]{args.circuit}[/cyan]  |  Team: [blue]{args.team}[/blue]  |  Driver: [green]{args.driver}[/green]",
        box=box.DOUBLE_EDGE,
        border_style="white",
    ))

    # 1. Track DNA
    if args.demo and args.circuit == "Suzuka":
        console.print("[yellow]Demo mode: using embedded Suzuka historical data[/yellow]")
        dna = SUZUKA_DEMO_DNA
    else:
        dna = analyse_circuit(args.circuit)

    # 2. Weather
    if args.no_weather:
        from weather import _fallback_weather
        wx = _fallback_weather(args.circuit, args.race_date or "N/A")
    else:
        wx = fetch_forecast(args.circuit, args.race_date)

    # 3. Team / Driver profiles
    print_team_driver(args.team, args.driver)

    # 4. Track DNA display
    print_track_dna(dna)

    # 5. Weather display
    print_weather(wx)

    # 6. Scenario engine
    circuit_info = CIRCUIT_COORDS.get(args.circuit, {"laps": 53, "pit_delta": 21.0})
    inp = ScenarioInput(
        circuit=args.circuit,
        team=args.team,
        driver=args.driver,
        current_lap=args.lap,
        total_laps=circuit_info["laps"],
        current_position=args.position,
        current_compound=args.compound,
        tyre_age_laps=args.tyre_age,
        pit_delta_seconds=circuit_info["pit_delta"],
        gap_ahead_seconds=args.gap_ahead,
        gap_behind_seconds=args.gap_behind,
        championship_position=args.championship_pos,
        championship_gap_points=args.championship_gap,
        weather_condition=wx["condition"].split(" ")[0],
        starting_compound=args.compound,
    )

    all_recs = run_all_scenarios(inp)
    print_scenarios(all_recs, inp)

    # 7. Save briefing
    date_str = args.race_date or datetime.now().strftime("%Y-%m-%d")
    out_path = OUTPUT_DIR / f"{args.circuit}_{date_str}_{args.driver}_briefing.txt"
    save_briefing(dna, wx, args.team, args.driver, all_recs, inp, out_path)

    html_path = OUTPUT_DIR / f"{args.circuit}_{date_str}_{args.driver}_briefing.html"
    generate_html(dna, wx, args.team, args.driver, all_recs, inp, html_path,
                  TEAM_PROFILES, DRIVER_PROFILES)
    console.print(f"[bold green]HTML briefing (local):[/bold green] {html_path}")

    # Also save to docs/ for GitHub Pages
    docs_dir = Path(__file__).parent.parent / "docs"
    docs_dir.mkdir(exist_ok=True)
    briefing_name = f"{args.circuit}_{date_str}_{args.driver}_briefing.html"
    docs_html_path = docs_dir / briefing_name
    generate_html(dna, wx, args.team, args.driver, all_recs, inp, docs_html_path,
                  TEAM_PROFILES, DRIVER_PROFILES)
    _update_docs_index(docs_dir)
    console.print(f"[bold cyan]GitHub Pages:[/bold cyan] {docs_html_path}")


if __name__ == "__main__":
    main()
