import streamlit as st
import pandas as pd
import altair as alt
from datetime import datetime, date
import statsapi
from pybaseball import playerid_reverse_lookup, statcast_batter

import requests
import time
import unicodedata
import re
import os

# Cloudflare設定（Secretsから取得する推奨版）
ACCOUNT_ID = os.environ.get("ACCOUNT_ID")
TOKEN = os.environ.get("TOKEN")

TOKYO_START   = datetime(2025, 3, 18)
TOKYO_2       = datetime(2025, 3, 19)
REGULAR_START = datetime(2025, 3, 27)

ROYAL_BLUE = "#1E90FF"
ORANGE     = "#FF8000"

st.set_page_config(layout="wide", page_title="MLB 2025 Home Run Pace Tracker")
st.title("MLB Home Run Pace Comparison — 2025 Season (Dynamic Rosters)")

@st.cache_data(ttl=12 * 60 * 60)
def get_team_info():
    teams_raw = statsapi.get('teams', {'sportIds': 1})['teams']
    team_info = {}
    for t in teams_raw:
        if t['active']:
            abbr = t['abbreviation']
            team_info[abbr] = {
                'id': t['id'],
                'name': t['name'],
                'logo': f"https://www.mlbstatic.com/team-logos/{t['id']}.svg",
                'slug': t.get('teamName', '').lower().replace(' ', '-'),
                'division': t['division']['name']
            }
    return team_info

team_info = get_team_info()
team_abbrs = sorted(team_info.keys())
team_names = [team_info[a]['name'] for a in team_abbrs]
abbr_by_name = {team_info[a]['name']: a for a in team_abbrs}

@st.cache_data(ttl=12 * 60 * 60)
def build_star_players():
    teams_raw = statsapi.get('teams', {'sportIds': 1})['teams']
    active_teams = [t for t in teams_raw if t['active']]
    stars = []
    for team in active_teams:
        data = statsapi.get('team_roster', {
            'teamId': team['id'],
            'rosterType': 'active'
        })
        for player in data.get('roster', []):
            person = player.get('person', {})
            name   = person.get('fullName')
            pid    = person.get('id')
            if name and pid:
                stars.append((name, pid, team['abbreviation']))
    return stars

star_players = build_star_players()
player_map   = {name: (pid, team) for name, pid, team in star_players}

def get_player_image(pid: int) -> str:
    return (f"https://img.mlbstatic.com/mlb-photos/image/upload/"
            f"w_180,q_100/v1/people/{pid}/headshot/67/current.png")

def fetch_hr_log(pid: int, start: datetime, end: datetime, team_abbr: str) -> pd.DataFrame:
    df = statcast_batter(start_dt=start.strftime('%Y-%m-%d'),
                         end_dt=end.strftime('%Y-%m-%d'),
                         player_id=str(pid))
    if df.empty:
        return df
    df['Date'] = pd.to_datetime(df['game_date'])
    tokyo_days = [TOKYO_START, TOKYO_2]
    if team_abbr in {'LAD', 'CHC'}:
        mask = df['Date'].isin(tokyo_days) | (df['Date'] >= REGULAR_START)
    else:
        mask = df['Date'] >= REGULAR_START
    df = df.loc[mask]
    df_hr = (df[df['events'] == 'home_run']
             .copy()
             .sort_values('Date')
             .reset_index(drop=True))
    if df_hr.empty:
        return df_hr
    df_hr['HR No'] = df_hr.index + 1
    df_hr['MM-DD'] = df_hr['Date'].dt.strftime('%m-%d')
    def pid2name(p):
        try:
            t = playerid_reverse_lookup([p], key_type='mlbam')
            return t['name_first'][0] + ' ' + t['name_last'][0]
        except Exception:
            return str(p)
    df_hr['Pitcher'] = df_hr['pitcher'].apply(
        lambda x: pid2name(x) if pd.notna(x) else '')
    return df_hr

