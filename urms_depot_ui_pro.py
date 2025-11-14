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
import plotly.graph_objects as go

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
body { font-family: 'Inter', 'Segoe UI', sans-serif; background-color: #f5f7fa; }
.main { background-color: #f5f7fa; }
.small { font-size:0.9rem; color: #666; }
.risk-high { color: #ff2e2e; font-weight:700; background: #ffe6e6; padding: 8px 12px; border-radius: 6px; }
.risk-med { color: #ff9000; font-weight:700; background: #fff4e6; padding: 8px 12px; border-radius: 6px; }
.risk-low { color: #1e7e34; font-weight:700; background: #e6f7ed; padding: 8px 12px; border-radius: 6px; }
.kpi-card { 
  background: linear-gradient(135deg, #ffffff 0%, #f8f9fa 100%);
  padding: 20px; 
  border-radius: 12px;
  border: 1px solid #e0e3e8;
  box-shadow: 0 2px 8px rgba(0,0,0,0.08);
  margin-bottom: 12px;
}
.header-title { color: #1a365d; font-size: 2.5em; font-weight: 700; margin-bottom: 10px; }
.section-title { color: #2d3748; font-size: 1.5em; font-weight: 600; margin: 20px 0 10px 0; border-bottom: 3px solid #4299e1; padding-bottom: 8px; }
.action-card { background: #f0f4ff; border-left: 4px solid #4299e1; padding: 12px; border-radius: 8px; margin: 8px 0; }
.stat-badge { display: inline-block; background: #e2e8f0; padding: 6px 12px; border-radius: 20px; margin: 4px 4px 4px 0; font-weight: 600; }
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
st.markdown("<div class='header-title'>🚛 URMS — Depot Logistics Assistant</div>", unsafe_allow_html=True)
st.write("Real-time depot operations dashboard with AI-powered insights & optimization recommendations")

# KPI row - Enhanced
rakes_df = db_get_rakes_df()
total_pending = int(rakes_df['pending_count'].sum()) if not rakes_df.empty else 0
avg_unload_rate = (rakes_df['unloaded_count'].sum() / max(len(rakes_df),1)) if not rakes_df.empty else 0
total_dandw = int(sum(compute_d_and_w_risk(int(p))[1] for p in (rakes_df['pending_count'].tolist() if not rakes_df.empty else [])))
total_rakes = len(rakes_df)

k1, k2, k3, k4 = st.columns(4)
with k1:
    st.markdown(f"""
    <div class='kpi-card'>
        <div style='color: #718096; font-size: 0.9rem; font-weight: 600;'>PENDING WAGONS</div>
        <div style='color: #2d3748; font-size: 2.2em; font-weight: 700; margin: 8px 0;'>{total_pending}</div>
        <div style='color: #a0aec0; font-size: 0.85rem;'>Across {total_rakes} rakes</div>
    </div>
    """, unsafe_allow_html=True)

with k2:
    st.markdown(f"""
    <div class='kpi-card'>
        <div style='color: #718096; font-size: 0.9rem; font-weight: 600;'>AVG UNLOAD RATE</div>
        <div style='color: #48bb78; font-size: 2.2em; font-weight: 700; margin: 8px 0;'>{avg_unload_rate:.1f}</div>
        <div style='color: #a0aec0; font-size: 0.85rem;'>Per rake</div>
    </div>
    """, unsafe_allow_html=True)

with k3:
    st.markdown(f"""
    <div class='kpi-card'>
        <div style='color: #718096; font-size: 0.9rem; font-weight: 600;'>D&W RISK</div>
        <div style='color: #ed8936; font-size: 2.2em; font-weight: 700; margin: 8px 0;'>₹{total_dandw:,}</div>
        <div style='color: #a0aec0; font-size: 0.85rem;'>Potential loss</div>
    </div>
    """, unsafe_allow_html=True)

with k4:
    st.markdown(f"""
    <div class='kpi-card'>
        <div style='color: #718096; font-size: 0.9rem; font-weight: 600;'>ACTIVE RAKES</div>
        <div style='color: #4299e1; font-size: 2.2em; font-weight: 700; margin: 8px 0;'>{total_rakes}</div>
        <div style='color: #a0aec0; font-size: 0.85rem;'>In system</div>
    </div>
    """, unsafe_allow_html=True)

st.markdown("---")

# Rake list + filters
left, right = st.columns([2.5,1.5])
with left:
    st.markdown("<div class='section-title'>📊 Rakes — Overview & Status</div>", unsafe_allow_html=True)
    if rakes_df.empty:
        st.info("ℹ️ No rakes in system. Create one from the sidebar.")
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
        }).reset_index(drop=True), height=320, use_container_width=True)

        # Visualizations
        tab1, tab2 = st.tabs(["📈 Pending Distribution", "⏱️ ETA Timeline"])
        
        with tab1:
            col1, col2 = st.columns(2)
            with col1:
                chart_df = display[['rake_id','pending_count']].sort_values('pending_count', ascending=True)
                fig_bar = px.bar(chart_df, y='rake_id', x='pending_count', orientation='h',
                                labels={'pending_count':'Pending Wagons', 'rake_id':'Rake ID'}, 
                                color='pending_count', color_continuous_scale='RdYlGn_r', 
                                title="Pending Wagons by Rake")
                fig_bar.update_layout(height=400, showlegend=False)
                st.plotly_chart(fig_bar, use_container_width=True)
            
            with col2:
                risk_counts = display['risk'].value_counts()
                colors_map = {'HIGH': '#ff2e2e', 'MEDIUM': '#ff9000', 'LOW': '#1e7e34'}
                fig_pie = px.pie(values=risk_counts.values, names=risk_counts.index, 
                                title="Risk Distribution", color=risk_counts.index,
                                color_discrete_map=colors_map)
                fig_pie.update_layout(height=400)
                st.plotly_chart(fig_pie, use_container_width=True)
        
        with tab2:
            if not display['eta_dt'].isna().all():
                display_eta = display[['rake_id', 'eta_dt']].dropna()
                display_eta = display_eta.sort_values('eta_dt')
                fig_timeline = px.scatter(display_eta, x='eta_dt', y='rake_id', 
                                        labels={'eta_dt':'Expected Arrival','rake_id':'Rake ID'},
                                        title="ETA Timeline")
                fig_timeline.update_traces(marker=dict(size=12, color='#4299e1'))
                fig_timeline.update_layout(height=400)
                st.plotly_chart(fig_timeline, use_container_width=True)

with right:
    st.markdown("<div class='section-title'>⚡ Quick Actions</div>", unsafe_allow_html=True)
    sel_rake = st.selectbox("Select Rake", options=(rakes_df['rake_id'].tolist() if not rakes_df.empty else [""]))
    if sel_rake:
        st.markdown(f"### ✅ {sel_rake}")
        row = db_get_rake(sel_rake)
        if row:
            _, fnr, created_ts, station, eta_iso, wagon_details_text, raw = row
            w_items = parse_wagon_details(wagon_details_text)
            pending = sum(1 for w in w_items if w['status'].upper() != 'UNLOADED')
            unloaded = sum(1 for w in w_items if w['status'].upper() == 'UNLOADED')
            
            st.markdown(f"""
            <div class='stat-badge'>📍 {station}</div>
            <div class='stat-badge'>🔢 FNR: {fnr}</div>
            <div style='margin: 12px 0;'>
                <strong>Wagon Status:</strong><br>
                ✓ Unloaded: {unloaded} | ⏳ Pending: {pending}
            </div>
            """, unsafe_allow_html=True)
            
            risk, dem = compute_d_and_w_risk(pending)
            if risk == "HIGH":
                st.markdown(f"<div class='risk-high'>🔴 D&W Risk: {risk} — ₹{dem:,}</div>", unsafe_allow_html=True)
            elif risk == "MEDIUM":
                st.markdown(f"<div class='risk-med'>🟠 D&W Risk: {risk} — ₹{dem:,}</div>", unsafe_allow_html=True)
            else:
                st.markdown(f"<div class='risk-low'>🟢 D&W Risk: {risk} — ₹{dem:,}</div>", unsafe_allow_html=True)

            st.markdown("---")
            st.markdown("**Truck Assignment**")
            assign_trucks_str = st.text_input("Truck IDs (comma separated)", value="TRK-101,TRK-102", key="trucks")
            lane = st.text_input("Lane from", value="Yard-A", key="lane")
            reason = st.text_input("Reason", value="Resolve backlog", key="reason")
            if st.button("🚚 Assign Trucks to Rake", use_container_width=True):
                trucks = [t.strip() for t in assign_trucks_str.split(",") if t.strip()]
                tid = db_insert_assignment(sel_rake, trucks, lane, reason)
                st.success(f"✓ Assigned {len(trucks)} trucks. Task ID: {tid}")
                st.rerun()

            with st.expander("⚠️ Create Exception / Case"):
                wagon_choices = [w['wagon_no'] for w in w_items]
                cw = st.selectbox("Wagon", options=wagon_choices, key="wagon_sel")
                ctype = st.selectbox("Case Type", ["SHORTAGE","DAMAGE","MISSING_WAGON","OTHER"], key="case_type")
                reporter = st.text_input("Reported by", value="depot_user_01", key="reporter")
                details = st.text_area("Details", value="", key="details")
                if st.button("📝 Create Case", use_container_width=True):
                    cid = db_insert_case(sel_rake, cw, ctype, reporter, details or "Auto note")
                    st.success(f"✓ Case created: {cid}")
                    st.rerun()

            st.markdown("---")
            st.markdown("**ETA Prediction**")
            dist = st.number_input("Remaining distance (km)", value=150.0, key="dist")
            speed = st.number_input("Estimated avg speed (kmph)", value=30.0, key="speed")
            if st.button("🕐 Predict ETA", use_container_width=True):
                mins = simple_eta_predict(dist, speed)
                predicted_ts = datetime.utcnow() + timedelta(minutes=mins)
                st.info(f"⏱️ Predicted ETA in {mins} minutes → {predicted_ts.strftime('%Y-%m-%d %H:%M UTC')}")
                log_activity("INFO","ETA","Predicted ETA for "+sel_rake)

st.markdown("---")
# Lower area: details & charts
st.markdown("<div class='section-title'>📋 Rake Details & Wagon Status</div>", unsafe_allow_html=True)
colA, colB, colC = st.columns([1.8,1,1.2])
with colA:
    if not rakes_df.empty:
        selected = st.selectbox("Choose Rake to inspect", options=rakes_df['rake_id'].tolist(), key="detail_rake")
        row = db_get_rake(selected)
        if row:
            _, fnr, created_ts, station, eta_iso, wagon_text, raw = row
            items = parse_wagon_details(wagon_text)
            df_w = pd.DataFrame(items)
            # progress
            unloaded = sum(1 for w in items if w['status'].upper()=="UNLOADED")
            total = len(items)
            pct = int(0 if total==0 else (unloaded/total)*100)
            
            st.markdown(f"""
            **Progress:** {unloaded} / {total} unloaded ({pct}%)
            """)
            st.progress(pct / 100)
            
            # Enhanced wagon table with colors
            df_display = df_w.copy()
            df_display['Status'] = df_display['status'].apply(lambda x: '✓ UNLOADED' if x.upper() == 'UNLOADED' else '⏳ PENDING')
            st.dataframe(df_display[['wagon_no','Status']].rename(columns={'wagon_no':'Wagon #'}), 
                        use_container_width=True, height=300)
            
with colB:
    st.markdown("<div style='text-align: center; padding: 20px;'><strong>Activity Status</strong></div>", unsafe_allow_html=True)
    if not rakes_df.empty:
        log_df = db_get_activity_df(20)
        if not log_df.empty:
            recent = log_df.head(5)
            for _, row in recent.iterrows():
                level_icon = "🔴" if row['level'] == 'WARN' else "ℹ️"
                st.write(f"{level_icon} **{row['source']}**: {row['message'][:40]}")
        else:
            st.info("No recent activity")

with colC:
    st.markdown("<div style='text-align: center; padding: 20px;'><strong>Case Summary</strong></div>", unsafe_allow_html=True)
    cases_df = db_get_cases_df()
    if not cases_df.empty:
        case_counts = cases_df['case_type'].value_counts()
        st.bar_chart(case_counts)
    else:
        st.info("No cases")

st.markdown("---")
# Analytics charts section
st.markdown("<div class='section-title'>📊 Advanced Analytics</div>", unsafe_allow_html=True)

if not rakes_df.empty:
    ana1, ana2 = st.columns(2)
    
    with ana1:
        # Pending vs Unloaded comparison
        chart_df = rakes_df[['rake_id','pending_count','unloaded_count']].sort_values('pending_count', ascending=False)
        fig_comp = px.bar(chart_df, x='rake_id', y=['pending_count','unloaded_count'],
                         labels={'rake_id':'Rake ID', 'pending_count':'Pending', 'unloaded_count':'Unloaded'},
                         title="Pending vs Unloaded Wagons by Rake",
                         barmode='group', color_discrete_map={'pending_count':'#ed8936', 'unloaded_count':'#48bb78'})
        fig_comp.update_layout(height=400)
        st.plotly_chart(fig_comp, use_container_width=True)
    
    with ana2:
        # Risk heatmap
        display_risk = rakes_df[['rake_id','pending_count']].copy()
        display_risk['risk_level'] = display_risk['pending_count'].apply(lambda x: 1 if compute_d_and_w_risk(int(x))[0] == 'HIGH' else (2 if compute_d_and_w_risk(int(x))[0] == 'MEDIUM' else 3))
        fig_heat = px.bar(display_risk.sort_values('pending_count', ascending=False), 
                         x='rake_id', y='risk_level',
                         color='risk_level', color_continuous_scale='RdYlGn',
                         labels={'rake_id':'Rake ID', 'risk_level':'Risk Level'},
                         title="Risk Level by Rake")
        fig_heat.update_layout(height=400, showlegend=False)
        st.plotly_chart(fig_heat, use_container_width=True)
    
    # Assignment history
    st.markdown("<div style='margin-top: 20px;'></div>", unsafe_allow_html=True)
    assign_df = db_get_assignments_df()
    if not assign_df.empty:
        st.subheader("🚚 Recent Truck Assignments")
        display_assign = assign_df[['rake_id','truck_ids','lane_from','reason','created_ts']].head(10)
        display_assign['created_ts'] = display_assign['created_ts'].dt.strftime("%Y-%m-%d %H:%M")
        st.dataframe(display_assign.rename(columns={'rake_id':'Rake','truck_ids':'Trucks','lane_from':'Lane','reason':'Reason','created_ts':'Time'}), 
                    use_container_width=True)
    
    # Cases overview
    cases_df = db_get_cases_df()
    if not cases_df.empty:
        st.subheader("⚠️ Exception Cases")
        display_cases = cases_df[['case_id','rake_id','wagon_no','case_type','reported_by','reported_ts']].head(10)
        display_cases['reported_ts'] = display_cases['reported_ts'].dt.strftime("%Y-%m-%d %H:%M")
        st.dataframe(display_cases.rename(columns={'case_id':'Case ID','rake_id':'Rake','wagon_no':'Wagon','case_type':'Type','reported_by':'Reporter','reported_ts':'Time'}), 
                    use_container_width=True)
else:
    st.info("📊 No analytics data available. Create a rake to populate the dashboard.")

st.markdown("---")
st.caption("🚀 Pro Depot Dashboard — Replace backend calls with FOIS/Kafka/RAG/ML services for production.")
