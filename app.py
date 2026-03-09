import streamlit as st
import pandas as pd
import json
import os
import threading
from datetime import datetime, date, timedelta
import plotly.express as px
from streamlit_gsheets import GSheetsConnection

# --- DATENBANK VERBINDUNG ---
conn = st.connection("gsheets", type=GSheetsConnection)
gs_write_lock = threading.Lock()

# --- DATEN LADEN ---
@st.cache_data(ttl=3600)
def load_config_gs():
    try:
        dt = conn.read(worksheet="WG_Tasks", ttl=3600)
        return dt
    except:
        return pd.DataFrame([{"Category": "Quick", "Task": "Flaschen", "Points": 3}])

@st.cache_data(ttl=3600)
def load_users_gs():
    try:
        du = conn.read(worksheet="WG_Users", ttl=3600)
        return du
    except:
        return pd.DataFrame([{"Name": "Admin", "Team": "LiSa", "IsAdmin": True}])

@st.cache_data(ttl=10)
def load_points_gs():
    try:
        dp = conn.read(worksheet="WG_Data", ttl=10)
        return dp
    except:
        return pd.DataFrame(columns=["timestamp", "user", "team", "task", "points"])

# --- APP SETUP & URSPRÜNGLICHES DESIGN ---
st.set_page_config(page_title="WG App", page_icon="🏆", layout="centered")

st.markdown(f"""
<style>
    /* URSPRÜNGLICHE BUTTONS */
    .stButton > button {{
        width: 100%; min-height: 65px; font-size: 1.2rem; font-weight: bold;
        border-radius: 12px; border: 2px solid #f0f2f6; background-color: white; color: #31333F;
        touch-action: manipulation;
    }}

    /* URSPRÜNGLICHER VERLAUF (Karten-Design) */
    .result-card {{
        padding: 12px; border-radius: 12px; background-color: #f8f9fb;
        border-left: 5px solid #ff4b4b; margin-bottom: 10px; color: #31333F;
    }}
    .win-card {{ border-left-color: #29b045; }}

    /* FIXIERTES LAYOUT OHNE BOUNCE */
    html, body, [data-testid="stAppViewContainer"] {{
        height: 100vh; width: 100vw; margin: 0; padding: 0;
        overflow: hidden !important; position: fixed; overscroll-behavior-y: none;
    }}
    .block-container {{ 
        height: 100vh; overflow-y: auto;
        padding-top: 1.5rem !important; padding-bottom: 100px !important;
        -webkit-overflow-scrolling: touch;
    }}
    
    /* BOTTOM TABS (Wieder unten wie gewünscht) */
    [data-testid="stTabs"] [data-baseweb="tab-list"] {{
        position: fixed; bottom: 0px; left: 0px; width: 100vw;
        background-color: white; z-index: 999999;
        box-shadow: 0 -2px 10px rgba(0,0,0,0.1);
        padding-top: 10px; padding-bottom: env(safe-area-inset-bottom, 20px);
        display: flex; justify-content: space-around;
    }}
    [data-testid="stTabs"] [data-baseweb="tab-list"] button {{
        flex: 1; padding: 10px 0; color: #31333F !important;
    }}

    /* STEALTH MODE (Logos weg) */
    [data-testid="stHeader"], header, footer, .stAppDeployButton, [data-testid="stManageAppBadge"] {{
        display: none !important; visibility: hidden !important;
    }}
</style>

<script>
    // PWA & AUTO-LOGIN
    if ('serviceWorker' in navigator) {{
        window.addEventListener('load', function() {{
            navigator.serviceWorker.register('./static/sw.js');
        }});
    }}

    const urlParams = new URLSearchParams(window.location.search);
    const urlUser = urlParams.get('user');
    if (urlUser) {{
        localStorage.setItem('wg_user', urlUser);
    }} else {{
        const savedUser = localStorage.getItem('wg_user');
        if (savedUser && window.location.pathname === "/") {{
            window.location.replace('/?user=' + savedUser);
        }}
    }}
</script>
""", unsafe_allow_html=True)

# --- AUTHENTIFIZIERUNG ---
df_users = load_users_gs()
if "authenticated" not in st.session_state:
    st.session_state.update({"user": None, "authenticated": False, "is_admin": False})

if not st.session_state.authenticated:
    # Auto-Login über URL
    qu = st.query_params.get("user")
    if qu:
        match = df_users[df_users["Name"].str.lower() == qu.lower()]
        if not match.empty:
            ui = match.iloc[0]
            st.session_state.update({"user": ui["Name"], "team": ui["Team"], "is_admin": bool(ui["IsAdmin"]), "authenticated": True})
            st.rerun()

    # Manueller Login
    st.title("🔐 Login")
    u_name = st.text_input("Benutzername")
    u_pw = st.text_input("Passwort", type="password")
    if st.button("Anmelden"):
        match = df_users[df_users["Name"].str.lower() == u_name.strip().lower()]
        if not match.empty and u_pw == st.secrets["passwords"].get(match.iloc[0]["Name"]):
            st.session_state.update({"user": match.iloc[0]["Name"], "team": match.iloc[0]["Team"], "is_admin": bool(match.iloc[0]["IsAdmin"]), "authenticated": True})
            st.query_params["user"] = match.iloc[0]["Name"]
            st.rerun()
        else: st.error("Daten inkorrekt")
    st.stop()

# --- HAUPTSEITE (EINGELOGGT) ---
st.write(f"Hallo **{st.session_state.user}**! 👋")

# URSPRÜNGLICHE TABS
tabs = st.tabs(["📊 Stand", "➕ Punkte", "📜 Verlauf"])

with tabs[0]:
    # Dein Dashboard/Plotly Chart...
    st.info("Aktueller Stand der WG")

with tabs[1]:
    # Deine Aufgaben-Buttons...
    df_t = load_config_gs()
    for cat in ["Quick", "Wartung", "Main"]:
        with st.expander(cat):
            tasks = df_t[df_t["Category"] == cat]
            for index, row in tasks.iterrows():
                if st.button(f"{row['Task']} ({row['Points']}P)", key=f"btn_{index}"):
                    # add_points_gs Logik hier...
                    st.toast(f"{row['Task']} eingetragen!")

with tabs[2]:
    # VERLAUF IM ALTEN DESIGN
    st.markdown("""
        <div class="result-card win-card">
            <strong>Letzter Zyklus</strong><br>
            Team LiSa hat gewonnen!
        </div>
        <div class="result-card">
            <strong>Vorletzter Zyklus</strong><br>
            Team SaNi hat gewonnen.
        </div>
    """, unsafe_allow_html=True)

if st.sidebar.button("Logout"):
    st.markdown("<script>localStorage.removeItem('wg_user');</script>", unsafe_allow_html=True)
    st.session_state.authenticated = False
    st.rerun()
