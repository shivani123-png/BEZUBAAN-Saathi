import streamlit as st
import pandas as pd
import os
from backend5 import (
    initialize_database, 
    seed_mock_data, 
    ingest_report_with_hash, 
    get_priority_queue, 
    dispatch_rescue_team
)
import sqlite3

# --- PAGE CONFIGURATION ---
st.set_page_config(
    page_title="BEZUBAAN Saathi | Emergency Rescue Dispatch",
    page_icon="🐾",
    layout="wide"
)

# Initialize DB & Mock Centers on startup
initialize_database()
seed_mock_data()

# --- APP HEADER ---
st.title("BEZUBAAN Saathi")
st.markdown("*IIT Roorkee Campus Emergency Response Network*")
st.markdown("---")

# Create Navigation Tabs
tab1, tab2, tab3 = st.tabs(["📝 Report Distress Case", "⚡ Dispatcher Command Queue", "🏥 Rescue Fleet Status"])

# ==========================================
# TAB 1: CITIZEN REPORTING PORTAL
# ==========================================
with tab1:
    st.subheader("Report an Injured or Distressed Stray Animal")
    st.write("Upload a photo and details to instantly alert our campus rescue team.")

    with st.form("distress_form"):
        col1, col2 = st.columns(2)
        
        with col1:
            animal_type = st.selectbox("Animal Type", ["Dog", "Cat", "Puppy", "Kitten", "Cow", "Other"])
            injury_severity = st.slider("Injury Severity (1 = Minor Scratch, 5 = Critical / Life Threatening)", 1, 5, 3)
            is_baby_choice = st.selectbox("Is it a baby / infant animal?", ["No", "Yes"])
            is_baby = 1 if is_baby_choice == "Yes" else 0

        with col2:
            photographer_id = st.text_input("Your Name / NetID", value="shivi_07")
            location_name = st.text_input("Campus Location Name", value="Hostel 14 Gate")
            # Defaulting to IIT Roorkee coordinates for campus simulation
            lat = st.number_input("Latitude", value=29.8651, format="%.4f")
            lon = st.number_input("Longitude", value=77.8964, format="%.4f")

        # File uploader for the photo (crucial for pHash duplicate defense!)
        uploaded_file = st.file_uploader("Upload Animal Photo (Required for Duplicate Protection)", type=["jpg", "jpeg", "png"])

        submit_btn = st.form_submit_button("Submit Emergency Report 🚀")

        if submit_btn:
            if uploaded_file is not None:
                # Save uploaded file temporarily so backend can read it with imagehash
                temp_image_path = "temp_upload.jpg"
                with open(temp_image_path, "wb") as f:
                    f.write(uploaded_file.getbuffer())

                # Call your backend ingestion pipeline!
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
                    st.success("✅ Emergency case logged successfully! Urgency calculated and route assigned.")
                else:
                    st.error("🛑 Duplicate Image Blocked! This exact photo was already reported. Rescuers saved from a redundant trip!")
                
                # Cleanup temp file
                if os.path.exists(temp_image_path):
                    os.remove(temp_image_path)
            else:
                st.warning("⚠️ Please upload a photo of the animal to proceed.")

# ==========================================
# TAB 2: DISPATCHER COMMAND QUEUE
# ==========================================
with tab2:
    st.subheader("⚡ Live Priority Triage Queue")
    st.write("Pending rescue cases sorted automatically by urgency score (Severity + Baby Bonus + Distance + Wait Time).")
    
    if st.button("🔄 Refresh Queue"):
        st.rerun()

    # Fetch data from your backend function
    raw_queue = get_priority_queue()

    if not raw_queue:
        st.info("🎉 All clear! No pending distress cases right now.")
    else:
        # Convert tuple list to a clean Pandas DataFrame for display
        df_queue = pd.DataFrame(raw_queue, columns=[
            "Report ID", "Animal Type", "Severity", "Is Baby", 
            "Location", "Timestamp", "Status", "Urgency Score"
        ])

        # Style dataframe for gorgeous UI
        st.dataframe(df_queue, use_container_width=True)

        st.markdown("### 🚑 Ambulance Dispatch Console")
        report_to_dispatch = st.number_input("Enter Report ID to Dispatch", min_value=1, step=1)
        
        if st.button("Deploy Rescue Van 🚐"):
            dispatch_rescue_team(report_to_dispatch)
            st.success(f"Successfully dispatched ambulance for Report ID #{report_to_dispatch}!")
            st.rerun()

# ==========================================
# TAB 3: RESCUE FLEET STATUS
# ==========================================
with tab3:
    st.subheader("🏥 Partner Veterinary Centers & Fleet Status")
    st.write("Real-time availability of rescue vehicles across partner facilities.")

    conn = sqlite3.connect("straycare.db")
    df_centers = pd.read_sql("SELECT * FROM rescue_centers", conn)
    conn.close()

    st.dataframe(df_centers, use_container_width=True)