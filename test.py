import pyodbc

# Define your DSN name
dsn_name = 'AdherenceTracker'  # Replace this with your actual DSN name

try:
    # Establish the connection using DSN
    conn = pyodbc.connect(f'DSN={dsn_name};DATABASE=Adherence_Tracker;Trusted_Connection=yes;')
    
    # Create a cursor object
    cursor = conn.cursor()

    # Execute the SQL query
    cursor.execute("SELECT * FROM task")

    # Fetch and print all rows
    rows = cursor.fetchall()
    for row in rows:
        print(row)

    # Close the connection
    cursor.close()
    conn.close()

except Exception as e:
    print("Error:", e)
