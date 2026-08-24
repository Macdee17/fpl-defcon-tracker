import pandas as pd
import requests
import streamlit as st
from concurrent.futures import ThreadPoolExecutor

st.set_page_config(page_title="FPL Friend", layout="wide", page_icon="⚽")

st.title("⚽ FPL Friend")
st.markdown("Your all-in-one suite for DEFCON tracking, live match monitoring, and expected performance analytics (xG, xA, xGC).")

# Hex dual-color combinations for Premier League teams
def color_teams(val):
    colors = {
        'ARS': 'background-color: #EF0107; color: #FFFFFF;',
        'AVL': 'background-color: #670E36; color: #95BFE5;',
        'BOU': 'background-color: #DA291C; color: #000000;',
        'BRE': 'background-color: #E30613; color: #FFFFFF;',
        'BHA': 'background-color: #0057B8; color: #FFFFFF;',
        'CHE': 'background-color: #034694; color: #FFFFFF;',
        'COV': 'background-color: #87CEEB; color: #000000;',
        'CRY': 'background-color: #1B458F; color: #C8102E;',
        'EVE': 'background-color: #003399; color: #FFFFFF;',
        'FUL': 'background-color: #000000; color: #FFFFFF;',
        'HUL': 'background-color: #F39C12; color: #000000;',
        'IPS': 'background-color: #0000FF; color: #FFFFFF;',
        'LEE': 'background-color: #FFFFFF; color: #0000FF;',
        'LIV': 'background-color: #C8102E; color: #FFFFFF;',
        'MCI': 'background-color: #6CABDD; color: #1C2C5B;',
        'MUN': 'background-color: #DA291C; color: #000000;',
        'NEW': 'background-color: #241F20; color: #FFFFFF;',
        'NFO': 'background-color: #E53233; color: #FFFFFF;',
        'SUN': 'background-color: #EB1C24; color: #FFFFFF;',
        'TOT': 'background-color: #132257; color: #FFFFFF;'
    }
    return colors.get(val, '')

# 1. Fetch Metadata from FPL API
@st.cache_data(ttl=3600)
def get_bootstrap_data():
    url = "https://fantasy.premierleague.com/api/bootstrap-static/"
    res = requests.get(url).json()
    
    current_gw = next((event["id"] for event in res["events"] if event["is_current"]), 1)
    
    team_cs = {}
    for el in res["elements"]:
        t_id = el["team"]
        cs = el.get("clean_sheets", 0)
        team_cs[t_id] = max(team_cs.get(t_id, 0), cs)

    teams = {
        t["id"]: {
            "name": t["short_name"], 
            "full_name": t["name"],
            "clean_sheets": team_cs.get(t["id"], 0)
        } for t in res["teams"]
    }
    
    pos_map = {2: "DEF", 3: "MID"}
    players = {}
    raw_elements = []

    for el in res["elements"]:
        if el["minutes"] > 0:
            raw_elements.append(el)

        if el["element_type"] in pos_map:
            players[el["id"]] = {
                "name": el["web_name"],
                "position": pos_map[el["element_type"]],
                "team_id": el["team"],
                "team": teams[el["team"]]["name"],
                "team_cs": teams[el["team"]]["clean_sheets"],
                "price": el["now_cost"] / 10.0,
                "starts": el.get("starts", 0),
                "minutes": el.get("minutes", 0)
            }
            
    df_raw = pd.DataFrame(raw_elements)
    df_raw['Team'] = df_raw['team'].map({k: v['name'] for k, v in teams.items()})
    for col in ['expected_goals', 'expected_assists', 'expected_goal_involvements', 'expected_goals_conceded']:
        df_raw[col] = df_raw[col].astype(float)
        
    return current_gw, players, teams, df_raw

