"""
HTML Report Generator
Converts track DNA + weather + scenario engine output into a
self-contained HTML file with Plotly charts — no server needed.
"""

import json
from pathlib import Path
from datetime import datetime

TEAM_COLORS = {
    "Red Bull Racing": "#3671C6",
    "Ferrari": "#E8002D",
    "Mercedes": "#27F4D2",
    "McLaren": "#FF8000",
    "Aston Martin": "#229971",
    "Alpine": "#FF87BC",
    "Williams": "#64C4FF",
    "RB": "#6692FF",
    "Kick Sauber": "#52E252",
    "Haas": "#B6BABD",
}

COMPOUND_COLORS = {
    "SOFT": "#E8002D",
    "MEDIUM": "#FFF200",
    "HARD": "#FFFFFF",
    "INTERMEDIATE": "#39B54A",
    "WET": "#0067FF",
}

RISK_COLORS = {"LOW": "#39B54A", "MEDIUM": "#FFF200", "HIGH": "#E8002D"}
RISK_BG = {"LOW": "#0d2b0d", "MEDIUM": "#2b2800", "HIGH": "#2b0d0d"}


def _plotly_compound_chart(compound_avg: dict) -> str:
    if not compound_avg:
        return ""
    compounds = list(compound_avg.keys())
    times = [compound_avg[c] for c in compounds]
    colors = [COMPOUND_COLORS.get(c, "#888") for c in compounds]
    baseline = min(times)
    deltas = [round(t - baseline, 3) for t in times]

    data = [{
        "type": "bar",
        "x": compounds,
        "y": times,
        "marker": {"color": colors, "line": {"color": "#333", "width": 1}},
        "text": [f"{t:.3f}s" for t in times],
        "textposition": "outside",
        "hovertemplate": "<b>%{x}</b><br>Avg lap: %{y:.3f}s<extra></extra>",
    }]
    layout = {
        "paper_bgcolor": "#1a1a2e",
        "plot_bgcolor": "#16213e",
        "font": {"color": "#e0e0e0", "family": "Arial"},
        "title": {"text": "Compound Avg Lap Time (clean laps)", "font": {"size": 14}},
        "xaxis": {"title": "Compound", "gridcolor": "#333"},
        "yaxis": {"title": "Avg Lap (s)", "gridcolor": "#333", "range": [baseline - 2, max(times) + 3]},
        "margin": {"l": 50, "r": 20, "t": 50, "b": 40},
        "height": 280,
    }
    return f"Plotly.newPlot('chart-compounds', {json.dumps(data)}, {json.dumps(layout)}, {{responsive:true}});"


def _plotly_pit_window_chart(pit_windows: dict) -> str:
    if not pit_windows:
        return ""
    labels = [str(k) for k in pit_windows.keys()]
    values = list(pit_windows.values())

    data = [{
        "type": "bar",
        "x": labels,
        "y": values,
        "marker": {"color": ["#3671C6", "#39B54A", "#FFF200", "#E8002D"][:len(labels)]},
        "text": values,
        "textposition": "outside",
        "hovertemplate": "<b>%{x}</b><br>Stops: %{y}<extra></extra>",
    }]
    layout = {
        "paper_bgcolor": "#1a1a2e",
        "plot_bgcolor": "#16213e",
        "font": {"color": "#e0e0e0"},
        "title": {"text": "Historical First Pit Stop Distribution", "font": {"size": 14}},
        "xaxis": {"title": "Lap Window", "gridcolor": "#333"},
        "yaxis": {"title": "Stop Count", "gridcolor": "#333"},
        "margin": {"l": 50, "r": 20, "t": 50, "b": 60},
        "height": 280,
    }
    return f"Plotly.newPlot('chart-pitstops', {json.dumps(data)}, {json.dumps(layout)}, {{responsive:true}});"