def normalize_name(name):
    name = name.lower()
    name = unicodedata.normalize("NFKD", name)
    name = "".join([c for c in name if not unicodedata.combining(c)])
    name = re.sub(r"[^a-z0-9 ]", "", name)
    name = re.sub(r"\bjr\b", "", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name

def fuzzy_player_lookup(ai_name, player_map):
    norm_ai = normalize_name(ai_name)
    for k in player_map:
        if normalize_name(k) == norm_ai:
            return player_map[k]
    ai_parts = set(norm_ai.split())
    for k in player_map:
        k_parts = set(normalize_name(k).split())
        if ai_parts & k_parts:
            return player_map[k]
    return None

# ------------------------ Sidebar UI --------------------------
st.sidebar.header("Select Players and Date Range")

st.sidebar.markdown(
    "<span style='color:#d97706; font-weight:bold;'>⚠️ Note:</span> "
    "Only players currently on the official MLB active roster are shown in the dropdowns. "
    "Players not on an active roster (e.g., due to injury or other status) will not appear.",
    unsafe_allow_html=True
)

default_team1 = "Los Angeles Dodgers"
default_player1 = "Shohei Ohtani"
team1_name = st.sidebar.selectbox(
    "First Player's Team", team_names,
    index=team_names.index(default_team1) if default_team1 in team_names else 0)
team1_abbr = abbr_by_name[team1_name]

team1_players = [n for n, _, t in star_players if t == team1_abbr]
player1_name = st.sidebar.selectbox(
    "First Player", team1_players,
    index=team1_players.index(default_player1) if default_player1 in team1_players else 0)

default_team2 = "New York Yankees"
default_player2 = "Aaron Judge"
team2_name = st.sidebar.selectbox(
    "Second Player's Team", team_names,
    index=team_names.index(default_team2) if default_team2 in team_names else 0)
team2_abbr = abbr_by_name[team2_name]

team2_players = [n for n, _, t in star_players if t == team2_abbr]
player2_name = st.sidebar.selectbox(
    "Second Player", team2_players,
    index=team2_players.index(default_player2) if default_player2 in team2_players else 0)

start_date = st.sidebar.date_input("Start date", TOKYO_START)
end_date   = st.sidebar.date_input("End date", date.today())

no_game_msgs = []
if team1_abbr not in {'LAD', 'CHC'} and datetime.combine(start_date, datetime.min.time()) < REGULAR_START:
    no_game_msgs.append(f"No official MLB games for {player1_name} ({team1_abbr}) before 2025-03-27.")
if team2_abbr not in {'LAD', 'CHC'} and datetime.combine(start_date, datetime.min.time()) < REGULAR_START:
    no_game_msgs.append(f"No official MLB games for {player2_name} ({team2_abbr}) before 2025-03-27.")
if no_game_msgs:
    for msg in no_game_msgs:
        st.sidebar.warning(msg)

st.sidebar.markdown("#### MLB Teams (links to official sites)")

division_map = {
    'American League': {'East': [], 'Central': [], 'West': []},
    'National League': {'East': [], 'Central': [], 'West': []}
}
division_name_map = {
    'American League East': ('American League', 'East'),
    'American League Central': ('American League', 'Central'),
    'American League West': ('American League', 'West'),
    'National League East': ('National League', 'East'),
    'National League Central': ('National League', 'Central'),
    'National League West': ('National League', 'West')
}
for abbr in team_abbrs:
    info = team_info[abbr]
    div_full = info['division']
    league, division = division_name_map[div_full]
    url = f"https://www.mlb.com/{info['slug']}"
    entry = (
        f'<a href="{url}" target="_blank">'
        f'<img src="{info["logo"]}" width="22" style="vertical-align:middle;margin-right:4px;">'
        f'{abbr}</a>'
    )
    division_map[league][division].append(entry)

def render_division_block_sidebar(division, entries):
    st.sidebar.markdown(f"**{division}**")
    col_count = 6
    rows = [entries[i:i+col_count] for i in range(0, len(entries), col_count)]
    table_html = '<table style="border-collapse:collapse;border:none;">'
    for row in rows:
        table_html += '<tr style="border:none;">' + ''.join(
            f'<td style="padding:2px 8px;border:none;background:transparent;">{cell}</td>' for cell in row
        ) + '</tr>'
    table_html += '</table>'
    st.sidebar.markdown(table_html, unsafe_allow_html=True)

for league in ['American League', 'National League']:
    st.sidebar.markdown(f"### {league}")
    for division in ['East', 'Central', 'West']:
        entries = division_map[league][division]
        if entries:
            render_division_block_sidebar(division, entries)

# ----------------------------------------
# Main content
# ----------------------------------------
p1_id, team1_code = player_map[player1_name]
p2_id, team2_code = player_map[player2_name]

col1, col2 = st.columns(2)
logs = {}
color_map = {player1_name: ROYAL_BLUE, player2_name: ORANGE}

for col, pid, name, code in [
    (col1, p1_id, player1_name, team1_code),
    (col2, p2_id, player2_name, team2_code)
]:
    with col:
        st.subheader(f"{name} ({team_info[code]['name']})")
        st.image(get_player_image(pid), width=100)
        df_hr = fetch_hr_log(
            pid,
            datetime.combine(start_date, datetime.min.time()),
            end_date,
            code
        )
        logs[name] = df_hr
        if df_hr.empty:
            st.info("No HR data in selected period.")
            continue
        st.dataframe(
            df_hr[['HR No', 'MM-DD', 'home_team', 'away_team', 'Pitcher']],
            use_container_width=True)
        chart = (alt.Chart(df_hr)
                 .mark_line(point=False, color=color_map[name])
                 .encode(
                     x=alt.X('Date:T', title='Date (MM-DD)', axis=alt.Axis(format='%m-%d')),
                     y=alt.Y('HR No:Q', title='Cumulative HRs', axis=alt.Axis(format='d'))
                 ) +
                 alt.Chart(df_hr)
                 .mark_point(size=60, filled=True, color=color_map[name])
                 .encode(x='Date:T', y='HR No:Q'))
        st.altair_chart(chart.properties(title=f"{name} HR Pace"), use_container_width=True)

if all(not logs[n].empty for n in [player1_name, player2_name]):
    st.subheader("Head-to-Head Comparison")
    merged = pd.concat([
        logs[player1_name].assign(Player=player1_name),
        logs[player2_name].assign(Player=player2_name)
    ])
    comparison = (
        alt.Chart(merged)
        .mark_line(point=False)
        .encode(
            x=alt.X('Date:T', title='Date (MM-DD)', axis=alt.Axis(format='%m-%d')),
            y=alt.Y('HR No:Q', title='Cumulative HRs', axis=alt.Axis(format='d')),
            color=alt.Color('Player:N', scale=alt.Scale(
                domain=[player1_name, player2_name],
                range=[ROYAL_BLUE, ORANGE])),
            tooltip=['Player', 'Date', 'HR No', 'Pitcher']
        )
        + alt.Chart(merged)
        .mark_point(size=60, filled=True)
        .encode(x='Date:T', y='HR No:Q', color='Player:N')
    )
    st.altair_chart(comparison, use_container_width=True)

    # === AI SUGGEST FEATURE START ===
    st.markdown("### 🔎 AI Next Recommendation")
    st.markdown(
        "Based on the two players currently shown, here are AI-personalized suggestions for the next interesting player pairs to search. The recommendation is tailored for you, leveraging shared traits, storylines, NOT random."
    )
    st.warning(
        "This answer is generated by AI (Llama 3) and may contain factual errors or differ from actual MLB history. Please always check reliable sources such as the official site. If you find an error or want another suggestion, just press the button below again.",
        icon="⚠️"
    )
    if "last_suggest" not in st.session_state:
        st.session_state["last_suggest"] = None
    if "suggest_error" not in st.session_state:
        st.session_state["suggest_error"] = None

    def ai_suggest_pairs(p1, p2, tries=3, timeout_sec=60):
        endpoint = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/ai/run/@cf/meta/llama-3-8b-instruct"
        headers = {"Authorization": f"Bearer {TOKEN}"}
        prompt = (
            "IMPORTANT: If there is no clear or meaningful connection, shared award, rivalry, team, nationality, or major story between the two players as explicitly stated in the opening summary table or first paragraph of each player's English Wikipedia page, simply state: 'There is no significant connection between these players.' "
            "Do NOT invent, speculate, or exaggerate any story, postseason moment, or relationship. "
            "If the only possible comparison is generic (e.g., both are young or both are hitters), say so and do not force a comparison. "
            f"Now, after comparing MLB players {p1} and {p2}, suggest one new pair of MLB hitters (not pitchers) who hit 20 or more home runs in the 2024 season, and are currently active as of the 2025 season. Do NOT include the same pair (regardless of order) as above. "
            "If you mention an MVP, Rookie of the Year, or Home Run King title, give only the correct year and award, as written in Wikipedia. "
            "Cite birth country, position, or award only from the infobox or opening paragraph of the player’s Wikipedia page. Do NOT include any statistics or numbers. "
            "Only mention walk-off home runs or postseason heroics if explicitly documented on Wikipedia. "
            "Limit the explanation to 40 words. "
            "Output only as:\n"
            "Pair: <PlayerA> and <PlayerB>\nReason: <40-words fact-based reason or 'There is no significant connection between these players.'>"
        ).replace("{p1}", p1).replace("{p2}", p2)
        for _ in range(tries):
            try:
                resp = requests.post(
                    endpoint,
                    headers=headers,
                    json={"messages": [{"role": "user", "content": prompt}]},
                    timeout=timeout_sec,
                )
                content = resp.json().get("result", {}).get("response", "")
                m = re.search(r"Pair:\s*(.+?)\nReason:\s*(.+)", content, re.DOTALL)
                if m:
                    pair_str, reason = m.groups()
                    players = [p.strip() for p in re.split(r" and | & ", pair_str)]
                    return [{"players": players, "reason": reason.strip()}], None
            except Exception as e:
                return None, f"Error: {str(e)}"
        return None, "No suitable suggestion found. Please try again."

    button_label = "Suggest / Retry AI Recommendation"
    if st.button(button_label):
        with st.spinner("AI is thinking... (max 60 seconds)"):
            t0 = time.time()
            results, error = ai_suggest_pairs(player1_name, player2_name)
            t1 = time.time()
            if error:
                st.session_state["suggest_error"] = error
                st.session_state["last_suggest"] = None
            else:
                st.session_state["suggest_error"] = None
                st.session_state["last_suggest"] = results
            st.write(f"⏱️ AI response time: {int(t1-t0)} sec")

    st.markdown(
        "**[Suggest / Retry AI Recommendation]**: Press this button to get AI suggestions. If you see a mistake or want a different answer, just press again!"
    )

    if st.session_state.get("last_suggest"):
        for rec in st.session_state["last_suggest"]:
            players = rec["players"]
            subcols = st.columns(len(players))
            for idx, name in enumerate(players):
                with subcols[idx]:
                    pid = None
                    if name in player_map:
                        pid, _ = player_map[name]
                    else:
                        fuzzy = fuzzy_player_lookup(name, player_map)
                        if fuzzy:
                            pid, _ = fuzzy
                    if pid:
                        st.image(get_player_image(pid), width=80)
                    st.markdown(f"**{name}**")
            st.markdown(f"**Reason:** {rec['reason']}")
    elif st.session_state.get("suggest_error"):
        st.error(st.session_state["suggest_error"])

st.caption("Data: Statcast (pybaseball) • Rosters: MLB-StatsAPI • Built with Streamlit")
