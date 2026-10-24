import sqlite3
import pandas as pd
import os
import math
from datetime import datetime
from PIL import Image
import imagehash

DB_NAME = "saathi.db"

# ==========================================
# 1. DATABASE INITIALIZATION & SCHEMA
# ==========================================

def initialize_database():
    """Initializes the SQLite database with multi-table architecture:
    1. 'distress_reports' for incoming animal cases with perceptual hashing & priority triage.
    2. 'rescue_centers' for nearby veterinary hospitals and rescue vans.
    """
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # Table 1: Distress Reports (Fixed comma bug & added strict constraints)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS distress_reports (
            report_id INTEGER PRIMARY KEY AUTOINCREMENT,
            animal_type TEXT NOT NULL,
            injury_severity INTEGER NOT NULL,   -- Scale 1 (Minor) to 5 (Critical)
            is_baby INTEGER NOT NULL,           -- 1 if puppy/kitten, 0 otherwise
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            location_name TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            status TEXT DEFAULT 'Pending',      -- 'Pending', 'Dispatched', 'Resolved'
            urgency_score REAL DEFAULT 0.0,     
            photographer_id TEXT NOT NULL,
            image_hash TEXT UNIQUE NOT NULL,
            assigned_center_id INTEGER,
            FOREIGN KEY (assigned_center_id) REFERENCES rescue_centers(center_id)
        )
    """)

    # Table 2: Rescue Centers / Vets
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS rescue_centers (
            center_id INTEGER PRIMARY KEY AUTOINCREMENT,
            center_name TEXT NOT NULL,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            available_vans INTEGER NOT NULL,
            contact_number TEXT NOT NULL
        )
    """)
    
    conn.commit()
    conn.close()
    print("BEZUBAAN Saathi Master Database initialized successfully!")


# ==========================================
# 2. DISTANCE CALCULATION (Haversine Formula)
# ==========================================
def calculate_distance(lat1, lon1, lat2, lon2):
    """Calculates straight-line distance in kilometers between two lat/lon pairs."""
    R = 6371.0  # Earth radius in km
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


# ==========================================
# 3. TRIAGE SCORING ENGINE
# ==========================================

def compute_urgency_score(severity, is_baby, distance_km, hours_elapsed):
    """Calculates a mathematical priority score for rescue dispatch.
    - Severity (1-5): High weight (15 pts per level)
    - Vulnerability (Baby): +15 bonus pts
    - Proximity (Distance): Closer cases get higher priority boost
    - Wait Time: +2 pts per hour waiting
    """
    severity_score = severity * 15.0
    baby_bonus = 15.0 if is_baby else 0.0
    proximity_score = max(0.0, 30.0 - (distance_km * 3.0))
    time_score = hours_elapsed * 2.0

    total_score = severity_score + baby_bonus + proximity_score + time_score
    return round(total_score, 2)


# ==========================================
# 4. PERCEPTUAL IMAGE HASHING (pHash)
# ==========================================
def compute_image_hash(image_path):
    """Generates a perceptual hash fingerprint to catch compressed duplicates."""
    if not os.path.exists(image_path):
        return None
    try:
        img = Image.open(image_path)
        return str(imagehash.phash(img))
    except Exception as e:
        print(f"⚠️ Error reading image {image_path}: {e}")
        return None


# ==========================================
# 5. CORE BACKEND INGESTION & UI FUNCTIONS
# ==========================================
def get_nearest_center_distance(lat, lon):
    """Finds the distance to the nearest rescue center."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT latitude, longitude FROM rescue_centers")
    centers = cursor.fetchall()
    conn.close()
    
    default_lat, default_lon = 29.8649, 77.8965 # Campus fallback
    
    if centers:
        return min([calculate_distance(lat, lon, c[0], c[1]) for c in centers])
    else:
        return calculate_distance(lat, lon, default_lat, default_lon)

    
def ingest_report_with_hash(animal_type, severity, is_baby, lat, lon, location_name, photographer_id, image_path):
    """Unified ingestion pipeline: checks image hash duplication, 
    calculates automated timestamp, and inserts the record safely.
    """
    img_hash = compute_image_hash(image_path)
    if not img_hash:
        print(f"⚠️ Error: Image file '{image_path}' not found. Cannot process report.")
        return False

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Check if this exact photo was already submitted
    cursor.execute("SELECT report_id FROM distress_reports WHERE image_hash = ?", (img_hash,))
    existing = cursor.fetchone()
    if existing:
        print(f"🛑 Duplicate blocked! Matches Report ID #{existing[0]}. Rescuers saved from a redundant trip!")
        conn.close()
        return False

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Insert unique record
    cursor.execute("""
        INSERT INTO distress_reports 
        (animal_type, injury_severity, is_baby, latitude, longitude, location_name, timestamp,photographer_id, image_hash)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (animal_type, severity, int(is_baby), lat, lon, location_name,now_str,photographer_id,img_hash))

    conn.commit()
    conn.close()
    
    # Recalculate priority queue scores immediately
    update_all_urgency_scores()
    print("✅ Success! New distress case logged with a unique auto-increment ID.")
    return True


