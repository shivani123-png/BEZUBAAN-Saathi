import streamlit as st
import pandas as pd
import os
from backend7 import (
    initialize_database, 
    seed_mock_data, 
    ingest_report_with_hash,    
    get_priority_queue, 
    resolve_rescue_case,
    dispatch_rescue_team,
    load_ai_model,
    AI_EMBEDDING_AVAILABLE
)
import sqlite3

# --- PAGE CONFIGURATION ---
st.set_page_config(
    page_title="BEZUBAAN Saathi | Emergency Rescue Dispatch",
    page_icon="🐾",
    layout="wide"
)

# Initialize DB & Mock Centers
initialize_database()
@st.cache_resource(show_spinner="Loading AI photo matcher (first time only)…")
def warm_up_ai():
    load_ai_model()
    return True

if AI_EMBEDDING_AVAILABLE:
    warm_up_ai()
if sqlite3.connect("saathi.db").execute("SELECT COUNT(*) FROM rescue_centers").fetchone()[0] == 0:
    seed_mock_data()

# --- SIDEBAR: AUTHENTICATION & ROLE SELECTION ---
st.sidebar.title("🔐 Access Portal")
user_role = st.sidebar.selectbox("Select Your Role", ["Citizen / Student", "Admin / Rescue Coordinator"])

# If Admin, ask for a secure pin/password to unlock dispatch privileges
is_admin = False
if user_role == "Admin / Rescue Coordinator":
    admin_pass = st.sidebar.text_input("Enter Admin Passcode", type="password")
    if admin_pass == "admin123":  # Simple secure passcode for hackathon demo
        is_admin = True
        st.sidebar.success("🔓 Admin Access Granted!")
    else:
        st.sidebar.warning("⚠️ Enter correct passcode for dispatch rights.")

# --- APP HEADER ---
st.title("BEZUBAAN Saathi")
st.markdown("*IIT Roorkee Campus Emergency Response Network*")
st.markdown("---")

# --- DYNAMIC TAB RENDERING BASED ON ROLE ---
if is_admin:
    # Admins see ALL THREE tabs (Report, Dispatch Queue, Fleet Status)
    tab1, tab2, tab3 = st.tabs([" Report Distress Case", " Dispatcher Command Queue", " Rescue Fleet Status"])
else:
    # Regular Citizens / Students ONLY see Reporting and Fleet Status (NO dispatch access!)
    tab1, tab3 = st.tabs([" Report Distress Case", " Rescue Fleet Status"])
    tab2 = None  # Dispatch tab doesn't exist for regular users!

# ==========================================
# TAB 1: CITIZEN REPORTING PORTAL (Visible to Everyone)
# ==========================================
with tab1:
    st.subheader("Report an Injured or Distressed Stray Animal")
    st.write("Upload a photo and details to instantly alert our campus rescue team.")

    with st.form("distress_form"):
        col1, col2 = st.columns(2)
        
        with col1:
            animal_type = st.selectbox("Animal Type", ["Dog", "Cat", "Puppy", "Kitten", "Cow", "Other"])
            injury_severity = st.slider("Injury Severity (1 = Minor Scratch, 5 = Critical)", 1, 5, 3)
            is_baby_choice = st.selectbox("Is it a baby / infant animal?", ["No", "Yes"])
            is_baby = 1 if is_baby_choice == "Yes" else 0

        with col2:
            photographer_id = st.text_input("Your Name / NetID", value="shivi_07")
            location_name = st.text_input("Campus Location Name", value="Hostel 14 Gate")
            lat = st.number_input("Latitude", value=29.8651, format="%.4f")
            lon = st.number_input("Longitude", value=77.8964, format="%.4f")

        uploaded_file = st.file_uploader("Upload Animal Photo (Duplicate Protection Active)", type=["jpg", "jpeg", "png"])
        submit_btn = st.form_submit_button("Submit Emergency Report ")

        if submit_btn:
            if uploaded_file is not None:
                temp_image_path = "temp_upload.jpg"
                with open(temp_image_path, "wb") as f:
                    f.write(uploaded_file.getbuffer())

                # Calls your smart backend update-or-insert pipeline!
                success = ingest_report_with_hash(
                    animal_type=animal_type,
                    severity=injury_severity,
                    is_baby=is_baby,
                    lat=lat,
                    lon=lon,
                    location_name=location_name,
                    photographer_id=photographer_id,
                    image_path=temp_image_path
                )

                if success:
                    st.success("✅ Case logged / location updated successfully!")
                else:
                    st.error("🛑 Duplicate blocked or status locked.")
                
                if os.path.exists(temp_image_path):
                    os.remove(temp_image_path)
            else:
                st.warning("⚠️ Please upload a photo to proceed.")

