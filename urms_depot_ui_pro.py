# urms_depot_ui_pro.py
# Polished Streamlit UI for URMS Depot Logistics Assistant (standalone demo)
# Updated to use st.rerun() (Streamlit stable API)

import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, timedelta
import random, uuid
from dateutil import parser
import plotly.express as px

DB_FILE = "urms_demo_pro.db"

# -----------------------
# DB helpers (SQLite)
# -----------------------
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("""
      CREATE TABLE IF NOT EXISTS rake_events (
        rake_id TEXT PRIMARY KEY,
        fnr TEXT,
        created_ts TIMESTAMP,
        current_station TEXT,
        eta_iso TEXT,
        wagon_details TEXT,
        raw TEXT
      )
    """)
    cur.execute("""
      CREATE TABLE IF NOT EXISTS truck_assignments (
        id TEXT PRIMARY KEY,
        rake_id TEXT,
        truck_ids TEXT,
        lane_from TEXT,
        reason TEXT,
        created_ts TIMESTAMP
      )
    """)
    cur.execute("""
      CREATE TABLE IF NOT EXISTS cases (
        case_id TEXT PRIMARY KEY,
        rake_id TEXT,
        wagon_no TEXT,
        case_type TEXT,
        reported_by TEXT,
        reported_ts TIMESTAMP,
        details TEXT
      )
    """)
    cur.execute("""
      CREATE TABLE IF NOT EXISTS activity_log (
        id TEXT PRIMARY KEY,
        ts TIMESTAMP,
        level TEXT,
        source TEXT,
        message TEXT
      )
    """)
    conn.commit()
    conn.close()

def log_activity(level, source, message):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("INSERT INTO activity_log (id, ts, level, source, message) VALUES (?,?,?,?,?)",
                (str(uuid.uuid4()), datetime.utcnow(), level, source, message))
    conn.commit()
    conn.close()

def db_insert_rake(rake_id, fnr, current_station, eta_iso, wagon_details, raw=""):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("INSERT OR REPLACE INTO rake_events (rake_id, fnr, created_ts, current_station, eta_iso, wagon_details, raw) VALUES (?,?,?,?,?,?,?)",
                (rake_id, fnr, datetime.utcnow(), current_station, eta_iso, wagon_details, raw))
    conn.commit(); conn.close()
    log_activity("INFO", "FOIS_SIM", f"Inserted/Updated rake {rake_id}")

def db_get_rakes_df():
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query("SELECT * FROM rake_events", conn, parse_dates=["created_ts"])
    conn.close()
    if df.empty:
        return df
    # normalize small fields
    df['pending_count'] = df['wagon_details'].apply(lambda t: sum(1 for p in (t or "").split(";") if ":" in p and p.split(":")[1].strip().upper() != "UNLOADED"))
    df['unloaded_count'] = df['wagon_details'].apply(lambda t: sum(1 for p in (t or "").split(";") if ":" in p and p.split(":")[1].strip().upper() == "UNLOADED"))
    df['eta_dt'] = df['eta_iso'].apply(lambda s: parser.isoparse(s) if s else None)
    return df

def db_get_rake(rake_id):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT * FROM rake_events WHERE rake_id=?", (rake_id,))
    row = cur.fetchone()
    conn.close()
    return row

def db_insert_assignment(rake_id, truck_ids, lane_from, reason):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    task_id = str(uuid.uuid4())
    cur.execute("INSERT INTO truck_assignments (id, rake_id, truck_ids, lane_from, reason, created_ts) VALUES (?,?,?,?,?,?)",
                (task_id, rake_id, ",".join(truck_ids), lane_from, reason, datetime.utcnow()))
    conn.commit(); conn.close()
    log_activity("INFO", "ASSIGN", f"Assigned {len(truck_ids)} trucks to {rake_id}")
    return task_id

def db_get_assignments_df():
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query("SELECT * FROM truck_assignments ORDER BY created_ts DESC LIMIT 50", conn, parse_dates=["created_ts"])
    conn.close()
    return df

def db_insert_case(rake_id, wagon_no, case_type, reported_by, details):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    case_id = "CASE-" + str(uuid.uuid4())[:8]
    cur.execute("INSERT INTO cases (case_id, rake_id, wagon_no, case_type, reported_by, reported_ts, details) VALUES (?,?,?,?,?,?,?)",
                (case_id, rake_id, wagon_no, case_type, reported_by, datetime.utcnow(), details))
    conn.commit(); conn.close()
    log_activity("WARN", "CASE", f"{case_type} for {rake_id}:{wagon_no} by {reported_by}")
    return case_id

def db_get_cases_df():
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query("SELECT * FROM cases ORDER BY reported_ts DESC LIMIT 100", conn, parse_dates=["reported_ts"])
    conn.close()
    return df

def db_get_activity_df(limit=100):
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query("SELECT * FROM activity_log ORDER BY ts DESC LIMIT ?", conn, params=(limit,), parse_dates=["ts"])
    conn.close()
    return df

