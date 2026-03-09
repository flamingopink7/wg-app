import streamlit as st
import pandas as pd
import json
import os
import threading
from datetime import datetime, date, timedelta
import plotly.express as px
from streamlit_gsheets import GSheetsConnection

# --- GOOGLE SHEETS CONNECTION ---
conn = st.connection("gsheets", type=GSheetsConnection)

# Global lock to safely append data in the background without overwrites
gs_write_lock = threading.Lock()

# --- CONFIG & CACHING ---
@st.cache_data(ttl=3600)
def load_config_gs():
    """Load tasks with long lifecycle (1h cache)."""
    try:
        dt = conn.read(worksheet="WG_Tasks", ttl=3600)
        mapping = {c.lower(): c for c in dt.columns}
        for k, v in {"category": "Category", "task": "Task", "points": "Points"}.items():
            if k in mapping: dt = dt.rename(columns={mapping[k]: v})
        return dt
    except:
        return pd.DataFrame([{"Category": "Quick", "Task": "Flaschen", "Points": 3}])

@st.cache_data(ttl=3600)
def load_users_gs():
    """Load users with long lifecycle (1h cache)."""
    try:
        du = conn.read(worksheet="WG_Users", ttl=3600)
        mapping = {c.lower(): c for c in du.columns}
        for k, v in {"name": "Name", "team": "Team", "isadmin": "IsAdmin"}.items():
            if k in mapping: du = du.rename(columns={mapping[k]: v})
        return du
    except:
        return pd.DataFrame([{"Name": "Livio", "Team": "LiSa", "IsAdmin": True}])

@st.cache_data(ttl=10)
def load_points_gs():
    """Load points with short lifecycle (10s cache)."""
    try:
        dp = conn.read(worksheet="WG_Data", ttl=10)
        for c in ["timestamp", "user", "team", "task", "points"]:
            if c not in dp.columns: dp[c] = None
        return dp
    except:
        return pd.DataFrame(columns=["timestamp", "user", "team", "task", "points"])

def get_active_points():
    """Returns points filtered by optimistic UI additions and deletions."""
    dp = load_points_gs()
    
    # Merge optimistic additions
    if "optimistic_points" in st.session_state and st.session_state.optimistic_points:
        opt_df = pd.DataFrame(st.session_state.optimistic_points)
        dp = pd.concat([dp, opt_df], ignore_index=True)
        dp = dp.drop_duplicates(subset=["timestamp"], keep="last")
        
    # Filter out deletions
    if not dp.empty and "deleted_timestamps" in st.session_state and st.session_state.deleted_timestamps:
        dp = dp[~dp["timestamp"].isin(st.session_state.deleted_timestamps)]
    return dp

def add_points_gs(user, team, task, points):
    """Writes to Google Sheets instantly in background, applies Optimistic UI locally."""
    ts = datetime.now().isoformat()
    if "optimistic_points" not in st.session_state: st.session_state.optimistic_points = []
    
    # Optimistic local UI update
    st.session_state.optimistic_points.append({
        "timestamp": ts, "user": user, "team": team, "task": task, "points": int(points)
    })
    st.toast("✅ Erledigt!", icon="🎉")
    
    def _write_task():
        # Ensure only one thread writes at a time to prevent data loss
        with gs_write_lock:
            try:
                load_points_gs.clear() 
                dp = load_points_gs() 
                new_row = pd.DataFrame([{
                    "timestamp": ts,
                    "user": user,
                    "team": team,
                    "task": task,
                    "points": int(points)
                }])
                updated = pd.concat([dp, new_row], ignore_index=True)
                conn.update(worksheet="WG_Data", data=updated)
                load_points_gs.clear() # Clear again so next UI refresh gets new data instantly
            except Exception as e:
                print(f"Background save failed: {e}")
                
    # Run in background to prevent the UI from freezing/greying out
    threading.Thread(target=_write_task).start()

def delete_points_gs(timestamp_val):
    """Safely deletes an entry by its timestamp in the background."""
    if "deleted_timestamps" in st.session_state:
        st.session_state.deleted_timestamps.add(timestamp_val)
        
    def _delete_task():
        with gs_write_lock:
            try:
                load_points_gs.clear() 
                dp = load_points_gs()
                updated = dp[dp["timestamp"] != timestamp_val]
                conn.update(worksheet="WG_Data", data=updated)
                load_points_gs.clear()
            except Exception as e:
                print(f"Background delete failed: {e}")
                
    threading.Thread(target=_delete_task).start()
    st.toast("🗑️ Gelöscht!", icon="🧹")

