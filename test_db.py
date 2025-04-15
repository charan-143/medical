import sqlite3
import os

def test_db_connection():
    db_path = os.path.join('instance', 'medical_dashboard.db')
    try:
        conn = sqlite3.connect(db_path)
        conn.close()
        return True, "Successfully created and connected to database"
    except sqlite3.Error as e:
        return False, f"Failed to connect to database: {str(e)}"

result, message = test_db_connection()
print(message)

