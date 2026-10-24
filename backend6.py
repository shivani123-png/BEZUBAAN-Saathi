import sqlite3
import pandas as pd
import os
import math
from datetime import datetime
from PIL import Image
import imagehash
import cv2
import numpy as np

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
    
def match_local_features_orb(img_path1, img_path2, match_threshold=25):
    """Uses OpenCV ORB keypoint matching to detect identical wounds/markings 
    invariant to camera angles, lighting, or background changes!
    """
    img1 = cv2.imread(img_path1, cv2.IMREAD_GRAYSCALE)
    img2 = cv2.imread(img_path2, cv2.IMREAD_GRAYSCALE)

    if img1 is None or img2 is None:
        return False

    # Initialize ORB detector
    orb = cv2.ORB_create(nfeatures=500)
    kp1, des1 = orb.detectAndCompute(img1, None)
    kp2, des2 = orb.detectAndCompute(img2, None)

    if des1 is None or des2 is None or len(des1) == 0 or len(des2) == 0:
        return False

    # Brute Force Matcher with Hamming distance
    bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
    matches = bf.match(des1, des2)

    # Filter good matches based on distance
    good_matches = [m for m in matches if m.distance < 40]
    
    print(f"ORB Keypoint Match Count: {len(good_matches)}")
    return len(good_matches) >= match_threshold

def ingest_report_with_hash(animal_type, severity, is_baby, lat, lon, location_name, photographer_id, image_path):
    """Smart Ingestion Pipeline with Dual-Layer pHash & OpenCV ORB Matching:
    - Checks incoming image against all active 'Pending' reports.
    - Layer 1: pHash Hamming distance (loose threshold for minor shifts).
    - Layer 2: OpenCV ORB keypoint matching (for different angles, hands, backgrounds, and wound patterns).
    - If a match is found, updates the existing report's GPS, timestamp, and urgency score!
    """
    img_hash = compute_image_hash(image_path)
    if not img_hash:
        print(f"⚠️ Error: Image file '{image_path}' not found.")
        return False

    new_hash_obj = imagehash.hex_to_hash(img_hash)

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Fetch all pending reports that have hashes
    cursor.execute("SELECT report_id, image_hash, status FROM distress_reports WHERE status = 'Pending' AND image_hash IS NOT NULL")
    pending_reports = cursor.fetchall()
    
    matched_report_id = None

    # Dual-layer check against existing pending reports
    for report_id, stored_hash_str, status in pending_reports:
        try:
            stored_hash_obj = imagehash.hex_to_hash(stored_hash_str)
            phash_distance = new_hash_obj - stored_hash_obj
            
            # Layer 1: pHash distance check
            if phash_distance <= 12:
                matched_report_id = report_id
                print(f"🎯 pHash Match! Report ID #{report_id} matched with distance {phash_distance}")
                break
            
            # Layer 2: OpenCV ORB Local Feature Match (handles different angles/backgrounds!)
            stored_img_path = f"report_{report_id}.jpg"
            if os.path.exists(stored_img_path) and os.path.exists(image_path):
                if match_local_features_orb(stored_img_path, image_path):
                    matched_report_id = report_id
                    print(f"🎯 ORB Feature Match! Report ID #{report_id} matched via wound/feature patterns.")
                    break
        except Exception as e:
            continue

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    min_dist = get_nearest_center_distance(lat, lon)
    initial_urgency = compute_urgency_score(severity, is_baby, min_dist, 0.0)

    if matched_report_id:
        # UPDATE the existing Pending report with new GPS, location name, timestamp, and hash!
        cursor.execute("""
            UPDATE distress_reports 
            SET latitude = ?, 
                longitude = ?, 
                location_name = ?, 
                timestamp = ?, 
                urgency_score = ?,
                image_hash = ?
            WHERE report_id = ?
        """, (lat, lon, location_name, now_str, initial_urgency, img_hash, matched_report_id))
        
        conn.commit()
        conn.close()
        print(f"🔄 Smart Multi-Tier Update! Report ID #{matched_report_id} moved to new location ({location_name}) at [{lat}, {lon}].")
        return True
        
    else:
        # Brand new case -> Insert fresh record
        cursor.execute("""
            INSERT INTO distress_reports 
            (animal_type, injury_severity, is_baby, latitude, longitude, location_name, timestamp, status, urgency_score, photographer_id, image_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'Pending', ?, ?, ?)
        """, (animal_type, severity, int(is_baby), lat, lon, location_name, now_str, initial_urgency, photographer_id, img_hash))

        new_id = cursor.lastrowid
        conn.commit()
        conn.close()

        # Save a local copy of this report's image so future uploads can compare against it via ORB!
        try:
            Image.open(image_path).save(f"report_{new_id}.jpg")
        except Exception:
            pass
        
        print(f"✅ Success! New case logged with ID #{new_id}. Urgency Score: {initial_urgency}")
        return True
    
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

def resolve_rescue_case(report_id):
    """Marks a case as resolved and returns the rescue van back to the nearest center (+1 van)."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # 1. Find which center was handling this report or just return a van to the default/assigned center
    # For simplicity, let's look up the report and find its assigned center, or increment the first available center's van count
    cursor.execute("SELECT status FROM distress_reports WHERE report_id = ?", (report_id,))
    row = cursor.fetchone()
    
    if row and row[0] == 'Dispatched':
        # Update report status to Resolved
        cursor.execute("UPDATE distress_reports SET status = 'Resolved' WHERE report_id = ?", (report_id,))
        
        # Increment available vans back by +1 for rescue centers
        cursor.execute("UPDATE rescue_centers SET available_vans = available_vans + 1 WHERE available_vans < total_vans")
        
        conn.commit()
        conn.close()
        print(f" Case #{report_id} marked as Resolved! Van returned to fleet (+1).")
        return True
    
    conn.close()
    return False

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
        ("IIT Roorkee CCF", 29.8649, 77.8965, 2, "+91 9162889102"),
        ("Civil Lines Vet Hospital", 29.8601, 77.8890, 1, "+91 9458900025 ")
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
    
    print("\n --- CURRENT LIVE DATABASE ---")
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
        lat=29.8643,
        lon=77.8974,
        location_name="lhc",
        photographer_id="shivi_02",
        image_path="photo1.jpg"
    )
    
    view_live_database()