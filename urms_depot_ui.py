# urms_depot_ui.py
# Single-file Streamlit UI demo for URMS Depot Logistics Assistant (standalone, no Docker)

import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, timedelta
import random
import uuid
from dateutil import parser
import plotly.express as px
import plotly.graph_objects as go

DB_FILE = "urms_demo.db"

# ---------- DB helpers ----------
def init_db():
    conn = sqlite3.connect(DB_FILE, detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES)
    cur = conn.cursor()
    cur.execute("""
      CREATE TABLE IF NOT EXISTS rake_events (
        rake_id TEXT PRIMARY KEY,
        fnr TEXT,
        created_ts TIMESTAMP,
        current_station TEXT,
        eta_iso TEXT,
        wagon_details TEXT,   -- JSON-like text: simple CSV "W1:PENDING;W2:UNLOADED"
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
    conn.commit()
    conn.close()

def db_insert_rake(rake_id, fnr, current_station, eta_iso, wagon_details, raw=""):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("INSERT OR REPLACE INTO rake_events (rake_id, fnr, created_ts, current_station, eta_iso, wagon_details, raw) VALUES (?,?,?,?,?,?,?)",
                (rake_id, fnr, datetime.utcnow(), current_station, eta_iso, wagon_details, raw))
    conn.commit()
    conn.close()

def db_get_rakes():
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query("SELECT * FROM rake_events", conn, parse_dates=["created_ts"])
    conn.close()
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
    conn.commit()
    conn.close()
    return task_id

def db_get_assignments():
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query("SELECT * FROM truck_assignments", conn, parse_dates=["created_ts"])
    conn.close()
    return df

def db_insert_case(rake_id, wagon_no, case_type, reported_by, details):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    case_id = "CASE-" + str(uuid.uuid4())[:8]
    cur.execute("INSERT INTO cases (case_id, rake_id, wagon_no, case_type, reported_by, reported_ts, details) VALUES (?,?,?,?,?,?,?)",
                (case_id, rake_id, wagon_no, case_type, reported_by, datetime.utcnow(), details))
    conn.commit()
    conn.close()
    return case_id

def db_get_cases():
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query("SELECT * FROM cases", conn, parse_dates=["reported_ts"])
    conn.close()
    return df

# ---------- Domain helpers ----------
def parse_wagon_details(text):
    # stored as "W1:PENDING;W2:UNLOADED"
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

def count_unloaded(wagon_items):
    return sum(1 for w in wagon_items if w["status"].upper() == "UNLOADED")

def count_pending(wagon_items):
    return sum(1 for w in wagon_items if w["status"].upper() != "UNLOADED")

def simple_eta_predict(distance_km, avg_speed_kmph):
    # simple prediction minutes = (distance / speed) * 60
    if avg_speed_kmph <= 0:
        avg_speed_kmph = 20
    minutes = (distance_km / avg_speed_kmph) * 60
    return int(minutes)

def compute_d_and_w_risk(pending_wagons):
    # rule-based scoring
    if pending_wagons > 30:
        return ("HIGH", pending_wagons * 820)   # simplistic INR estimate
    elif pending_wagons > 10:
        return ("MEDIUM", pending_wagons * 490)
    else:
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

# ---------- UI ----------
st.set_page_config(page_title="URMS Depot Assistant - Single File Demo", layout="wide")
st.markdown("""<style>
body { font-family: 'Inter', 'Segoe UI', sans-serif; background-color: #f5f7fa; }
.main { background-color: #f5f7fa; }
.risk-high { color: #ff2e2e; font-weight:700; background: #ffe6e6; padding: 8px 12px; border-radius: 6px; }
.risk-med { color: #ff9000; font-weight:700; background: #fff4e6; padding: 8px 12px; border-radius: 6px; }
.risk-low { color: #1e7e34; font-weight:700; background: #e6f7ed; padding: 8px 12px; border-radius: 6px; }
.header-title { color: #1a365d; font-size: 2.5em; font-weight: 700; margin-bottom: 10px; }
.stat-badge { display: inline-block; background: #e2e8f0; padding: 6px 12px; border-radius: 20px; margin: 4px 4px 4px 0; font-weight: 600; }
</style>""", unsafe_allow_html=True)
st.markdown("<div class='header-title'>🚛 URMS Depot Logistics Assistant</div>", unsafe_allow_html=True)

init_db()

col1, col2 = st.columns([2,1])

with col1:
    st.header("Simulate FOIS Poll / Create Rake Event")
    with st.form("simulate_form"):
        fnr = st.text_input("FNR (identifier)", value=str(random.randint(10000000,99999999)))
        rake_id = st.text_input("Rake ID", value=f"RAKE-{fnr}")
        current_station = st.text_input("Current Station", value="PLANT-01")
        # create sample wagons
        wagons_count = st.number_input("Number of wagons", min_value=2, max_value=80, value=8)
        # build wagon statuses randomly
        default_unloaded = st.slider("Initial unloaded wagons", 0, int(wagons_count), 1)
        wagons = []
        for i in range(1, wagons_count+1):
            status = "UNLOADED" if i <= default_unloaded else "PENDING"
            wagons.append({"wagon_no": f"W{i:03d}", "status": status})
        eta_in_hours = st.number_input("ETA (hours from now)", min_value=0.0, max_value=72.0, value=6.0)
        submit_sim = st.form_submit_button("Create Rake Event (simulate FOIS)")
    if submit_sim:
        eta_dt = datetime.utcnow() + timedelta(hours=float(eta_in_hours))
        db_insert_rake(rake_id, fnr, current_station, eta_dt.isoformat(), format_wagon_details(wagons))
        st.success(f"Rake {rake_id} created with {len(wagons)} wagons; {default_unloaded} unloaded.")

    st.markdown("---")
    st.header("Rakes in System")
    rakes_df = db_get_rakes()
    if rakes_df.empty:
        st.info("No rakes yet — simulate one above.")
    else:
        display = []
        for _, row in rakes_df.iterrows():
            wd = parse_wagon_details(row["wagon_details"])
            unloaded = count_unloaded(wd)
            pending = count_pending(wd)
            eta = row["eta_iso"]
            # compute basic ETA delta
            eta_dt = parser.isoparse(eta) if eta else None
            eta_str = eta_dt.strftime("%Y-%m-%d %H:%M:%S UTC") if eta_dt else "NA"
            actions, risk, dem = recommended_actions_for_rake(pending)
            display.append({
                "rake_id": row["rake_id"],
                "fnr": row["fnr"],
                "station": row["current_station"],
                "unloaded": unloaded,
                "pending": pending,
                "eta": eta_str,
                "d_and_w_risk": risk,
                "pred_demurrage_inr": dem
            })
        st.dataframe(pd.DataFrame(display).sort_values(["d_and_w_risk","pending"], ascending=[False, False]).reset_index(drop=True))

with col2:
    st.header("Inspect / Act on a Rake")
    rake_to_view = st.text_input("Enter Rake ID to view", value=(rakes_df.iloc[0]["rake_id"] if not rakes_df.empty else ""))
    if rake_to_view:
        row = db_get_rake(rake_to_view)
        if not row:
            st.warning("Rake not found — create one using simulate FOIS.")
        else:
            _, fnr, created_ts, station, eta_iso, wagon_details_text, raw = row
            st.subheader(f"Rake {rake_to_view}")
            st.markdown(f"**FNR:** {fnr}  \n**Station:** {station}  \n**ETA:** {eta_iso}")
            w_items = parse_wagon_details(wagon_details_text)
            st.markdown("**Wagons (status)**")
            df_w = pd.DataFrame(w_items)
            st.table(df_w)
            unloaded = count_unloaded(w_items)
            pending = count_pending(w_items)
            st.markdown(f"**Unloaded:** {unloaded}   **Pending:** {pending}")
            actions, risk, dem = recommended_actions_for_rake(pending)
            st.markdown(f"**D&W Risk:** {risk}  •  **Projected Demurrage INR:** {dem}")
            st.markdown("**Recommended Actions:**")
            for a in actions:
                st.write(f"- {a['detail']} (urgency: {a['urgency']})")

            st.markdown("----")
            st.subheader("Predict ETA (quick)")
            dist = st.number_input("Distance remaining (km)", min_value=1.0, value=150.0)
            avg_speed = st.number_input("Avg speed (kmph)", min_value=1.0, value=30.0)
            if st.button("Predict ETA for selected rake"):
                mins = simple_eta_predict(dist, avg_speed)
                pred = datetime.utcnow() + timedelta(minutes=mins)
                st.success(f"Predicted ETA in {mins} minutes → {pred.strftime('%Y-%m-%d %H:%M:%S UTC')}")
            st.markdown("----")
            st.subheader("Assign Trucks")
            trucks_raw = st.text_input("Truck IDs (comma separated)", value="TRK-101,TRK-102")
            lane_from = st.text_input("Lane from", value="Yard-Lane-A")
            reason = st.text_input("Reason", value="Resolve backlog")
            if st.button("Assign Trucks"):
                truck_list = [t.strip() for t in trucks_raw.split(",") if t.strip()]
                task_id = db_insert_assignment(rake_to_view, truck_list, lane_from, reason)
                st.success(f"Assigned {len(truck_list)} trucks. Task ID: {task_id}")

            st.markdown("----")
            st.subheader("Create Exception / Case")
            case_wagon = st.selectbox("Wagon No (choose)", [w["wagon_no"] for w in w_items])
            case_type = st.selectbox("Case Type", ["SHORTAGE","DAMAGE","MISSING_WAGON","OTHER"])
            reporter = st.text_input("Reported by", value="depot_user_01")
            details = st.text_area("Details", value=f"Auto - recorded at {datetime.utcnow().isoformat()}")
            if st.button("Create Case"):
                cid = db_insert_case(rake_to_view, case_wagon, case_type, reporter, details)
                st.success(f"Case created: {cid}")

st.markdown("---")
st.header("Assignments & Cases")
assign_df = db_get_assignments()
case_df = db_get_cases()
c1, c2 = st.columns(2)
with c1:
    st.subheader("Truck Assignments")
    if assign_df.empty:
        st.info("No assignments yet.")
    else:
        st.dataframe(assign_df)
with c2:
    st.subheader("Cases")
    if case_df.empty:
        st.info("No cases yet.")
    else:
        st.dataframe(case_df)

st.markdown("---")
st.caption("This is a demo app: logic simplified for local testing and proofs-of-concept. Replace with FOIS API, Kafka, ML models and production DB for real deployments.")
