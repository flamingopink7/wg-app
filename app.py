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
# Verbindet sich mit Google Sheets über die Streamlit Secrets
conn = st.connection("gsheets", type=GSheetsConnection)

# Ein "Schloss" (Lock) für Hintergrundprozesse, damit sich Speicherbefehle nicht überschneiden
gs_write_lock = threading.Lock()

# ==========================================
# 2. CACHING & DATEN LADEN
# ==========================================
# Caching bedeutet, dass Streamlit nicht bei jedem Klick Google fragt, sondern sich Daten für X Sekunden merkt.

@st.cache_data(ttl=3600)
def load_config_gs():
    """Lädt die Aufgaben (Tasks) und cacht sie für 1 Stunde (3600s)."""
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
    """Lädt die Benutzerliste und cacht sie für 1 Stunde."""
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
    """Lädt die Punkte-Tabelle. Kurzer Cache (10s), damit neue Punkte schnell sichtbar sind."""
    try:
        dp = conn.read(worksheet="WG_Data", ttl=10)
        for c in ["timestamp", "user", "team", "task", "points"]:
            if c not in dp.columns: dp[c] = None
        return dp
    except:
        return pd.DataFrame(columns=["timestamp", "user", "team", "task", "points"])

# ==========================================
# 3. GESCHÄFTSLOGIK (PUNKTE & BERECHNUNG)
# ==========================================

def get_active_points():
    """Kombiniert die echten Google-Daten mit lokalen (noch nicht gespeicherten) Klicks."""
    dp = load_points_gs()
    # Füge Punkte hinzu, die gerade erst geklickt wurden (Optimistic UI)
    if "optimistic_points" in st.session_state and st.session_state.optimistic_points:
        opt_df = pd.DataFrame(st.session_state.optimistic_points)
        dp = pd.concat([dp, opt_df], ignore_index=True)
        dp = dp.drop_duplicates(subset=["timestamp"], keep="last")
        
    # Entferne Punkte, die lokal gelöscht, aber noch nicht bei Google gelöscht wurden
    if not dp.empty and "deleted_timestamps" in st.session_state and st.session_state.deleted_timestamps:
        dp = dp[~dp["timestamp"].isin(st.session_state.deleted_timestamps)]
    return dp

def add_points_gs(user, team, task, points):
    """Speichert Punkte im Hintergrund ab und zeigt sie lokal SOFORT an."""
    ts = datetime.now().isoformat()
    if "optimistic_points" not in st.session_state: st.session_state.optimistic_points = []
    
    # 1. Sofortiges lokales Feedback (schnell)
    st.session_state.optimistic_points.append({
        "timestamp": ts, "user": user, "team": team, "task": task, "points": int(points)
    })
    st.toast("✅ Erledigt!", icon="🎉")
    
    # 2. Schreibvorgang im Hintergrund an Google (langsam)
    def _write_task():
        with gs_write_lock:
            try:
                load_points_gs.clear() 
                dp = load_points_gs() 
                new_row = pd.DataFrame([{
                    "timestamp": ts, "user": user, "team": team, "task": task, "points": int(points)
                }])
                updated = pd.concat([dp, new_row], ignore_index=True)
                conn.update(worksheet="WG_Data", data=updated)
                load_points_gs.clear()
            except Exception as e:
                print(f"Background save failed: {e}")
                
    threading.Thread(target=_write_task).start()

def delete_points_gs(timestamp_val):
    """Löscht einen Eintrag anhand seines Zeitstempels im Hintergrund."""
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
    """Speichert Änderungen aus dem Admin-Bereich an den Aufgaben."""
    conn.update(worksheet="WG_Tasks", data=df_tasks)
    load_config_gs.clear()

def get_base_date(): return date(2024, 1, 1)