def _plotly_team_strategy_chart(team_tendencies: list) -> str:
    if not team_tendencies:
        return ""
    teams = [t.get("Team", "?") for t in team_tendencies]
    first_stops = [t.get("AvgFirstStop", 20) for t in team_tendencies]
    colors = [TEAM_COLORS.get(team, "#888") for team in teams]

    data = [{
        "type": "bar",
        "orientation": "h",
        "y": teams,
        "x": first_stops,
        "marker": {"color": colors},
        "text": [f"L{s}" for s in first_stops],
        "textposition": "outside",
        "hovertemplate": "<b>%{y}</b><br>Avg first stop: Lap %{x}<extra></extra>",
    }]
    layout = {
        "paper_bgcolor": "#1a1a2e",
        "plot_bgcolor": "#16213e",
        "font": {"color": "#e0e0e0"},
        "title": {"text": "Team Avg First Stop Lap (historical)", "font": {"size": 14}},
        "xaxis": {"title": "Lap Number", "gridcolor": "#333"},
        "yaxis": {"gridcolor": "#333"},
        "margin": {"l": 130, "r": 60, "t": 50, "b": 40},
        "height": 280,
    }
    return f"Plotly.newPlot('chart-teams', {json.dumps(data)}, {json.dumps(layout)}, {{responsive:true}});"


def _plotly_sc_window_chart(sc_data: dict) -> str:
    windows = sc_data.get("by_window", {})
    if not windows:
        return ""
    labels = list(windows.keys())
    counts = [windows[w]["count"] for w in labels]

    data = [{
        "type": "bar",
        "x": labels,
        "y": counts,
        "marker": {"color": ["#FFF200", "#FF8000", "#E8002D"][:len(labels)]},
        "text": counts,
        "textposition": "outside",
    }]
    layout = {
        "paper_bgcolor": "#1a1a2e",
        "plot_bgcolor": "#16213e",
        "font": {"color": "#e0e0e0"},
        "title": {"text": f"SC/VSC Events by Race Window (SC: {sc_data['sc_per_race']}/race, VSC: {sc_data['vsc_per_race']}/race)", "font": {"size": 13}},
        "xaxis": {"gridcolor": "#333"},
        "yaxis": {"title": "Event Count", "gridcolor": "#333", "dtick": 1},
        "margin": {"l": 50, "r": 20, "t": 60, "b": 40},
        "height": 280,
    }
    return f"Plotly.newPlot('chart-sc', {json.dumps(data)}, {json.dumps(layout)}, {{responsive:true}});"


def _scenario_card_html(label: str, rec) -> str:
    risk = rec.risk
    color = RISK_COLORS.get(risk, "#888")
    bg = RISK_BG.get(risk, "#1a1a2e")
    alts = "".join(f"<li>{a}</li>" for a in rec.alternatives)
    return f"""
    <div class="scenario-card" style="border-left: 4px solid {color}; background: {bg};">
        <div class="scenario-header">
            <span class="risk-badge" style="background:{color}; color:#000;">{risk}</span>
            <span class="scenario-title">{label}</span>
        </div>
        <div class="scenario-action">&#9658; {rec.action}</div>
        <div class="scenario-rationale">{rec.rationale}</div>
        <div class="scenario-alts">
            <strong>Alternatives:</strong>
            <ul>{alts}</ul>
        </div>
        <div class="scenario-hist"><em>Historical: {rec.historical_note}</em></div>
    </div>
    """