# 2. Fetch Live Gameweek Data
def get_live_data(gw, players_dict):
    url = f"https://fantasy.premierleague.com/api/event/{gw}/live/"
    res = requests.get(url).json()
    
    data = []
    for el in res["elements"]:
        p_id = el["id"]
        if p_id in players_dict:
            stats = el["stats"]
            pos = players_dict[p_id]["position"]
            team = players_dict[p_id]["team"]
            price = players_dict[p_id]["price"]
            
            cbi = stats.get("clearances_blocks_interceptions", 0)
            tackles = stats.get("tackles", 0)
            recoveries = stats.get("recoveries", 0)
            goals_conceded = stats.get("goals_conceded", 0)
            goals_scored = stats.get("goals_scored", 0)
            assists = stats.get("assists", 0)
            
            target = 10 if pos == "DEF" else 12
            actions = (cbi + tackles) if pos == "DEF" else (cbi + tackles + recoveries)
            
            needed = target - actions
            status = "✅ HIT" if needed <= 0 else f"{needed} needed"
            
            data.append({
                "Player": players_dict[p_id]["name"],
                "Team": team,
                "Position": pos,
                "Price (£m)": price,
                "Live Actions": actions,
                "Target": target,
                "Goals": goals_scored,
                "Assists": assists,
                "Goals Conceded": goals_conceded,
                "Status": status
            })
    return pd.DataFrame(data)

# 3. Helper for Player History
def fetch_player_history(p_id):
    url = f"https://fantasy.premierleague.com/api/element-summary/{p_id}/"
    res = requests.get(url)
    if res.status_code == 200:
        return p_id, res.json().get("history", [])
    return p_id, []

# 4. Compile Season DEFCON Data
@st.cache_data(ttl=3600)
def get_season_defcon_data(players_dict):
    data = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        results = executor.map(fetch_player_history, players_dict.keys())
        
    for p_id, history in results:
        pos = players_dict[p_id]["position"]
        target = 10 if pos == "DEF" else 12
        
        total_actions = 0
        apps = 0
        hits = 0
        total_gc = 0
        total_goals = 0
        total_assists = 0
        
        for gw in history:
            mins = gw.get("minutes", 0)
            if mins > 0:
                apps += 1
                cbi = gw.get("clearances_blocks_interceptions", 0)
                tackles = gw.get("tackles", 0)
                recoveries = gw.get("recoveries", 0)
                gc = gw.get("goals_conceded", 0)
                g = gw.get("goals_scored", 0)
                a = gw.get("assists", 0)
                
                actions = (cbi + tackles) if pos == "DEF" else (cbi + tackles + recoveries)
                total_actions += actions
                total_gc += gc
                total_goals += g
                total_assists += a
                if actions >= target:
                    hits += 1
                    
        starts = players_dict[p_id]["starts"]
        total_mins = players_dict[p_id]["minutes"]
        team_cs = players_dict[p_id]["team_cs"]
        price = players_dict[p_id]["price"]
        
        hit_rate = (hits / apps * 100) if apps > 0 else 0.0
        per_90 = (total_actions / total_mins * 90) if total_mins > 0 else 0.0
        avg_gc = (total_gc / apps) if apps > 0 else 0.0
        
        data.append({
            "Player": players_dict[p_id]["name"],
            "Team": players_dict[p_id]["team"],
            "Position": pos,
            "Price (£m)": price,
            "Team Clean Sheets": team_cs,
            "Starts": starts,
            "Minutes Played": total_mins,
            "Total Actions": total_actions,
            "DEFCON Hits": hits,
            "DEFCON / 90": round(per_90, 2),
            "Hit Rate (%)": round(hit_rate, 2),
            "Goals": total_goals,
            "Assists": total_assists,
            "Total GC": total_gc,
            "Avg GC / Game": round(avg_gc, 2)
        })
        
    return pd.DataFrame(data)