def get_cycle_info(target_date):
    """Berechnet die 14-Tage Zyklen und das aktuelle Straf-Paket."""
    base_date = get_base_date()
    delta = (target_date - base_date).days
    cycle_num = delta // 14
    start = base_date + timedelta(days=cycle_num * 14)
    end = start + timedelta(days=13)
    pkg = "Paket A (Boden, Bad, K.-Deep, Chem.)" if cycle_num % 2 == 0 else "Paket B (Boden, Staub, Entsorg., Kühls.)"
    return start, end, pkg, cycle_num

# ==========================================
# 4. APP SETUP & BASIS-CSS (BEREINIGT)
# ==========================================
st.set_page_config(page_title="WG", page_icon="🏔️", layout="centered")

# CSS-Block für das Layout und die neuen Bild-Icons
st.markdown(f"""
<style>
    /* Generelles Layout */
    .stButton > button {{
        width: 100%; min-height: 65px; font-size: 1.2rem; font-weight: bold;
        border-radius: 12px; border: 2px solid #f0f2f6; background-color: white; color: #31333F;
    }}
    
    .block-container {{ 
        height: 100vh; overflow-y: auto;
        padding-left: 75px !important; padding-right: 15px !important;
        padding-top: 1.5rem !important; padding-bottom: 80px !important;
    }}

    /* SCHMALE ICON-SEITENLEISTE */
    [data-testid="stRadio"] {{
        position: fixed !important; top: 0 !important; left: 0 !important;
        width: 65px !important; height: 100vh !important;
        background-color: var(--secondary-background-color) !important;
        z-index: 999999 !important; padding-top: 20px !important;
        border-right: 1px solid #ddd; display: flex; flex-direction: column; align-items: center;
    }}
    [data-testid="stWidgetLabel"] {{ display: none !important; }}
    
    /* Punkt und Text verstecken, um Platz für Bilder zu machen */
    [data-baseweb="radio"] > div:first-child {{ display: none !important; }}
    [data-testid="stRadio"] p {{ display: none !important; }} 
    
    /* Globale Icon-Definitionen entfernt, werden dynamisch per User-Rolle gesetzt */

    /* Stealth Mode */
    [data-testid="collapsedControl"], [data-testid="stSidebar"], 
    header, footer, .stAppDeployButton {{ display: none !important; }}
</style>

<script>
    /* Nur noch die Auto-Login Logik (PWA-Teil entfernt) */
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
# 5. INITIALISIERUNG & AUTHENTIFIZIERUNG
# ==========================================
df_tasks = load_config_gs()
df_users = load_users_gs()

# Standardwerte im Session-State setzen
if "user" not in st.session_state:
    st.session_state.update({"user": None, "authenticated": False, "is_admin": False, "deleted_timestamps": set()})

# URL prüfen (wird getriggert, wenn das JavaScript oben weiterleitet)
if not st.session_state.authenticated:
    qu = st.query_params.get("user")
    if qu:
        match = df_users[df_users["Name"].str.lower() == qu.lower()]
        if not match.empty:
            ui = match.iloc[0]
            st.session_state.update({"user": ui["Name"], "team": ui["Team"], "is_admin": bool(ui["IsAdmin"]), "authenticated": True})
            st.rerun()

# Wenn JavaScript nichts gefunden hat, lade Login-Skript aus zur Sicherheit
if not st.session_state.authenticated:
    st.markdown("""<script>
        const savedUser = localStorage.getItem('wg_user');
        if (savedUser && !window.location.search.includes('user=')) { window.location.search = '?user=' + savedUser; }
    </script>""", unsafe_allow_html=True)


# ==========================================
# 6. LAYOUT-WEICHEN (LOGIN vs. APP)
# ==========================================
if not st.session_state.authenticated:
    # --- CSS FÜR LOGIN SEITE (Mittig, keine Seitenleiste) ---
    st.markdown("""
    <style>
        .block-container { 
            padding: 2rem !important; 
            max-width: 500px; /* Hält das Login-Fenster schmal und mittig */
            margin: 0 auto;
        }
    </style>
    """, unsafe_allow_html=True)
    
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
                else: st.error("Falsches Passwort")
            else: st.error("Benutzername nicht gefunden")
        else: st.warning("Bitte Benutzername und Passwort eingeben")
    st.stop() # Stoppt die Ausführung hier, wenn nicht eingeloggt


# --- CSS FÜR APP SEITE (Mit 70px Platz links für die Sidebar) ---
if st.session_state.authenticated:
    st.markdown("""
    <style>
        .block-container {{ 
            height: 100vh; overflow-y: auto;
            padding-left: 75px !important;  /* WICHTIG: Platz für schmale Sidebar! */
            padding-right: 15px !important; padding-top: 1.5rem !important; padding-bottom: 80px !important;
            -webkit-overflow-scrolling: touch;
        }}
        
        /* Die statische, schmale Icon-Leiste am linken Rand */
        [data-testid="stRadio"] {{
            position: fixed !important; top: 0 !important; left: 0 !important;
            width: 65px !important; height: 100vh !important;
            background-color: var(--secondary-background-color) !important;
            z-index: 999999 !important; padding-top: 20px !important;
            border-right: 1px solid #ddd; display: flex; flex-direction: column; align-items: center;
            box-shadow: 2px 0 5px rgba(0,0,0,0.05);
        }}
        [data-testid="stWidgetLabel"] {{ display: none !important; }}
        
        /* Das Layout der einzelnen Radio-Optionen (Icons) */
        [data-testid="stRadio"] div[role="radiogroup"] > label {{
            height: 65px !important; width: 65px !important;
            padding: 0 !important; margin-bottom: 5px;
            display: flex; justify-content: center !important; align-items: center !important;
            cursor: pointer;
        }}
        
        /* Die Emojis zentrieren und Basis-Größe festlegen */
        [data-testid="stRadio"] p {
            font-size: 1.8rem !important; margin: 0 !important; text-align: center;
            transition: all 0.2s ease-in-out; /* Weicher Übergang beim Vergrößern */
        }

        /* DEN BÖSEN PUNKT DES RADIO-BUTTONS VERNICHTEN */
        [data-baseweb="radio"] > div:first-child { display: none !important; }
        
        /* Wrapper zentrieren */
        [data-baseweb="radio"] { justify-content: center !important; width: 100% !important; }
    </style>
    """, unsafe_allow_html=True)
    
    # User im LocalStorage speichern (sicher ist sicher)
    st.markdown(f"<script>localStorage.setItem('wg_user', '{st.session_state.user}');</script>", unsafe_allow_html=True)


# ==========================================
# 7. DIE ICON-NAVIGATION (SIDEBAR)
# ==========================================
nav_options = {"📊": "Stand", "➕": "Punkte", "📜": "Verlauf"}
if st.session_state.is_admin:
    nav_options["⚙️"] = "Admin"
nav_options["🚪"] = "Abmelden"

# Auslesen aller verfügbaren Icons als Liste
icon_keys = list(nav_options.keys())

# Render des Radio-Buttons
selected_icon = st.radio("Menü", icon_keys, label_visibility="collapsed")
active_tab = nav_options[selected_icon]

# --- DYNAMISCHES CSS FÜR DIE ICONS ---
icon_url_map = {
    "📊": "app/static/001.png",
    "➕": "app/static/002.png",
    "📜": "app/static/icon.png",
    "⚙️": "app/static/003.png",
    "🚪": "app/static/004.png"
}

icon_css = ""
# Wir iterieren nur ueber die Menuepunkte, die dieser User logisch auch sehen darf (z.B. kein Admin Icon fuer non-Admins)
for i, key in enumerate(icon_keys):
    icon_css += f"""
    [data-testid="stRadio"] div[role="radiogroup"] > label:nth-child({i+1}) {{
        background-image: url('{icon_url_map[key]}');
        background-size: 35px; background-repeat: no-repeat; background-position: center 45%;
    }}
    """

# Das selektierte Icon nochmal vergroessert formatieren
selected_index = icon_keys.index(selected_icon) + 1
icon_css += f"""
    [data-testid="stRadio"] div[role="radiogroup"] > label:nth-child({selected_index}) {{
        background-size: 45px !important;
        filter: brightness(0.8);
        transition: transform 0.2s, background-size 0.2s;
        transform: scale(1.05);
    }}
"""

st.markdown(f"<style>{icon_css}</style>", unsafe_allow_html=True)

# Dashboard statisch machen (Scrollen deaktivieren auf dem Stand-Tab)
if active_tab == "Stand":
    st.markdown("<style>.block-container { overflow-y: hidden !important; }</style>", unsafe_allow_html=True)


# ==========================================
# 8. SEITEN-INHALTE (TABS)
# ==========================================
st.write(f"Hallo **{st.session_state.user}**! 👋")

# TAB 1: DASHBOARD / STAND
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
                     text="user", category_orders={"team": team_order},
                     color_discrete_sequence=["#FF4B4B", "#1C83E1", "#29B045", "#FFD700"])
        
        fig.update_traces(textposition='inside', textfont=dict(color='white', size=14))
        fig.update_layout(showlegend=False, margin=dict(l=0, r=0, t=10, b=0), xaxis_title=None, yaxis_title=None)
        st.plotly_chart(fig, use_container_width=True, config={'staticPlot': True})
        
        ps, pl = agg[agg['team']=='SaNi']['points'].sum(), agg[agg['team']=='LiSa']['points'].sum()
        my_pts = pl if my_team == "LiSa" else ps
        other_pts = ps if my_team == "LiSa" else pl

        st.markdown(f"""
        <div style="display: flex; justify-content: space-around; text-align: center; margin-top: 5px;">
            <div style="flex: 1;"><p style="font-size: 0.9rem; margin: 0; color: #555;">{my_team}</p><p style="font-size: 1.8rem; font-weight: bold; margin: 0; color: var(--text-color);">{my_pts} P</p></div>
            <div style="flex: 1;"><p style="font-size: 0.9rem; margin: 0; color: #555;">{other_team}</p><p style="font-size: 1.8rem; font-weight: bold; margin: 0; color: var(--text-color);">{other_pts} P</p></div>
        </div>
        """, unsafe_allow_html=True)
    else: st.warning("Noch keine Punkte.")

# TAB 2: PUNKTE EINTRAGEN
elif active_tab == "Punkte":
    current_tasks = load_config_gs()
    cat_order = ["Quick", "Wartung", "Main", "Strafaufgaben"]
    
    for cat in cat_order:
        with st.expander(f"📍 {cat}", expanded=False):
            ct = current_tasks[current_tasks["Category"] == cat]
            if not ct.empty:
                for r in ct.itertuples():
                    # Rendert einen Button pro Aufgabe
                    if st.button(f"{r.Task} ({r.Points}P)", key=f"p_{r.Index}"):
                        add_points_gs(st.session_state.user, st.session_state.team, r.Task, r.Points)
    
    st.markdown("---")
    with st.expander("⏱️ Letzte Einträge bearbeiten", expanded=False):
        dp = get_active_points()
        if not dp.empty:
            dp['Datum'] = pd.to_datetime(dp['timestamp']).dt.date
            # Admins sehen 50 Einträge, normale User nur ihre eigenen von heute
            if st.session_state.is_admin:
                recent = dp.sort_values("timestamp", ascending=False).head(50)
            else:
                recent = dp[(dp['Datum'] == date.today()) & (dp['user'] == st.session_state.user)].sort_values("timestamp", ascending=False)
                
            if not recent.empty:
                for _, r in recent.iterrows():
                    can_delete = st.session_state.is_admin or (r['user'] == st.session_state.user)
                    if pd.notna(r['timestamp']):
                        c1, c2, c3 = st.columns([3, 4, 1])
                        dt_str = datetime.fromisoformat(r['timestamp']).strftime("%d.%m. %H:%M") if "T" in str(r['timestamp']) else str(r['timestamp'])[:10]
                        c1.caption(dt_str)
                        c2.markdown(f"**{r['user']}**: {r['task']} ({r['points']}P)")
                        # Mülleimer Icon zum Löschen
                        if can_delete and c3.button("🗑️", key=f"del_pt_{r['timestamp']}"): delete_points_gs(r['timestamp'])
            else: st.info("Heute noch keine Einträge gemacht.")
        else: st.info("Noch keine Einträge vorhanden.")

# TAB 3: VERLAUF / HISTORY
elif active_tab == "Verlauf":
    df = get_active_points()
    if not df.empty:
        df['Datum'] = pd.to_datetime(df['timestamp']).dt.date
        _, _, _, n = get_cycle_info(date.today())
        # Schleife über die letzten 6 Zyklen
        for i in range(n - 1, max(-1, n - 6), -1):
            s, e, p, _ = get_cycle_info(get_base_date() + timedelta(days=i*14))
            d = df[(df['Datum'] >= s) & (df['Datum'] <= e)]
            vs, vl = d[d["team"] == "SaNi"]["points"].sum(), d[d["team"] == "LiSa"]["points"].sum()
            loser = "SaNi" if vs < vl else ("LiSa" if vl < vs else "Unentschieden")
            
            kw_s = s.isocalendar()[1]
            kw_e = e.isocalendar()[1]
            if st.session_state.team != loser or loser == "Unentschieden":
                st.success(f"**KW{kw_s} & KW{kw_e}** ({s.strftime('%d.%m')} - {e.strftime('%d.%m')})  \n"
                           f"SaNi: **{vs}** | LiSa: **{vl}**  \n"
                           f"Strafe: **{loser}**  \n"
                           f"{p}")
            else:
                st.error(f"**KW{kw_s} & KW{kw_e}** ({s.strftime('%d.%m')} - {e.strftime('%d.%m')})  \n"
                         f"SaNi: **{vs}** | LiSa: **{vl}**  \n"
                         f"Strafe: **{loser}**  \n"
                         f"{p}")
    else: st.info("Keine Daten.")

# TAB 4: ADMIN BEREICH
elif active_tab == "Admin" and st.session_state.is_admin:
    st.subheader("Aufgaben editieren")
    cat_order = ["Quick", "Wartung", "Main", "Strafaufgaben"]
    
    with st.form("adm_task_form"):
        updated, new_tasks = [], []
        
        for cat in cat_order:
            with st.expander(f"⚙️ {cat}", expanded=False):
                ct = df_tasks[df_tasks["Category"] == cat].copy()
                if not ct.empty:
                    for i, r in ct.iterrows():
                        col1, col2 = st.columns([3, 1])
                        new_p = col1.number_input(r['Task'], value=0 if pd.isna(r['Points']) else int(r['Points']), key=f"upd_{i}")
                        if not col2.checkbox("🗑️ löschen", key=f"del_{i}"):
                            updated.append({"Category": cat, "Task": r['Task'], "Points": new_p})
                
                st.markdown(f"**Neue Aufgabe in {cat}:**")
                c1, c2 = st.columns([3, 1])
                nt = c1.text_input("Name", key=f"new_n_{cat}")
                np = c2.number_input("Punkte", 10, key=f"new_p_{cat}")
                if nt: new_tasks.append({"Category": cat, "Task": nt, "Points": int(np)})
        
        if st.form_submit_button("Speichern"):
            save_tasks_gs(pd.DataFrame(updated + new_tasks))
            st.toast("✅ Gespeichert!", icon="💾")
            st.rerun()

# TAB 5: ABMELDEN
elif active_tab == "Abmelden":
    st.markdown("<script>localStorage.removeItem('wg_user');</script>", unsafe_allow_html=True)
    st.session_state.update({"user": None, "authenticated": False})
    if "user" in st.query_params: del st.query_params["user"]
    st.rerun()
