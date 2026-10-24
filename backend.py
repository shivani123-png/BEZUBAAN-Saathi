import sqlite3
import math
from datetime import datetime

DB_NAME = "straycare.db"

# ==========================================
# 1. DATABASE INITIALIZATION & SCHEMA
# ==========================================
def init_db():
    """Initializes the SQLite database schema."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # Table 1: Distress Reports
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS distress_reports (
            report_id INTEGER PRIMARY KEY AUTOINCREMENT,
            animal_type TEXT NOT NULL,
            injury_severity INTEGER NOT NULL, -- Scale 1 (Minor) to 5 (Critical)
            is_baby BOOLEAN NOT NULL,         -- 1 if puppy/kitten, 0 otherwise
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            location_name TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            status TEXT DEFAULT 'Pending',   -- 'Pending', 'Dispatched', 'Resolved'
            urgency_score REAL DEFAULT 0.0
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


# ==========================================
# 2. DISTANCE CALCULATION (Haversine Formula)
# ==========================================
def calculate_distance(lat1, lon1, lat2, lon2):
    """
    Calculates straight-line distance in kilometers between two lat/lon pairs.
    """
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
    """
    Calculates a mathematical priority score for rescue dispatch.
    
    Formula Weights:
    - Severity (1-5): High weight (15 pts per level)
    - Vulnerability (Baby): +15 bonus pts
    - Proximity (Distance): Closer cases get higher priority boost
    - Wait Time: +2 pts per hour waiting
    """
    severity_score = severity * 15.0
    baby_bonus = 15.0 if is_baby else 0.0
    
    # Distance factor: Cases within 5 km get maximum proximity weight
    proximity_score = max(0.0, 30.0 - (distance_km * 3.0))
    
    time_score = hours_elapsed * 2.0

    total_score = severity_score + baby_bonus + proximity_score + time_score
    return round(total_score, 2)


# ==========================================
# 4. CORE BACKEND FUNCTIONS FOR UI
# ==========================================
def add_distress_report(animal_type, severity, is_baby, lat, lon, location_name):
    """Saves a new user distress report to SQLite."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cursor.execute("""
        INSERT INTO distress_reports 
        (animal_type, injury_severity, is_baby, latitude, longitude, location_name, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (animal_type, severity, int(is_baby), lat, lon, location_name, now_str))

    conn.commit()
    conn.close()
    
    # Recalculate priority queue immediately after inserting
    update_all_urgency_scores()


def update_all_urgency_scores():
    """Recalculates scores for all pending cases based on nearest rescue center."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # Get all rescue centers
    cursor.execute("SELECT latitude, longitude FROM rescue_centers")
    centers = cursor.fetchall()
    
    # Fallback default coords (Campus Center) if no centers registered
    default_lat, default_lon = 29.8649, 77.8965

    # Fetch pending reports
    cursor.execute("""
        SELECT report_id, injury_severity, is_baby, latitude, longitude, timestamp 
        FROM distress_reports WHERE status = 'Pending'
    """)
    reports = cursor.fetchall()

    for r in reports:
        report_id, severity, is_baby, r_lat, r_lon, timestamp_str = r
        
        # Calculate distance to nearest center
        if centers:
            min_dist = min([calculate_distance(r_lat, r_lon, c[0], c[1]) for c in centers])
        else:
            min_dist = calculate_distance(r_lat, r_lon, default_lat, default_lon)

        # Calculate waiting time in hours
        report_time = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
        hours_elapsed = (datetime.now() - report_time).total_seconds() / 3600.0

        # Calculate new score
        score = compute_urgency_score(severity, is_baby, min_dist, hours_elapsed)

        # Update in DB
        cursor.execute("UPDATE distress_reports SET urgency_score = ? WHERE report_id = ?", (score, report_id))

    conn.commit()
    conn.close()


def get_priority_queue():
    """Fetches all pending rescue reports ordered by highest urgency score."""
    update_all_urgency_scores() # Refresh scores before reading
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
    """Updates report status from 'Pending' to 'Dispatched'."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE distress_reports SET status = 'Dispatched' WHERE report_id = ?", (report_id,))
    conn.commit()
    conn.close()


# ==========================================
# 5. MOCK DATA GENERATOR (For Testing/Demo)
# ==========================================
def seed_mock_data():
    """Populates database with realistic campus/city mock cases."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # Clear existing data for fresh demo setup
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

    # Add Mock Cases
    mock_reports = [
        ("Dog", 5, 0, 29.8655, 77.8980, "Main Gate, Campus", "2026-10-23 06:15:00", "Pending"),
        ("Cat", 2, 1, 29.8620, 77.8910, "Subhash Bhawan Hostel", "2026-10-23 05:45:00", "Pending"),
        ("Dog", 4, 1, 29.8690, 77.9010, "Century Gate Road", "2026-10-23 06:30:00", "Pending"),
        ("Puppy", 1, 1, 29.8615, 77.8950, "Cautley Bhawan Lawn", "2026-10-23 04:00:00", "Pending")
    ]
    cursor.executemany("""
        INSERT INTO distress_reports 
        (animal_type, injury_severity, is_baby, latitude, longitude, location_name, timestamp, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, mock_reports)

    conn.commit()
    conn.close()
    
    # Calculate initial scores
    update_all_urgency_scores()


# ==========================================
# DRIVER RUN (Executes when file runs)
# ==========================================
if __name__ == "__main__":
    init_db()
    seed_mock_data()
    print("✅ StrayCare AI Database Initialized & Seeded Successfully!")
    
    print("\n--- Current Priority Queue ---")
    queue = get_priority_queue()
    for item in queue:
        print(f"ID: {item[0]} | Animal: {item[1]} | Severity: {item[2]}/5 | Location: {item[4]} | Score: {item[7]}")