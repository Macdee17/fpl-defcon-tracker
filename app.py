import pandas as pd
import requests
import streamlit as st
from concurrent.futures import ThreadPoolExecutor

st.set_page_config(page_title="FPL DEFCON Tracker", layout="wide", page_icon="⚽")
st.title("⚽ FPL DEFCON Tracker")

# Hex dual-color combinations for 2026/2027 Premier League teams (Background & Text)
def color_teams(val):
    colors = {
        'ARS': 'background-color: #EF0107; color: #FFFFFF;', # Arsenal (Red & White)
        'AVL': 'background-color: #670E36; color: #95BFE5;', # Aston Villa (Claret & Sky Blue)
        'BOU': 'background-color: #DA291C; color: #000000;', # Bournemouth (Red & Black)
        'BRE': 'background-color: #E30613; color: #FFFFFF;', # Brentford (Red & White)
        'BHA': 'background-color: #0057B8; color: #FFFFFF;', # Brighton (Blue & White)
        'CHE': 'background-color: #034694; color: #FFFFFF;', # Chelsea (Blue & White)
        'COV': 'background-color: #87CEEB; color: #000000;', # Coventry City (Sky Blue & Black)
        'CRY': 'background-color: #1B458F; color: #C8102E;', # Crystal Palace (Blue & Red)
        'EVE': 'background-color: #003399; color: #FFFFFF;', # Everton (Blue & White)
        'FUL': 'background-color: #000000; color: #FFFFFF;', # Fulham (Black & White)
        'HUL': 'background-color: #F39C12; color: #000000;', # Hull City (Amber & Black)
        'IPS': 'background-color: #0000FF; color: #FFFFFF;', # Ipswich Town (Blue & White)
        'LEE': 'background-color: #FFFFFF; color: #0000FF;', # Leeds United (White & Blue)
        'LIV': 'background-color: #C8102E; color: #FFFFFF;', # Liverpool (Red & White)
        'MCI': 'background-color: #6CABDD; color: #1C2C5B;', # Man City (Sky Blue & Navy)
        'MUN': 'background-color: #DA291C; color: #000000;', # Man United (Red & Black)
        'NEW': 'background-color: #241F20; color: #FFFFFF;', # Newcastle (Black & White)
        'NFO': 'background-color: #E53233; color: #FFFFFF;', # Nottingham Forest (Red & White)
        'SUN': 'background-color: #EB1C24; color: #FFFFFF;', # Sunderland (Red & White)
        'TOT': 'background-color: #132257; color: #FFFFFF;'  # Tottenham (Navy & White)
    }
    return colors.get(val, '')

# 1. Fetch metadata
@st.cache_data(ttl=3600)
def get_metadata():
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
            "clean_sheets": team_cs.get(t["id"], 0)
        } for t in res["teams"]
    }
    
    pos_map = {2: "DEF", 3: "MID"}
    players = {}
    
    for el in res["elements"]:
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
    return current_gw, players, teams

# 2. Fetch Live Gameweek Data with Goals & Assists
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

# 3. Helper for individual player history
def fetch_player_history(p_id):
    url = f"https://fantasy.premierleague.com/api/element-summary/{p_id}/"
    res = requests.get(url)
    if res.status_code == 200:
        return p_id, res.json().get("history", [])
    return p_id, []

# 4. Compile Season Data with Goals & Assists
@st.cache_data(ttl=3600)
def get_season_data(players_dict):
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

