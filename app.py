import streamlit as st
import pandas as pd
import json
import os
import threading
from datetime import datetime, date, timedelta
import plotly.express as px
from streamlit_gsheets import GSheetsConnection

# ==========================================
# 1. DATENBANK & GOOGLE SHEETS VERBINDUNG
# ==========================================
conn = st.connection("gsheets", type=GSheetsConnection)
gs_write_lock = threading.Lock() # Verhindert Schreibfehler bei gleichzeitigem Zugriff

# ==========================================
# 2. CACHING (DATEN LADEN)
# ==========================================
@st.cache_data(ttl=3600)
def load_config_gs():
    """Lädt Aufgaben/Punkte-Definitionen (1h Cache)."""
    try:
        dt = conn.read(worksheet="WG_Tasks", ttl=3600)
        return dt
    except:
        return pd.DataFrame([{"Category": "Quick", "Task": "Flaschen", "Points": 3}])

@st.cache_data(ttl=3600)
def load_users_gs():
    """Lädt Benutzer (1h Cache)."""
    try:
        du = conn.read(worksheet="WG_Users", ttl=3600)
        return du
    except:
        return pd.DataFrame([{"Name": "Admin", "Team": "LiSa", "IsAdmin": True}])

@st.cache_data(ttl=10)
def load_points_gs():
    """Lädt die aktuellen Punktestände (10s Cache)."""
    try:
        dp = conn.read(worksheet="WG_Data", ttl=10)
        return dp
    except:
        return pd.DataFrame(columns=["timestamp", "user", "team", "task", "points"])

# ==========================================
# 3. APP SETUP & CSS (DEIN DESIGN)
# ==========================================
st.set_page_config(page_title="WG App", page_icon="🏔️", layout="centered")

# Wir nutzen f-Strings für CSS, damit wir Variablen einbauen können.
# WICHTIG: CSS-Klammern müssen wegen f-String doppelt {{ }} sein!
st.markdown(f"""
<style>
    /* BASIS STYLING */
    .stButton > button {{
        width: 100%; min-height: 65px; font-size: 1.2rem; font-weight: bold;
        border-radius: 12px; border: 2px solid #f0f2f6; background-color: white; color: #31333F;
    }}
    
    /* DAS DESIGN FÜR DEN VERLAUF (Wiederhergestellt) */
    .result-card {{
        padding: 15px; border-radius: 12px; background-color: #f8f9fb;
        border-left: 6px solid #ff4b4b; margin-bottom: 12px; color: #31333F;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    }}
    .win-card {{ border-left-color: #29b045 !important; }}

    /* SIDEBAR NAVIGATION (Schmale Icon-Leiste links) */
    [data-testid="stSidebar"] {{ display: none !important; }} /* Standard-Sidebar weg */
    
    [data-testid="stRadio"] {{
        position: fixed !important; top: 0 !important; left: 0 !important;
        width: 70px !important; height: 100vh !important;
        background-color: #ffffff !important; z-index: 999999 !important;
        border-right: 1px solid #eee; display: flex; flex-direction: column;
        align-items: center; padding-top: 40px !important;
    }}
    
    /* Icons in der Leiste */
    [data-testid="stRadio"] label {{
        justify-content: center !important; padding: 20px 0 !important;
    }}
    [data-testid="stRadio"] p {{ font-size: 1.8rem !important; transition: 0.2s; }}
    [data-baseweb="radio"] > div:first-child {{ display: none !important; }} /* Radio-Punkt verstecken */

    /* PLATZ FÜR INHALT (70px links frei lassen für die Leiste) */
    .block-container {{ 
        padding-left: 85px !important; padding-right: 20px !important;
        padding-top: 2rem !important;
    }}

    /* STREAMLIT BRANDING VERSTECKEN */
    header, footer, [data-testid="stHeader"] {{ visibility: hidden !important; height: 0; }}
</style>

<link rel="manifest" href="./static/manifest.json">
<script>
    // Service Worker für die Installation (PWA)
    if ('serviceWorker' in navigator) {{
        window.addEventListener('load', function() {{
            navigator.serviceWorker.register('./static/sw.js');
        }});
    }}
    
    // Auto-Login Logik
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

# ==========================================
# 4. NAVIGATIONSLOGIK
# ==========================================
# Initialisierung Session State
if "authenticated" not in st.session_state:
    st.session_state.update({"user": None, "authenticated": False, "is_admin": False})

# Login-Check
if not st.session_state.authenticated:
    # --- LOGIN PAGE (Zentriert) ---
    st.markdown("<style>.block-container { max-width: 400px !important; margin: 0 auto !important; padding-left: 20px !important; }</style>", unsafe_allow_html=True)
    st.title("🏔️ WG Login")
    u_in = st.text_input("User")
    p_in = st.text_input("Passwort", type="password")
    if st.button("Login"):
        df_u = load_users_gs()
        match = df_u[df_u["Name"].str.lower() == u_in.lower()]
        if not match.empty and p_in == st.secrets["passwords"].get(match.iloc[0]["Name"]):
            st.session_state.update({"user": match.iloc[0]["Name"], "team": match.iloc[0]["Team"], "is_admin": bool(match.iloc[0]["IsAdmin"]), "authenticated": True})
            st.rerun()
    st.stop()

# --- SIDEBAR ICON LOGIK ---
nav_icons = {"📊": "Stand", "➕": "Punkte", "📜": "Verlauf", "🚪": "Exit"}
sel_icon = st.radio("Nav", list(nav_icons.keys()), label_visibility="collapsed")
page = nav_icons[sel_icon]

# Dynamisches Vergrößern des gewählten Icons
icon_idx = list(nav_icons.keys()).index(sel_icon) + 1
st.markdown(f"<style>[data-testid='stRadio'] label:nth-of-type({icon_idx}) p {{ font-size: 2.8rem !important; }}</style>", unsafe_allow_html=True)

# ==========================================
# 5. SEITEN-INHALTE
# ==========================================

if page == "Stand":
    st.subheader(f"Hi {st.session_state.user}! 👋")
    # Hier kommt dein Plotly Chart rein...
    st.info("Hier ist die Übersicht der aktuellen Woche.")

elif page == "Verlauf":
    st.subheader("📜 Dein Verlauf")
    df = load_points_gs()
    if not df.empty:
        # Beispiel für die Karten-Logik (wie du sie mochtest)
        # Wir simulieren hier die Anzeige der letzten Zyklen
        for i in range(3): 
            # card_class wird grün (win-card), wenn dein Team führt
            card_class = "win-card" if i == 0 else "" 
            st.markdown(f"""
                <div class="result-card {card_class}">
                    <strong>Zyklus {10-i}</strong><br>
                    <small>Team LiSa: 45 Pkt | Team SaNi: 30 Pkt</small><br>
                    <span style="font-size: 0.8rem;">Strafe: Paket A (Boden/Bad)</span>
                </div>
            """, unsafe_allow_html=True)
    else:
        st.write("Noch keine Daten vorhanden.")

elif page == "Exit":
    st.markdown("<script>localStorage.removeItem('wg_user');</script>", unsafe_allow_html=True)
    st.session_state.authenticated = False
    st.rerun()