# -----------------------
# Domain helpers
# -----------------------
def parse_wagon_details(text):
    items = []
    if not text:
        return items
    for part in text.split(";"):
        if ":" in part:
            wagon, status = part.split(":", 1)
            items.append({"wagon_no": wagon.strip(), "status": status.strip()})
    return items

def format_wagon_details(items):
    return ";".join(f"{w['wagon_no']}:{w['status']}" for w in items)

def simple_eta_predict(distance_km, avg_speed_kmph):
    if avg_speed_kmph <= 0: avg_speed_kmph = 20
    mins = int((distance_km / avg_speed_kmph) * 60)
    return mins

def compute_d_and_w_risk(pending_wagons):
    if pending_wagons > 30:
        return ("HIGH", pending_wagons * 820)
    if pending_wagons > 10:
        return ("MEDIUM", pending_wagons * 490)
    return ("LOW", 0)

def recommended_actions_for_rake(pending):
    risk, dem = compute_d_and_w_risk(pending)
    actions = []
    if risk == "HIGH":
        actions.append({"action":"assign_trucks","detail":"Assign 5 trucks to Block 3", "urgency":"HIGH"})
        actions.append({"action":"notify_ha","detail":"Increase manpower by 3", "urgency":"HIGH"})
    elif risk == "MEDIUM":
        actions.append({"action":"notify_ha","detail":"Add 1 extra worker", "urgency":"MEDIUM"})
    else:
        actions.append({"action":"monitor","detail":"Continue monitoring", "urgency":"LOW"})
    return actions, risk, dem

# -----------------------
# UI & Layout
# -----------------------
st.set_page_config(page_title="URMS Depot Assistant — Pro UI", layout="wide", initial_sidebar_state="expanded")
st.markdown("""<style>
body { font-family: 'Inter', sans-serif; }
.small { font-size:0.9rem; color: #666; }
.risk-high { color: #ff2e2e; font-weight:700; }
.risk-med { color: #ff9000; font-weight:700; }
.risk-low { color: #1e7e34; font-weight:700; }
.kpi { background: linear-gradient(90deg,#f8f9fa,#ffffff); padding:12px; border-radius:8px; }
</style>""", unsafe_allow_html=True)

init_db()

# Sidebar controls
st.sidebar.header("Controls & Quick Actions")
with st.sidebar.expander("Create demo rake (simulate FOIS)"):
    fnr = st.text_input("FNR (auto)", value=str(random.randint(10000000,99999999)))
    rake_id = st.text_input("Rake ID", value=f"RAKE-{fnr}")
    station = st.text_input("Current Station", value="PLANT-01")
    wagons = st.slider("Wagons", 4, 80, 12)
    unloaded_initial = st.slider("Initially unloaded", 0, wagons, 2)
    eta_hours = st.number_input("ETA hours from now", min_value=0.0, max_value=168.0, value=6.0)
    if st.button("Create demo rake"):
        items = [{"wagon_no": f"W{i:03d}", "status": ("UNLOADED" if i <= unloaded_initial else "PENDING")} for i in range(1, wagons+1)]
        eta_dt = datetime.utcnow() + timedelta(hours=eta_hours)
        db_insert_rake(rake_id, fnr, station, eta_dt.isoformat(), format_wagon_details(items))
        st.success(f"Created {rake_id} ({wagons} wagons).")
        st.rerun()

st.sidebar.markdown("---")
if st.sidebar.button("Refresh data"):
    st.rerun()

# Main header
st.title("URMS — Depot Logistics Assistant (Pro UI Demo)")
st.write("Interactive demo. Replace with FOIS, Kafka & ML services for production.")

# KPI row
rakes_df = db_get_rakes_df()
total_pending = int(rakes_df['pending_count'].sum()) if not rakes_df.empty else 0
avg_unload_rate = (rakes_df['unloaded_count'].sum() / max(len(rakes_df),1)) if not rakes_df.empty else 0
total_dandw = int(sum(compute_d_and_w_risk(int(p))[1] for p in (rakes_df['pending_count'].tolist() if not rakes_df.empty else [])))

k1, k2, k3, k4 = st.columns([1.4,1,1,1])
k1.metric("Pending Wagons (total)", f"{total_pending}")
k2.metric("Avg Unloaded / Rake", f"{avg_unload_rate:.1f}")
k3.metric("Projected D&W (INR)", f"₹{total_dandw:,}")
k4.metric("Rakes in System", f"{len(rakes_df)}")

st.markdown("---")

# Rake list + filters
left, right = st.columns([2,1])
with left:
    st.subheader("Rakes — Overview")
    if rakes_df.empty:
        st.info("No rakes in system. Create one from the sidebar.")
    else:
        # prepare display
        display = rakes_df[['rake_id','fnr','current_station','unloaded_count','pending_count','eta_dt']].copy()
        display['eta'] = display['eta_dt'].dt.strftime("%Y-%m-%d %H:%M") 
        display = display.sort_values(by=['pending_count'], ascending=False)
        # add risk column for coloring
        display['risk'] = display['pending_count'].apply(lambda p: compute_d_and_w_risk(int(p))[0])
        # show as interactive table with small sparkline: use bar chart to show pending distribution
        st.dataframe(display.rename(columns={
            'rake_id':'Rake ID','fnr':'FNR','current_station':'Station','unloaded_count':'Unloaded','pending_count':'Pending','eta':'ETA','risk':'Risk'
        }).reset_index(drop=True), height=300)

        st.markdown("**Pending distribution**")
        # bar chart
        chart_df = display[['rake_id','pending_count']].set_index('rake_id')
        st.bar_chart(chart_df)