# --- Main App Logic ---
try:
    gw, players, teams, df_xg_raw = get_bootstrap_data()

    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "🔴 Live DEFCON", 
        "📊 Season DEFCON", 
        "🛡️ Team DEFCON", 
        "🏃‍♂️ Player Expected Stats", 
        "⚽ Team Expected Stats"
    ])

    # --- TAB 1: LIVE DEFCON ---
    with tab1:
        st.subheader(f"Gameweek {gw} Live Action Tracker")
        if st.button("🔄 Refresh Live Data"):
            st.rerun()
            
        df_live = get_live_data(gw, players)
        df_live_sorted = df_live.sort_values(by="Live Actions", ascending=False)
        
        st.dataframe(
            df_live_sorted.style.map(color_teams, subset=['Team']).format({'Price (£m)': '£{:.1f}m'}),
            use_container_width=True,
            height=800
        )

    # --- TAB 2: SEASON DEFCON ---
    with tab2:
        st.subheader("Individual Season DEFCON Totals & Hit Rates")
        with st.spinner("Fetching season history..."):
            df_season = get_season_defcon_data(players)
        
        df_season_active = df_season[df_season["Minutes Played"] > 0]
        df_season_sorted = df_season_active.sort_values(by="Hit Rate (%)", ascending=False)
        
        st.dataframe(
            df_season_sorted.style.map(color_teams, subset=['Team']).format({
                'Price (£m)': '£{:.1f}m',
                'DEFCON / 90': '{:.2f}',
                'Hit Rate (%)': '{:.2f}',
                'Avg GC / Game': '{:.2f}'
            }), 
            use_container_width=True,
            height=800
        )

    # --- TAB 3: TEAM DEFCON ---
    with tab3:
        st.subheader("Team-Level Defensive Performance")
        df_season_agg = get_season_defcon_data(players)
        
        df_def = df_season_agg[df_season_agg["Position"] == "DEF"].groupby("Team").agg({
            "Total Actions": "sum", "DEFCON Hits": "sum"
        }).rename(columns={"Total Actions": "DEF Actions", "DEFCON Hits": "DEF DEFCONs"})
        
        df_mid = df_season_agg[df_season_agg["Position"] == "MID"].groupby("Team").agg({
            "Total Actions": "sum", "DEFCON Hits": "sum"
        }).rename(columns={"Total Actions": "MID Actions", "DEFCON Hits": "MID DEFCONs"})
        
        df_cs = df_season_agg.groupby("Team").agg({"Team Clean Sheets": "first"})
        
        df_teams = df_cs.join(df_def).join(df_mid).fillna(0).reset_index()
        int_cols = ["DEF Actions", "DEF DEFCONs", "MID Actions", "MID DEFCONs", "Team Clean Sheets"]
        df_teams[int_cols] = df_teams[int_cols].astype(int)
        
        df_teams["Total Actions"] = df_teams["DEF Actions"] + df_teams["MID Actions"]
        df_teams["Total DEFCONs"] = df_teams["DEF DEFCONs"] + df_teams["MID DEFCONs"]
        
        cols = ["Team", "Team Clean Sheets", "DEF Actions", "MID Actions", "Total Actions", "DEF DEFCONs", "MID DEFCONs", "Total DEFCONs"]
        df_teams_sorted = df_teams.sort_values(by="Total DEFCONs", ascending=False)[cols]
        
        st.dataframe(
            df_teams_sorted.style.map(color_teams, subset=['Team']),
            use_container_width=True,
            height=800
        )

    # --- TAB 4: PLAYER EXPECTED STATS ---
    with tab4:
        st.subheader("Player Expected Metrics (xG, xA, xGI)")
        
        # Checkbox directly above table
        per_90_player = st.checkbox("☑️ Show stats Per 90 Minutes", value=False, key="p_per90")
        
        df_xg = df_xg_raw.copy()
        if per_90_player:
            df_xg['90s'] = df_xg['minutes'] / 90
            df_xg['Goals'] = (df_xg['goals_scored'] / df_xg['90s']).round(2)
            df_xg['xG'] = (df_xg['expected_goals'] / df_xg['90s']).round(2)
            df_xg['Assists'] = (df_xg['assists'] / df_xg['90s']).round(2)
            df_xg['xA'] = (df_xg['expected_assists'] / df_xg['90s']).round(2)
            df_xg['xGI'] = (df_xg['expected_goal_involvements'] / df_xg['90s']).round(2)
            df_xg['GC'] = (df_xg['goals_conceded'] / df_xg['90s']).round(2)
            df_xg['xGC'] = (df_xg['expected_goals_conceded'] / df_xg['90s']).round(2)
        else:
            df_xg['Goals'] = df_xg['goals_scored'].astype(float)
            df_xg['xG'] = df_xg['expected_goals'].round(2)
            df_xg['Assists'] = df_xg['assists'].astype(float)
            df_xg['xA'] = df_xg['expected_assists'].round(2)
            df_xg['xGI'] = df_xg['expected_goal_involvements'].round(2)
            df_xg['GC'] = df_xg['goals_conceded'].astype(float)
            df_xg['xGC'] = df_xg['expected_goals_conceded'].round(2)

        player_cols = ['web_name', 'Team', 'minutes', 'Goals', 'xG', 'Assists', 'xA', 'xGI', 'GC', 'xGC']
        player_df = df_xg[player_cols].rename(columns={'web_name': 'Player', 'minutes': 'Mins'})
        
        player_num_cols = ['Goals', 'xG', 'Assists', 'xA', 'xGI', 'GC', 'xGC']
        
        st.dataframe(
            player_df.sort_values(by='xGI', ascending=False)
            .style.map(color_teams, subset=['Team'])
            .format('{:.2f}', subset=player_num_cols),
            use_container_width=True,
            hide_index=True,
            height=800
        )

    # --- TAB 5: TEAM EXPECTED STATS ---
    with tab5:
        st.subheader("Team Attacking Threat & Defensive Solidity")
        
        # Checkbox directly above table
        per_90_team = st.checkbox("☑️ Show stats Per 90 Minutes", value=False, key="t_per90")
        
        team_df = df_xg_raw.groupby('Team')[['goals_scored', 'expected_goals', 'assists', 'expected_assists', 'expected_goal_involvements', 'goals_conceded', 'expected_goals_conceded', 'minutes']].sum().reset_index()
        
        if per_90_team:
            team_df['team_90s'] = (team_df['minutes'] / 11) / 90
            team_df['Goals'] = (team_df['goals_scored'] / team_df['team_90s']).round(2)
            team_df['xG'] = (team_df['expected_goals'] / team_df['team_90s']).round(2)
            team_df['Assists'] = (team_df['assists'] / team_df['team_90s']).round(2)
            team_df['xA'] = (team_df['expected_assists'] / team_df['team_90s']).round(2)
            team_df['xGI'] = (team_df['expected_goal_involvements'] / team_df['team_90s']).round(2)
            team_df['GC'] = ((team_df['goals_conceded'] / 11) / team_df['team_90s']).round(2)
            team_df['xGC'] = ((team_df['expected_goals_conceded'] / 11) / team_df['team_90s']).round(2)
        else:
            team_df['Goals'] = team_df['goals_scored'].astype(float)
            team_df['xG'] = team_df['expected_goals'].round(2)
            team_df['Assists'] = team_df['assists'].astype(float)
            team_df['xA'] = team_df['expected_assists'].round(2)
            team_df['xGI'] = team_df['expected_goal_involvements'].round(2)
            team_df['GC'] = (team_df['goals_conceded'] / 11).round(2)
            team_df['xGC'] = (team_df['expected_goals_conceded'] / 11).round(2)

        team_display = team_df[['Team', 'Goals', 'xG', 'Assists', 'xA', 'xGI', 'GC', 'xGC']]
        
        team_num_cols = ['Goals', 'xG', 'Assists', 'xA', 'xGI', 'GC', 'xGC']
        
        st.dataframe(
            team_display.sort_values(by='xGI', ascending=False)
            .style.map(color_teams, subset=['Team'])
            .format('{:.2f}', subset=team_num_cols),
            use_container_width=True,
            hide_index=True,
            height=800
        )

except Exception as e:
    st.error(f"Error loading FPL data: {e}")