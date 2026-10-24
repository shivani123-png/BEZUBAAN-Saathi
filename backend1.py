import sqlite3
import pandas as pd
import os
from PIL import Image 
import imagehash

DB_NAME = "straycare.db"

def initialize_database():
    """Initializes the SQLite database and creates the distress_reports table 
    with an auto-incrementing primary key (i.e the report id here) to ensure every single animal case 
    gets its own unique ID safely and with an image_hash column to store the digital fingerprint of 
    every uploaded rescue photo.
    """
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS distress_reports (
            report_id INTEGER PRIMARY KEY AUTOINCREMENT,
            animal_type TEXT NOT NULL,
            injury_severity INTEGER NOT NULL,
            is_baby INTEGER NOT NULL,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            location_name TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            photographer_id TEXT NOT NULL,
            image_hash TEXT UNIQUE NOT NULL
        )
    """)
    
    conn.commit()
    conn.close()
    print("✨ Database initialized successfully with auto-incrementing primary key!")

def ingest_mehul_csv(csv_path="campus_cases.csv"):
    """Ingests Mehul's mock CSV file safely. 
    Strips any incoming manual IDs so SQLite auto-generates clean, 
    unique primary keys, preventing accidental data collisions.
    """
    if not os.path.exists(csv_path):
        print(f"⚠️ Warning: CSV file '{csv_path}' not found yet. Ask Mehul to send it over!")
        return

    conn = sqlite3.connect(DB_NAME)
    
    # Read raw CSV data
    df_new = pd.read_csv(csv_path)
    
    # Drop 'report_id' if Mehul accidentally included it, letting SQLite auto-increment
    if 'report_id' in df_new.columns:
        df_new = df_new.drop(columns=['report_id'])
        
    # Append to SQLite — primary keys handle uniqueness automatically!
    df_new.to_sql("distress_reports", conn, if_exists="append", index=False)
    
    print(f"✅ Successfully ingested {len(df_new)} rows into SQLite database!")
    conn.close()

def view_live_database():
    """Dumps the live contents of the database to the terminal for verification."""
    conn = sqlite3.connect(DB_NAME)
    df_live = pd.read_sql("SELECT * FROM distress_reports", conn)
    conn.close()
    
    print("\n📊 --- CURRENT LIVE DATABASE ---")
    if df_live.empty:
        print("Database is currently empty.")
    else:
        print(df_live)
    print("--------------------------------\n")

if __name__ == "__main__":
    # 1. Setup the DB
    initialize_database()
    
    # 2. Ingest mock data if Mehul provided the CSV
    ingest_mehul_csv()
    
    # 3. Print current contents to verify
    view_live_database()