def save_tasks_gs(df_tasks):
    conn.update(worksheet="WG_Tasks", data=df_tasks)
    load_config_gs.clear()

# --- HELPER FUNCTIONS ---
def get_base_date(): return date(2024, 1, 1)

def get_cycle_info(target_date):
    base_date = get_base_date()

    delta = (target_date - base_date).days
    cycle_num = delta // 14
    start = base_date + timedelta(days=cycle_num * 14)
    end = start + timedelta(days=13)
    pkg = "Paket A (Boden, Bad, K.-Deep, Chem.)" if cycle_num % 2 == 0 else "Paket B (Boden, Staub, Entsorg., Kühls.)"
    return start, end, pkg, cycle_num

# --- APP SETUP ---
# NEU: Name ist jetzt "WG" und das Icon ein Berg
st.set_page_config(page_title="WG", page_icon="🏔️", layout="centered")

st.markdown("""
<style>
    /* Generelles Button-Styling */
    .stButton > button {
        width: 100%; min-height: 65px; font-size: 1.2rem; font-weight: bold;
        border-radius: 12px; border: 2px solid #f0f2f6; background-color: white; color: #31333F;
        touch-action: manipulation;
    }
    /* Hide the 'Running...' overlay for a smoother feel */
    [data-testid="stStatusWidget"] { visibility: hidden !important; }
    .stTable { font-size: 0.8rem; }
    .result-card {
        padding: 12px; border-radius: 12px; background-color: #f8f9fb;
        border-left: 5px solid #ff4b4b; margin-bottom: 10px; color: #31333F;
    }
    .win-card { border-left-color: #29b045; }

    /* UI Fixierung Full-Height NO BOUNCE */
    html, body, [data-testid="stAppViewContainer"] {
        height: 100vh;
        width: 100vw;
        margin: 0;
        padding: 0;
        overflow: hidden !important;
        position: fixed;
        overscroll-behavior-y: none;
    }
    
    /* Content Bereich nach rechts verschieben, damit die Side-Bar Platz hat */
    .block-container { 
        height: 100vh;
        overflow-y: auto;
        padding-left: 85px !important;  /* Platz für die neue Sidebar */
        padding-right: 15px !important;
        padding-top: 1.5rem !important; 
        padding-bottom: 80px !important;
        -webkit-overflow-scrolling: touch;
    }

    /* --- NEUE STATISCHE ICON-SEITENLEISTE LINKS --- */
    /* Wir zwingen die Radio-Buttons in eine vertikale, fixe Leiste am linken Rand */
    [data-testid="stRadio"] {
        position: fixed !important;
        top: 0 !important;
        left: 0 !important;
        width: 70px !important;
        height: 100vh !important;
        background-color: var(--secondary-background-color) !important;
        z-index: 999999 !important;
        padding-top: 30px !important;
        border-right: 1px solid #ddd;
        display: flex;
        flex-direction: column;
        align-items: center;
        box-shadow: 2px 0 5px rgba(0,0,0,0.05);
    }
    
    /* Die Radio-Buttons optisch zu großen Icons machen */
    [data-testid="stRadio"] label {
        justify-content: center;
        padding: 15px 0 !important;
        cursor: pointer;
        margin-bottom: 5px;
        width: 100%;
    }
    
    /* Die Icons riesig machen */
    [data-testid="stRadio"] p {
        font-size: 2rem !important;
        margin: 0 !important;
    }

    /* Den unsichtbaren Klick-Kreis des Radios verstecken */
    [data-testid="stRadio"] div[role="radio"] {
        display: none !important;
    }

    /* --- STEALTH MODE: Verstecke Streamlit-Elemente --- */
    /* Das echte Hamburger-Icon und die alte Sidebar töten */
    [data-testid="collapsedControl"] { display: none !important; }
    [data-testid="stSidebar"] { display: none !important; }
    
    [data-testid="stHeader"], header { display: none !important; }
    [data-testid="stToolbar"] { display: none !important; }
    [data-testid="stDecoration"] { display: none !important; }
    [data-testid="stFooter"], footer { display: none !important; }

    /* RADIKALE MASSNAHME gegen mobile Logos & Badges unten rechts */
    iframe[title*="streamlit"], iframe[src*="manage"] {
        display: none !important;
        pointer-events: none !important;
        opacity: 0 !important;
    }
    .stAppDeployButton, [data-testid="stManageAppBadge"], #MainMenu {
        display: none !important;
        visibility: hidden !important;
    }
</style>

<link rel="manifest" href="data:application/manifest+json;base64,eyJuYW1lIjoiV0ciLCJzaG9ydF9uYW1lIjoiV0ciLCJzdGFydF91cmwiOiIvIiwiZGlzcGxheSI6InN0YW5kYWxvbmUiLCJiYWNrZ3JvdW5kX2NvbG9yIjoiI2ZmZmZmZiIsInRoZW1lX2NvbG9yIjoiI2ZmZmZmZiIsImljb25zIjpbeyJzcmMiOiJkYXRhOmltYWdlL3N2Zyt4bWwsJTNDc3ZnIHhtbG5zPSdodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2Zycgdmlld0JveD0nMCAwIDEwMCAxMDAnJTNFJTNDdGV4dCB5PScuOWVtJyBmb250LXNpemU9JzkwJyUzReKbrO+4jyUzQy90ZXh0JTNFJTNDL3N2ZyUzRSIsInNpemVzIjoiMTkyeDE5MiA1MTJ4NTEyIiwidHlwZSI6ImltYWdlL3N2Zyt4bWwiLCJwdXJwb3NlIjoiYW55IG1hc2thYmxlIn1dfQ==">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="mobile-web-app-capable" content="yes">
<meta name="theme-color" content="#ffffff">
<script>
    if ('serviceWorker' in navigator) {
        window.addEventListener('load', function() {
            navigator.serviceWorker.register('app/static/sw.js');
        });
    }

    const urlParams = new URLSearchParams(window.location.search);
    const urlUser = urlParams.get('user');
    if (urlUser) {
        localStorage.setItem('wg_user', urlUser);
    } else {
        const savedUser = localStorage.getItem('wg_user');
        if (savedUser && window.location.pathname === "/") {
            window.location.replace('/?user=' + savedUser);
        }
    }
</script>
""", unsafe_allow_html=True)

