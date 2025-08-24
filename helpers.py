import pyodbc
from datetime import datetime, date, timedelta
from flask import session, jsonify

def get_db_connection():
    return pyodbc.connect('DSN=AdherenceTracker')

def get_user(emp_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT emp_id, name, password, role, process FROM cred WHERE emp_id = ?", emp_id)
    rows = cursor.fetchall()
    conn.close()
    if rows:
        # Take the first row for name/password/role
        user = {
            'emp_id': rows[0].emp_id,
            'name': rows[0].name,
            'password': rows[0].password,
            'role': rows[0].role,

            # Aggregate all processes into a list
            'process': [row.process for row in rows]
        }
        print("@@@@@@@@@@@@@@@@@@@@@",user["process"])
        return user
    else:
        return None


def get_tasks_for_process(process):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT TaskName FROM Process_Tasks WHERE ProcessName = ?", process)
    tasks = [row.TaskName for row in cursor.fetchall()]
    conn.close()
    return tasks

#from datetime import datetime, date, timedelta

def store_login(emp_id):
    today = date.today()
    tomorrow = today + timedelta(days=1)
    conn = get_db_connection()
    cursor = conn.cursor()
    login_time = datetime.now()
    cursor.execute("""
        INSERT INTO logs (emp_id, activity_type, description, timestamp)
        VALUES (?, ?, ?, ?)""",
        (emp_id, 'login', 'User logged in', login_time))

    # Check if already stored
    cursor.execute("SELECT * FROM logins WHERE emp_id = ? AND log_date = ?", (emp_id, today))
    if not cursor.fetchone():
        # Get first login from logs table
        cursor.execute("""
            SELECT MIN(timestamp) FROM logs
            WHERE emp_id = ? AND activity_type = 'login'
            AND timestamp >= ? AND timestamp < ?
        """, (emp_id, today, tomorrow))

        first_login_row = cursor.fetchone()
        if first_login_row and first_login_row[0]:
            login_datetime = first_login_row[0]
            login_time = login_datetime.time()

            # Store in logins table
            cursor.execute("""
                INSERT INTO logins (emp_id, login_time, log_date)
                VALUES (?, ?, ?)
            """, emp_id, login_time, today)
            conn.commit()

    conn.close()


def store_logout(emp_id):
    today = date.today()
    tomorrow = today + timedelta(days=1)
    now = datetime.now()
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
            INSERT INTO logs (emp_id, activity_type, description, timestamp)
            VALUES (?, ?, ?, ?)
        """, emp_id, 'logout', 'User logged out', datetime.now())

    # Get existing login record
    cursor.execute("SELECT id, login_time FROM logins WHERE emp_id = ? AND log_date = ?", (emp_id, today))
    row = cursor.fetchone()

    if row:
        login_id = row.id
        login_time = row.login_time  # SQL time object

        # Fetch last logout timestamp from logs table
        cursor.execute("""
            SELECT MAX(timestamp) FROM logs
            WHERE emp_id = ? AND activity_type = 'logout'
            AND timestamp >= ? AND timestamp < ?
        """, emp_id, today, tomorrow)
        last_logout_row = cursor.fetchone()

        if last_logout_row and last_logout_row[0]:
            logout_datetime = last_logout_row[0]

            # Convert stored login time into datetime
            login_datetime = datetime.combine(today, login_time)
            duration = logout_datetime - login_datetime
            duration_str = str(duration).split('.')[0]  # Format as HH:MM:SS

            # Update logout_time and duration
            cursor.execute("""
                UPDATE logins
                SET logout_time = ?, duration = ?
                WHERE id = ?
            """, logout_datetime.time(), duration_str, login_id)
            conn.commit()

    conn.close()



def format_seconds(seconds):
    seconds = int(seconds)
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    return f"{hours:02}:{minutes:02}:{secs:02}"


def get_active_activity_counts(cursor, selected_process_list):
    """
    Retrieves the count of currently active activities grouped by activity_type
    from the AssociateActivity table.
    """
    placeholders = ','.join(['?'] * len(selected_process_list))
    query_active_counts = f"""
        SELECT aa.activity_type, COUNT(*) 
        FROM Current_Activity aa
        JOIN cred u ON aa.emp_id = u.emp_id
        WHERE u.process IN ({placeholders})
        GROUP BY aa.activity_type
    """
    cursor.execute(query_active_counts, selected_process_list)
    active_counts_data = cursor.fetchall()

    # Initialize counts
    counts = {'task': 0, 'break': 0, 'session': 0}
    for activity_type, count in active_counts_data:
        activity_type_lower = activity_type.lower()
        if activity_type_lower in counts:
            counts[activity_type_lower] = count

    return counts

def calculate_duration(start_time):
    from datetime import datetime
    now = datetime.now()
    if isinstance(start_time, datetime):
        delta = now - start_time
        hours, remainder = divmod(delta.total_seconds(), 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{int(hours):02}:{int(minutes):02}:{int(seconds):02}"
    else:
        return "00:00:00"
    
def authenticate_user(emp_id, password):
    user = get_user(emp_id)
    if user and user['password'] == password:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM cred WHERE emp_id=? AND password=?", emp_id, password)
        user_row = cursor.fetchone()
        conn.close()
        if user_row:
            return {
                'emp_id': user_row.emp_id,
                'name': user_row.name,
                'role': user_row.role,
                'process': user_row.process
            }
    return None

def set_user_session(user):
    session['emp_id'] = user['emp_id']
    session['name'] = user['name']
    session['role'] = user['role']
    session['process'] = user['process']
    session['user'] = {
        'emp_id': user['emp_id'],
        'role': user['role'],
        'process': user['process']
    }

def get_active_session(emp_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    check_query = """
    SELECT TOP 1 id, 'Task' AS type, start_time 
    FROM task 
    WHERE emp_id = ? AND CAST(start_time AS DATE) = CAST(GETDATE() AS DATE) AND stop_time IS NULL
    UNION
    SELECT TOP 1 id, 'Break' AS type, start_time 
    FROM breaks 
    WHERE emp_id = ? AND CAST(start_time AS DATE) = CAST(GETDATE() AS DATE) AND stop_time IS NULL
    UNION
    SELECT TOP 1 id, 'Session' AS type, start_time 
    FROM session_time 
    WHERE emp_id = ? AND CAST(start_time AS DATE) = CAST(GETDATE() AS DATE) AND stop_time IS NULL
    ORDER BY start_time ASC
    """
    cursor.execute(check_query, emp_id, emp_id, emp_id)
    active_session = cursor.fetchone()
    conn.close()
    if active_session:
        return {
            'id': active_session.id,
            'type': active_session.type,
            'start_time': str(active_session.start_time)
        }
    return None


def fetch_latest_live_activities(cursor, selected_process_list, placeholders):
    today = datetime.now().date()

    query = f"""
        SELECT 
            u.name, 
            t.activity_name, 
            t.start_time, 
            'Task' AS activity_type
        FROM task t
        JOIN cred u ON t.emp_id = u.emp_id
        WHERE u.process IN ({placeholders})
          AND t.stop_time IS NULL
          AND CAST(t.start_time AS DATE) = CAST(GETDATE() AS DATE)

        UNION ALL

        SELECT 
            u.name, 
            b.activity_name, 
            b.start_time, 
            'Break' AS activity_type
        FROM breaks b
        JOIN cred u ON b.emp_id = u.emp_id
        WHERE u.process IN ({placeholders})
          AND b.stop_time IS NULL
          AND CAST(b.start_time AS DATE) = CAST(GETDATE() AS DATE)

        UNION ALL

        SELECT 
            u.name, 
            s.activity_name, 
            s.start_time, 
            'Session' AS activity_type
        FROM session_time s
        JOIN cred u ON s.emp_id = u.emp_id
        WHERE u.process IN ({placeholders})
          AND s.stop_time IS NULL
          AND CAST(s.start_time AS DATE) = CAST(GETDATE() AS DATE)
    """

    cursor.execute(query, selected_process_list * 3)  # repeat for each subquery

    rows = cursor.fetchall()

    # Organize activities by name and pick the latest per user
    user_activities = {}
    for row in rows:
        name, activity_name, start_time, activity_type = row
        if name not in user_activities or start_time > user_activities[name]['start_time']:
            user_activities[name] = {
                'name': name,
                'activity_name': activity_name,
                'activity_type': activity_type,
                'start_time': start_time
            }

    # Format output
    latest_activities = []
    for activity in user_activities.values():
        start_time = activity['start_time']
        if start_time:
            duration = datetime.now() - start_time
            duration_str = str(duration).split('.')[0]
        else:
            duration_str = "00:00:00"
        latest_activities.append({
            'name': activity['name'],
            'activity_name': activity['activity_name'],
            'activity_type': activity['activity_type'],
            'duration': duration_str
        })

    return latest_activities


# stop all open acticities when page cancelled or refreshed
def stop_all_open_activities(emp_id):
    conn = get_db_connection()
    cursor = conn.cursor()

    # Tables to update
    table_names = ['task', 'breaks', 'session_time']
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    for table in table_names:
        cursor.execute(f"""
            UPDATE {table}
            SET 
                stop_time = ?, 
                total_duration = CONVERT(VARCHAR(8), DATEADD(SECOND, DATEDIFF(SECOND, start_time, ?), 0), 108)
            WHERE emp_id = ? AND stop_time IS NULL
        """, now, now, emp_id)


    print(table)

    # Delete from Current_Activity table
    # cursor.execute("""
    #     DELETE FROM Current_Activity
    #     WHERE emp_id = ?
    # """, emp_id)

    conn.commit()
    conn.close()

    return jsonify({'status': 'success', 'message': 'All open activities stopped for user'})

    