with right:
    st.subheader("Quick Actions")
    sel_rake = st.selectbox("Select Rake", options=(rakes_df['rake_id'].tolist() if not rakes_df.empty else [""]))
    if sel_rake:
        st.markdown("### Selected: " + (sel_rake or "—"))
        row = db_get_rake(sel_rake)
        if row:
            _, fnr, created_ts, station, eta_iso, wagon_details_text, raw = row
            w_items = parse_wagon_details(wagon_details_text)
            pending = sum(1 for w in w_items if w['status'].upper() != 'UNLOADED')
            unloaded = sum(1 for w in w_items if w['status'].upper() == 'UNLOADED')
            st.markdown(f"**Station:** {station}  \n**FNR:** {fnr}  \n**Unloaded / Pending:** {unloaded} / {pending}")
            risk, dem = compute_d_and_w_risk(pending)
            if risk == "HIGH":
                st.markdown(f"<span class='risk-high'>D&W Risk: {risk} • ₹{dem:,}</span>", unsafe_allow_html=True)
            elif risk == "MEDIUM":
                st.markdown(f"<span class='risk-med'>D&W Risk: {risk} • ₹{dem:,}</span>", unsafe_allow_html=True)
            else:
                st.markdown(f"<span class='risk-low'>D&W Risk: {risk} • ₹{dem:,}</span>", unsafe_allow_html=True)

            st.markdown("----")
            st.subheader("Actions for this rake")
            assign_trucks_str = st.text_input("Truck IDs (comma separated)", value="TRK-101,TRK-102")
            lane = st.text_input("Lane from", value="Yard-A")
            reason = st.text_input("Reason", value="Resolve backlog")
            if st.button("Assign Trucks to Rake"):
                trucks = [t.strip() for t in assign_trucks_str.split(",") if t.strip()]
                tid = db_insert_assignment(sel_rake, trucks, lane, reason)
                st.success(f"Assigned {len(trucks)} trucks. Task ID: {tid}")
                st.rerun()

            with st.expander("Create exception / case"):
                wagon_choices = [w['wagon_no'] for w in w_items]
                cw = st.selectbox("Wagon", options=wagon_choices)
                ctype = st.selectbox("Case Type", ["SHORTAGE","DAMAGE","MISSING_WAGON","OTHER"])
                reporter = st.text_input("Reported by", value="depot_user_01")
                details = st.text_area("Details", value="")
                if st.button("Create Case"):
                    cid = db_insert_case(sel_rake, cw, ctype, reporter, details or "Auto note")
                    st.success(f"Case created: {cid}")
                    st.rerun()

            st.markdown("----")
            st.subheader("ETA prediction (interactive)")
            dist = st.number_input("Remaining distance (km)", value=150.0)
            speed = st.number_input("Estimated avg speed (kmph)", value=30.0)
            if st.button("Predict ETA"):
                mins = simple_eta_predict(dist, speed)
                predicted_ts = datetime.utcnow() + timedelta(minutes=mins)
                st.info(f"Predicted ETA in {mins} minutes → {predicted_ts.strftime('%Y-%m-%d %H:%M UTC')}")
                log_activity("INFO","ETA","Predicted ETA for "+sel_rake)

st.markdown("---")
# Lower area: details & charts
st.subheader("Rake Details & Wagons")
colA, colB = st.columns([2,1])
with colA:
    if not rakes_df.empty:
        selected = st.selectbox("Choose Rake to inspect", options=rakes_df['rake_id'].tolist())
        row = db_get_rake(selected)
        if row:
            _, fnr, created_ts, station, eta_iso, wagon_text, raw = row
            items = parse_wagon_details(wagon_text)
            df_w = pd.DataFrame(items)
            # progress
            unloaded = sum(1 for w in items if w['status'].upper()=="UNLOADED")
            total = len(items)
            pct = int(0 if total==0 else (unloaded/total)*100)
            st.write(f"Unloaded: {unloaded} / {total}")
            st.progress(pct)
            st.table(df_w)
with colB:
    st.subheader("Activity Log (recent)")
    log_df = db_get_activity_df(50)
    if log_df.empty:
        st.info("No activity yet.")
    else:
        st.dataframe(log_df[['ts','level','source','message']].head(50))

st.markdown("---")
# Analytics chart
st.subheader("Analytics - Pending wagons per rake")
if not rakes_df.empty:
    chart_df = rakes_df[['rake_id','pending_count']].sort_values('pending_count', ascending=False)
    fig = px.bar(chart_df, x='rake_id', y='pending_count', labels={'rake_id':'Rake','pending_count':'Pending Wagons'}, title="Pending Wagons by Rake")
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("No data to show.")

st.markdown("---")
st.caption("Demo UI: replace backend calls with FOIS/Kafka/RAG/ML services for production.")