# Data Load
df_tasks = load_config_gs()
df_users = load_users_gs()

# --- AUTH & AUTO-LOGIN LOGIK ---
if "user" not in st.session_state:
    st.session_state.update({"user": None, "authenticated": False, "is_admin": False, "deleted_timestamps": set()})

# 1. Prüfen, ob eine URL mitgegeben wurde
if not st.session_state.authenticated:
    qu = st.query_params.get("user")
    if qu:
        match = df_users[df_users["Name"].str.lower() == qu.lower()]
        if not match.empty:
            ui = match.iloc[0]
            st.session_state.update({"user": ui["Name"], "team": ui["Team"], "is_admin": bool(ui["IsAdmin"]), "authenticated": True})
            st.rerun()

# 2. LocalStorage Check
if not st.session_state.authenticated:
    st.markdown("""
    <script>
        const savedUser = localStorage.getItem('wg_user');
        if (savedUser && !window.location.search.includes('user=')) {
            window.location.search = '?user=' + savedUser;
        }
    </script>
    """, unsafe_allow_html=True)

# 3. Login Screen
if not st.session_state.authenticated:
    st.title("🏔️ WG Login")
    username_input = st.text_input("Benutzername")
    pw = st.text_input("Passwort", type="password")
    
    if st.button("Anmelden"):
        if username_input and pw:
            match = df_users[df_users["Name"].str.lower() == username_input.strip().lower()]
            if not match.empty:
                real_username = match.iloc[0]["Name"]
                if pw == st.secrets["passwords"].get(real_username):
                    ui = match.iloc[0]
                    st.session_state.update({"user": real_username, "team": ui["Team"], "is_admin": bool(ui["IsAdmin"]), "authenticated": True})
                    st.query_params["user"] = real_username
                    st.rerun()
                else: 
                    st.error("Falsches Passwort")
            else:
                st.error("Benutzername nicht gefunden")
        else:
            st.warning("Bitte Benutzername und Passwort eingeben")
    st.stop()