# ==========================================
# TAB 2: DISPATCHER COMMAND QUEUE (ADMIN ONLY)
# ==========================================
if is_admin and tab2 is not None:
    with tab2:
        st.subheader("Live Priority Triage Queue (Admin Console)")
        st.write("Pending rescue cases sorted by urgency score.")

        if st.button("🔄 Refresh Queue"):
            st.rerun()

        raw_queue = get_priority_queue()

        if not raw_queue:
            st.info("All clear! No pending distress cases.")
        else:
            df_queue = pd.DataFrame(raw_queue, columns=[
                "Report ID", "Animal Type", "Severity", "Is Baby", 
                "Location", "Timestamp", "Status", "Urgency Score"
            ])
            st.dataframe(df_queue, use_container_width=True)

            st.markdown("###  Ambulance Dispatch Console")
            report_to_dispatch = st.number_input("Enter Report ID to Dispatch", min_value=1, step=1)
            
            if st.button("Deploy Rescue Van "):
                if dispatch_rescue_team(report_to_dispatch):
                    st.success(f"Successfully dispatched ambulance for Report ID #{report_to_dispatch}!")
                    st.rerun()
                else:
                    st.error("Dispatch failed: no free ambulance, or this case is already dispatched. ")
        st.markdown("###  Complete Rescue & Return Ambulance")
        report_to_resolve = st.number_input("Enter Report ID to Mark as Resolved", min_value=1, step=1, key="resolve_input")
        
        if st.button("Mark Resolved & Return Ambulance"):
            if resolve_rescue_case(report_to_resolve):
                st.success(f"Rescue completed for Report ID #{report_to_resolve}! Ambulance inventory restored (+1).")
                st.rerun()
            else:
                st.error("Only a dispatched case can be resolved. ")

        # --- CAMPUS HOTSPOT ANALYTICS MAP ---
        st.markdown("### 🗺️ IIT Roorkee Campus Distress Hotspots")
        st.write("Visualizing high-frequency incident zones to help administrative teams relocate at-risk strays proactively.")
        
        # Query all report coordinates from the database
        conn = sqlite3.connect("saathi.db")
        df_map = pd.read_sql("SELECT latitude AS lat, longitude AS lon, animal_type, injury_severity, location_name FROM distress_reports", conn)
        conn.close()
        
        if not df_map.empty:
            # Streamlit's native map automatically centers and plots scatter points based on 'lat' and 'lon' columns!
            st.map(df_map, zoom=15, use_container_width=True)
            st.caption("📍 Each red pin represents a logged distress or hotspot area on campus.")
        else:
            st.info("No location data available for mapping yet.")


# ==========================================
# TAB 3: RESCUE FLEET STATUS (Visible to Everyone)
# ==========================================
with tab3:
    st.subheader(" Partner Veterinary Centers & Fleet Status")
    st.write("Real-time availability of rescue vehicles across partner facilities.")

    conn = sqlite3.connect("saathi.db")
    df_centers = pd.read_sql("SELECT * FROM rescue_centers", conn)
    conn.close()

    st.dataframe(df_centers, use_container_width=True)