def update_all_urgency_scores():
    """Recalculates scores for all pending cases based on nearest rescue center."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("SELECT latitude, longitude FROM rescue_centers")
    centers = cursor.fetchall()
    
    default_lat, default_lon = 29.8649, 77.8965

    cursor.execute("""
        SELECT report_id, injury_severity, is_baby, latitude, longitude, timestamp 
        FROM distress_reports WHERE status = 'Pending'
    """)
    reports = cursor.fetchall()

    for r in reports:
        report_id, severity, is_baby, r_lat, r_lon, timestamp_str = r
        
        if centers:
            min_dist = min([calculate_distance(r_lat, r_lon, c[0], c[1]) for c in centers])
        else:
            min_dist = calculate_distance(r_lat, r_lon, default_lat, default_lon)

        report_time = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
        hours_elapsed = (datetime.now() - report_time).total_seconds() / 3600.0

        score = compute_urgency_score(severity, is_baby, min_dist, hours_elapsed)

        cursor.execute("UPDATE distress_reports SET urgency_score = ? WHERE report_id = ?", (score, report_id))

    conn.commit()
    conn.close()


def get_priority_queue():
    """Fetches all pending rescue reports ordered by highest urgency score for Streamlit."""
    update_all_urgency_scores()
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT report_id, animal_type, injury_severity, is_baby, location_name, 
               timestamp, status, urgency_score 
        FROM distress_reports 
        WHERE status = 'Pending'
        ORDER BY urgency_score DESC
    """)
    rows = cursor.fetchall()
    conn.close()
    return rows


def dispatch_rescue_team(report_id):
    """Relational dispatch engine: 
    1. Finds the closest rescue center with available vans.
    2. Decrements its available van count (-1).
    3. Updates the report status to 'Dispatched' and links the assigned_center_id.
    """
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")
    
    # 1. Get report coordinates
    cursor.execute("SELECT latitude, longitude, status FROM distress_reports WHERE report_id = ?", (report_id,))
    report = cursor.fetchone()
    
    if not report:
        print(f"⚠️ Report ID #{report_id} not found.")
        conn.close()
        return False

    r_lat, r_lon, status = report
    
    if status == 'Dispatched':
        print(f"⚠️ Report #{report_id} is already dispatched!")
        conn.close()
        return False

    # 2. Find nearest rescue center with at least 1 available van
    cursor.execute("SELECT center_id, latitude, longitude, available_vans FROM rescue_centers WHERE available_vans > 0")
    centers = cursor.fetchall()
    
    if not centers:
        print("🛑 Critical: No ambulance vans available at any rescue center right now!")
        conn.close()
        return False

    best_center_id = None
    min_dist = float('inf')

    for c in centers:
        c_id, c_lat, c_lon, _ = c
        dist = calculate_distance(r_lat, r_lon, c_lat, c_lon)
        if dist < min_dist:
            min_dist = dist
            best_center_id = c_id

    # 3. Perform the relational update & inventory decrement transaction
    # Decrement van count
    cursor.execute("""
        UPDATE rescue_centers 
        SET available_vans = available_vans - 1 
        WHERE center_id = ?
    """, (best_center_id,))

    # Update report status and lock in the foreign key
    cursor.execute("""
        UPDATE distress_reports 
        SET status = 'Dispatched', assigned_center_id = ? 
        WHERE report_id = ?
    """, (best_center_id, report_id))

    conn.commit()
    conn.close()
    
    print(f"Success! Report #{report_id} dispatched via Center ID #{best_center_id}. Van count decremented.")
    return True


# ==========================================
# 6. MOCK DATA GENERATOR (For Testing/Demo)
# ==========================================
def seed_mock_data():
    """Populates database with realistic mock centers and test cases."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("DELETE FROM distress_reports")
    cursor.execute("DELETE FROM rescue_centers")

    # Add Rescue Centers
    rescue_centers = [
        ("IIT Roorkee Animal Care Cell", 29.8649, 77.8965, 2, "+91 9876543210"),
        ("Civil Lines Vet Hospital", 29.8601, 77.8890, 1, "+91 9876543211")
    ]
    cursor.executemany("""
        INSERT INTO rescue_centers (center_name, latitude, longitude, available_vans, contact_number)
        VALUES (?, ?, ?, ?, ?)
    """, rescue_centers)

    conn.commit()
    conn.close()


def view_live_database():
    """Dumps the live contents of the database for verification."""
    conn = sqlite3.connect(DB_NAME)
    df_live = pd.read_sql("SELECT * FROM distress_reports", conn)
    conn.close()
    
    print("\n📊 --- CURRENT LIVE DATABASE ---")
    if df_live.empty:
        print("Database is currently empty.")
    else:
        print(df_live.to_string(index=False))
    print("--------------------------------\n")


if __name__ == "__main__":
    initialize_database()
    seed_mock_data()
    
    print("\n--- TESTING MASTER BACKEND WITH JEE PHOTOS ---")
    
    # Test 1: Ingest original JEE photo
    ingest_report_with_hash(
        animal_type="Dog",
        severity=4,
        is_baby=1,
        lat=29.8651,
        lon=77.8964,
        location_name="Hostel 14 Gate",
        photographer_id="shivi_07",
        image_path="photo.jpg"
    )
    
    # Test 2: Ingest compressed duplicate (Should be blocked!)
    ingest_report_with_hash(
        animal_type="Dog",
        severity=4,
        is_baby=1,
        lat=29.8651,
        lon=77.8964,
        location_name="Hostel 14 Gate",
        photographer_id="shivi_07",
        image_path="photo1.jpg"
    )
    
    view_live_database()