# 4. Save to LocalStorage
if st.session_state.authenticated:
    st.markdown(f"""
    <script>
        localStorage.setItem('wg_user', '{st.session_state.user}');
    </script>
    """, unsafe_allow_html=True)


# --- NEUE ICON-NAVIGATION ---
# Dictionary: Icon -> Logischer Name
nav_options = {"📊": "Stand", "➕": "Punkte", "📜": "Verlauf"}
if st.session_state.is_admin:
    nav_options["🛠"] = "Admin"
nav_options["🚪"] = "Abmelden"

# Das CSS von oben packt diesen Radio-Button an den linken Bildschirmrand!
selected_icon = st.radio("Menü", list(nav_options.keys()), label_visibility="collapsed")
active_tab = nav_options[selected_icon]


# --- CONTENT DISPLAY REGION ---
st.write(f"Hallo **{st.session_state.user}**! 👋")

if active_tab == "Stand":
    df = get_active_points() 
    cs, ce, pkg, cn = get_cycle_info(date.today())
    kw_start = cs.isocalendar()[1]
    kw_end = ce.isocalendar()[1]
    st.info(f"📍 **KW{kw_start} & KW{kw_end}** | Strafe: {pkg}")
    
    if not df.empty:
        df['Datum'] = pd.to_datetime(df['timestamp']).dt.date
        curr = df[(df['Datum'] >= cs) & (df['Datum'] <= ce)]
    else: curr = pd.DataFrame()

    if not curr.empty:
        agg = curr.groupby(["team", "user"])["points"].sum().reset_index()
        
        my_team = st.session_state.team
        other_team = "SaNi" if my_team == "LiSa" else "LiSa"
        team_order = [my_team, other_team]

        fig = px.bar(agg, x="team", y="points", color="user", barmode='stack', height=350,
                     text="user",
                     category_orders={"team": team_order},
                     color_discrete_sequence=["#FF4B4B", "#1C83E1", "#29B045", "#FFD700"])
        
        fig.update_traces(textposition='inside', textfont=dict(color='white', size=14))
        fig.update_layout(showlegend=False, margin=dict(l=0, r=0, t=10, b=0), xaxis_title=None, yaxis_title=None)
        st.plotly_chart(fig, use_container_width=True, config={'staticPlot': True})
        
        ps, pl = agg[agg['team']=='SaNi']['points'].sum(), agg[agg['team']=='LiSa']['points'].sum()
        my_pts = pl if my_team == "LiSa" else ps
        other_pts = ps if my_team == "LiSa" else pl

        st.markdown(f"""
        <div style="display: flex; justify-content: space-around; text-align: center; margin-top: 5px;">
            <div style="flex: 1;">
                <p style="font-size: 0.9rem; margin: 0; color: #555;">{my_team}</p>
                <p style="font-size: 1.8rem; font-weight: bold; margin: 0; color: var(--text-color);">{my_pts} P</p>
            </div>
            <div style="flex: 1;">
                <p style="font-size: 0.9rem; margin: 0; color: #555;">{other_team}</p>
                <p style="font-size: 1.8rem; font-weight: bold; margin: 0; color: var(--text-color);">{other_pts} P</p>
            </div>
        </div>
        """, unsafe_allow_html=True)
    else: st.warning("Noch keine Punkte.")