# --- UI Execution ---
try:
    gw, players, teams = get_metadata()
    
    tab1, tab2, tab3 = st.tabs(["🔴 Live Gameweek", "📊 Season Totals", "🛡️ Team DEFCON"])
    
    with tab1:
        st.subheader(f"Gameweek {gw} Live Action Tracker")
        
        if st.button("🔄 Refresh Live Data"):
            st.rerun()
            
        df_live = get_live_data(gw, players)
        df_live_sorted = df_live.sort_values(by="Live Actions", ascending=False)
        
        st.dataframe(
            df_live_sorted.style.map(color_teams, subset=['Team']).format({'Price (£m)': '£{:.1f}m'}),
            use_container_width=True,
            height=750,
            column_config={
                "Live Actions": st.column_config.NumberColumn(
                    "Live Actions",
                    help="Calculated as: (Clearances + Blocks + Interceptions + Tackles) for DEF | Includes Recoveries for MID."
                ),
                "Target": st.column_config.NumberColumn(
                    "Target",
                    help="DEFCON Threshold: 10 defensive actions for Defenders, 12 for Midfielders."
                ),
                "Goals": st.column_config.NumberColumn(
                    "Goals",
                    help="Goals scored in the current live match."
                ),
                "Assists": st.column_config.NumberColumn(
                    "Assists",
                    help="Assists provided in the current live match."
                ),
                "Goals Conceded": st.column_config.NumberColumn(
                    "Goals Conceded",
                    help="Goals conceded in real-time. Defenders lose -1 point for every 2 goals conceded."
                ),
                "Status": st.column_config.TextColumn(
                    "Status",
                    help="Indicates whether DEFCON was achieved or the remaining actions needed."
                )
            }
        )
        
    with tab2:
        st.subheader("Individual Season Totals & Hit Rates")
        with st.spinner("Fetching season history... (Cached for 1 hour)"):
            df_season = get_season_data(players)
        
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
            height=750,
            column_config={
                "Total Actions": st.column_config.NumberColumn(
                    "Total Actions",
                    help="Sum of all CBI + Tackles (+ Recoveries for MID) across all matches played."
                ),
                "DEFCON Hits": st.column_config.NumberColumn(
                    "DEFCON Hits",
                    help="Total number of gameweeks the player reached their position target (10+ or 12+)."
                ),
                "DEFCON / 90": st.column_config.NumberColumn(
                    "DEFCON / 90",
                    help="Normalized defensive actions per 90 minutes played."
                ),
                "Hit Rate (%)": st.column_config.NumberColumn(
                    "Hit Rate (%)",
                    help="Percentage of matches played in which the player hit DEFCON."
                ),
                "Goals": st.column_config.NumberColumn(
                    "Goals",
                    help="Total goals scored by the player this season."
                ),
                "Assists": st.column_config.NumberColumn(
                    "Assists",
                    help="Total assists provided by the player this season."
                ),
                "Total GC": st.column_config.NumberColumn(
                    "Total GC",
                    help="Total Goals Conceded while player was on the pitch."
                ),
                "Avg GC / Game": st.column_config.NumberColumn(
                    "Avg GC / Game",
                    help="Average Goals Conceded per appearance."
                )
            }
        )

    with tab3:
        st.subheader("Team-Level Defensive Performance")
        
        df_season_agg = get_season_data(players)
        
        df_def = df_season_agg[df_season_agg["Position"] == "DEF"].groupby("Team").agg({
            "Total Actions": "sum",
            "DEFCON Hits": "sum"
        }).rename(columns={"Total Actions": "DEF Actions", "DEFCON Hits": "DEF DEFCONs"})
        
        df_mid = df_season_agg[df_season_agg["Position"] == "MID"].groupby("Team").agg({
            "Total Actions": "sum",
            "DEFCON Hits": "sum"
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
            height=750,
            column_config={
                "DEF Actions": st.column_config.NumberColumn(
                    "DEF Actions",
                    help="Combined defensive actions (CBI + Tackles) generated by all defenders in the team."
                ),
                "MID Actions": st.column_config.NumberColumn(
                    "MID Actions",
                    help="Combined defensive actions (CBI + Tackles + Recoveries) generated by all midfielders in the team."
                ),
                "Total Actions": st.column_config.NumberColumn(
                    "Total Actions",
                    help="Combined sum of DEF Actions + MID Actions across the entire team."
                ),
                "DEF DEFCONs": st.column_config.NumberColumn(
                    "DEF DEFCONs",
                    help="Total DEFCON thresholds hit by defenders on this team."
                ),
                "MID DEFCONs": st.column_config.NumberColumn(
                    "MID DEFCONs",
                    help="Total DEFCON thresholds hit by midfielders on this team."
                ),
                "Total DEFCONs": st.column_config.NumberColumn(
                    "Total DEFCONs",
                    help="Combined total DEFCON hits (DEF + MID) achieved by the team."
                )
            }
        )

except Exception as e:
    st.error(f"Error connecting to FPL API: {e}")