def generate_html(dna: dict, wx: dict, team_key: str, driver_key: str,
                  scenarios: dict, inp, output_path: Path,
                  team_profiles: dict, driver_profiles: dict):
    team = team_profiles.get(team_key, {})
    driver = driver_profiles.get(driver_key, {})
    wx_f = wx.get("race_window_forecast", {})
    condition = wx.get("condition", "Unknown")
    cond_color = "#39B54A" if "DRY" in condition else "#FFF200" if "MIXED" in condition else "#3671C6"

    scenario_cards_html = ""
    for key, data in scenarios.items():
        scenario_cards_html += _scenario_card_html(data["label"], data["rec"])

    # Build chart JS
    chart_js = "\n".join([
        _plotly_compound_chart(dna.get("compound_avg_lap_s", {})),
        _plotly_pit_window_chart(dna.get("pit_windows", {})),
        _plotly_team_strategy_chart(dna.get("team_tendencies", [])),
        _plotly_sc_window_chart(dna.get("safety_car", {})),
    ])

    sc = dna.get("safety_car", {})
    generated = datetime.now().strftime("%Y-%m-%d %H:%M")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>F1 Strategy Briefing — {dna['circuit']} {wx['race_date']}</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: #0d0d1a; color: #e0e0e0; font-family: 'Segoe UI', Arial, sans-serif; font-size: 14px; }}
  .header {{ background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
             border-bottom: 2px solid #e10600; padding: 20px 30px; }}
  .header h1 {{ font-size: 22px; color: #fff; }}
  .header .meta {{ color: #aaa; margin-top: 4px; font-size: 13px; }}
  .header .badge {{ display:inline-block; background:#e10600; color:#fff;
                    padding: 2px 10px; border-radius: 4px; font-size: 12px; margin-right: 8px; }}
  .grid-2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; padding: 16px 24px; }}
  .grid-4 {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; padding: 0 24px 16px; }}
  .card {{ background: #1a1a2e; border: 1px solid #2a2a4a; border-radius: 8px; padding: 16px; }}
  .card h3 {{ color: #e10600; font-size: 13px; text-transform: uppercase;
              letter-spacing: 1px; margin-bottom: 12px; }}
  .stat-row {{ display: flex; justify-content: space-between; padding: 5px 0;
               border-bottom: 1px solid #2a2a4a; }}
  .stat-label {{ color: #888; }}
  .stat-val {{ color: #fff; font-weight: bold; }}
  .condition-badge {{ display:inline-block; padding: 4px 12px; border-radius: 20px;
                      font-weight: bold; font-size: 13px; }}
  .chart-card {{ background: #1a1a2e; border: 1px solid #2a2a4a; border-radius: 8px;
                 padding: 12px; }}
  .scenarios-section {{ padding: 0 24px 24px; }}
  .scenarios-section h2 {{ color: #fff; font-size: 16px; margin-bottom: 4px; }}
  .scenarios-meta {{ color: #888; font-size: 13px; margin-bottom: 16px; }}
  .scenario-card {{ border-radius: 8px; padding: 16px; margin-bottom: 12px; }}
  .scenario-header {{ display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }}
  .risk-badge {{ padding: 2px 10px; border-radius: 12px; font-size: 11px;
                 font-weight: bold; letter-spacing: 1px; }}
  .scenario-title {{ font-size: 15px; font-weight: bold; color: #fff; }}
  .scenario-action {{ font-size: 16px; font-weight: bold; color: #fff;
                      margin-bottom: 8px; padding: 8px 12px;
                      background: rgba(255,255,255,0.05); border-radius: 4px; }}
  .scenario-rationale {{ color: #ccc; margin-bottom: 10px; line-height: 1.5; }}
  .scenario-alts {{ color: #aaa; margin-bottom: 8px; }}
  .scenario-alts ul {{ margin-left: 16px; margin-top: 4px; }}
  .scenario-alts li {{ margin-bottom: 3px; }}
  .scenario-hist {{ color: #777; font-size: 12px; font-style: italic; }}
  .stat-pill {{ display:inline-block; background:#16213e; border:1px solid #2a2a4a;
                border-radius: 20px; padding: 3px 10px; margin: 2px; font-size: 12px; }}
  .footer {{ text-align:center; color:#444; font-size:11px; padding: 16px; }}
  @media(max-width:768px) {{
    .grid-2, .grid-4 {{ grid-template-columns: 1fr; }}
  }}
</style>
</head>
<body>

<div class="header">
  <h1>&#127937; F1 Race Strategy Briefing</h1>
  <div class="meta">
    <span class="badge">{dna['circuit'].upper()}</span>
    <span class="badge">{wx['race_date']}</span>
    {driver.get('name', driver_key)} &nbsp;|&nbsp; {team.get('name', team_key)}
    &nbsp;&nbsp;&#183;&nbsp;&nbsp; Generated {generated}
  </div>
</div>

<!-- Top stats row -->
<div class="grid-4">
  <div class="card">
    <h3>Weather</h3>
    <div style="margin-bottom:8px;">
      <span class="condition-badge" style="background:{cond_color}20; color:{cond_color}; border:1px solid {cond_color};">
        {condition}
      </span>
    </div>
    <div class="stat-row"><span class="stat-label">Temp</span><span class="stat-val">{wx_f.get('temp_c','?')}°C</span></div>
    <div class="stat-row"><span class="stat-label">Rain prob</span><span class="stat-val">{wx_f.get('precip_prob_pct','?')}%</span></div>
    <div class="stat-row"><span class="stat-label">Wind</span><span class="stat-val">{wx_f.get('wind_kph','?')} kph</span></div>
    <div class="stat-row"><span class="stat-label">Humidity</span><span class="stat-val">{wx_f.get('humidity_pct','?')}%</span></div>
    <div style="margin-top:10px; color:#888; font-size:11px;">{wx.get('strategy_implication','')}</div>
  </div>

  <div class="card">
    <h3>Track DNA</h3>
    <div class="stat-row"><span class="stat-label">Total laps</span><span class="stat-val">{dna['total_laps']}</span></div>
    <div class="stat-row"><span class="stat-label">Pit delta</span><span class="stat-val">{dna['pit_delta_seconds']}s</span></div>
    <div class="stat-row"><span class="stat-label">SC per race</span><span class="stat-val">{sc.get('sc_per_race','?')}</span></div>
    <div class="stat-row"><span class="stat-label">VSC per race</span><span class="stat-val">{sc.get('vsc_per_race','?')}</span></div>
    <div class="stat-row"><span class="stat-label">Red flag/race</span><span class="stat-val">{sc.get('red_flag_per_race','?')}</span></div>
  </div>

  <div class="card">
    <h3>Driver — {driver_key}</h3>
    <div class="stat-row"><span class="stat-label">Name</span><span class="stat-val">{driver.get('name','?')}</span></div>
    <div class="stat-row"><span class="stat-label">Tyre mgmt</span><span class="stat-val">{driver.get('tyre_mgmt','?')}</span></div>
    <div class="stat-row"><span class="stat-label">Overtaking</span><span class="stat-val">{driver.get('overtaking','?')}</span></div>
    <div class="stat-row"><span class="stat-label">Wet perf</span><span class="stat-val">{driver.get('wet_delta','?')}</span></div>
    <div class="stat-row"><span class="stat-label">L1 incident</span><span class="stat-val">{driver.get('incident_rate','?')}</span></div>
  </div>

  <div class="card">
    <h3>Team — {team_key}</h3>
    <div class="stat-row"><span class="stat-label">Strategy</span><span class="stat-val" style="font-size:12px;">{team.get('strategy_style','?')}</span></div>
    <div class="stat-row"><span class="stat-label">Typical stop</span><span class="stat-val">{team.get('typical_first_stop','?')}</span></div>
    <div class="stat-row"><span class="stat-label">Undercut threat</span><span class="stat-val">{team.get('undercut_risk','?')}</span></div>
    <div style="margin-top:10px; color:#888; font-size:11px;">{team.get('tyre_tendency','')}</div>
  </div>
</div>

<!-- Charts -->
<div class="grid-2" style="padding-top:0;">
  <div class="chart-card"><div id="chart-compounds"></div></div>
  <div class="chart-card"><div id="chart-pitstops"></div></div>
  <div class="chart-card"><div id="chart-sc"></div></div>
  <div class="chart-card"><div id="chart-teams"></div></div>
</div>

<!-- Scenario engine -->
<div class="scenarios-section">
  <h2>&#9889; Scenario Engine</h2>
  <div class="scenarios-meta">
    Race state &nbsp;&#183;&nbsp; Lap <strong>{inp.current_lap}/{inp.total_laps}</strong>
    &nbsp;&#183;&nbsp; P<strong>{inp.current_position}</strong>
    &nbsp;&#183;&nbsp; <strong>{inp.current_compound}</strong> ({inp.tyre_age_laps} laps old)
    &nbsp;&#183;&nbsp; Gap ahead: <strong>{inp.gap_ahead_seconds}s</strong>
    &nbsp;&#183;&nbsp; Gap behind: <strong>{inp.gap_behind_seconds}s</strong>
  </div>
  {scenario_cards_html}
</div>

<div class="footer">F1 Strategy Intelligence Tool &nbsp;&#183;&nbsp; Data: FastF1 / OpenF1 / Open-Meteo &nbsp;&#183;&nbsp; {generated}</div>

<script>
{chart_js}
</script>
</body>
</html>"""

    output_path.write_text(html, encoding="utf-8")
    return output_path