elif active_tab == "Punkte":
    current_tasks = load_config_gs()
    cat_order = ["Quick", "Wartung", "Main", "Strafaufgaben"]
    
    for cat in cat_order:
        with st.expander(f"📍 {cat}", expanded=False):
            ct = current_tasks[current_tasks["Category"] == cat]
            if not ct.empty:
                for r in ct.itertuples():
                    if st.button(f"{r.Task} ({r.Points}P)", key=f"p_{r.Index}"):
                        add_points_gs(st.session_state.user, st.session_state.team, r.Task, r.Points)
    
    st.markdown("---")
    with st.expander("⏱️ Letzte Einträge bearbeiten", expanded=False):
        dp = get_active_points()
        if not dp.empty:
            dp['Datum'] = pd.to_datetime(dp['timestamp']).dt.date
            if st.session_state.is_admin:
                recent = dp.sort_values("timestamp", ascending=False).head(50)
            else:
                today = date.today()
                recent = dp[(dp['Datum'] == today) & (dp['user'] == st.session_state.user)].sort_values("timestamp", ascending=False)
                
            if not recent.empty:
                for _, r in recent.iterrows():
                    can_delete = st.session_state.is_admin or (r['user'] == st.session_state.user)
                    if pd.notna(r['timestamp']):
                        c1, c2, c3 = st.columns([3, 4, 1])
                        try:
                            dt_str = datetime.fromisoformat(r['timestamp']).strftime("%d.%m. %H:%M")
                        except:
                            dt_str = str(r['timestamp'])[:10]
                        
                        c1.caption(dt_str)
                        c2.markdown(f"**{r['user']}**: {r['task']} ({r['points']}P)")
                        if can_delete:
                            if c3.button("🗑️", key=f"del_pt_{r['timestamp']}"):
                                delete_points_gs(r['timestamp'])
            else:
                st.info("Heute noch keine Einträge gemacht.")
        else:
            st.info("Noch keine Einträge vorhanden.")

elif active_tab == "Verlauf":
    df = get_active_points()
    if not df.empty:
        df['Datum'] = pd.to_datetime(df['timestamp']).dt.date
        _, _, _, n = get_cycle_info(date.today())
        for i in range(n - 1, max(-1, n - 6), -1):
            s, e, p, _ = get_cycle_info(get_base_date() + timedelta(days=i*14))
            d = df[(df['Datum'] >= s) & (df['Datum'] <= e)]
            vs, vl = d[d["team"] == "SaNi"]["points"].sum(), d[d["team"] == "LiSa"]["points"].sum()
            loser = "SaNi" if vs < vl else ("LiSa" if vl < vs else "Unentschieden")
            
            kw_s = s.isocalendar()[1]
            kw_e = e.isocalendar()[1]
            
            card_class = "win-card" if (st.session_state.team != loser or loser == "Unentschieden") else "result-card"
            st.markdown(f"""<div class="result-card {card_class}">
                <strong>KW{kw_s} & KW{kw_e}</strong> ({s.strftime('%d.%m')} - {e.strftime('%d.%m')})<br>
                <small>SaNi: {vs} | LiSa: {vl} | <b>Strafe: {loser}</b><br>{p}</small>
            </div>""", unsafe_allow_html=True)
    else: st.info("Keine Daten.")

elif active_tab == "Admin" and st.session_state.is_admin:
    st.subheader("Aufgaben editieren")
    cat_order = ["Quick", "Wartung", "Main", "Strafaufgaben"]
    
    with st.form("adm_task_form"):
        updated = []
        new_tasks = []
        
        for cat in cat_order:
            with st.expander(f"⚙️ {cat}", expanded=False):
                ct = df_tasks[df_tasks["Category"] == cat].copy()
                if not ct.empty:
                    for i, r in ct.iterrows():
                        col1, col2 = st.columns([3, 1])
                        pt_val = 0 if pd.isna(r['Points']) else int(r['Points'])
                        new_p = col1.number_input(r['Task'], value=pt_val, key=f"upd_{i}")
                        if not col2.checkbox("🗑️ löschen", key=f"del_{i}"):
                            updated.append({"Category": cat, "Task": r['Task'], "Points": new_p})
                
                st.markdown(f"**Neue Aufgabe in {cat}:**")
                c1, c2 = st.columns([3, 1])
                nt = c1.text_input("Name", key=f"new_n_{cat}")
                np = c2.number_input("Punkte", 10, key=f"new_p_{cat}")
                if nt: new_tasks.append({"Category": cat, "Task": nt, "Points": int(np)})
        
        if st.form_submit_button("Speichern"):
            final = pd.DataFrame(updated + new_tasks)
            save_tasks_gs(final)
            st.toast("✅ Gespeichert!", icon="💾")
            st.rerun()

elif active_tab == "Abmelden":
    st.markdown("<script>localStorage.removeItem('wg_user');</script>", unsafe_allow_html=True)
    st.session_state.update({"user": None, "authenticated": False})
    if "user" in st.query_params:
        del st.query_params["user"]
    st.rerun()
