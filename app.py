# Importing required modules from Flask and other libraries
from flask import Flask, render_template, request, redirect, session, jsonify, url_for, send_file
from flask_socketio import SocketIO, emit
import pandas as pd
import pyodbc  # Used for SQL Server database connection
from datetime import datetime, timedelta, date  # To work with date and time
from io import BytesIO
from helpers  import get_user, get_tasks_for_process, store_login, store_logout, get_active_activity_counts,authenticate_user,set_user_session, get_active_session, stop_all_open_activities


# Initializing Flask app
app = Flask(__name__)
app.secret_key = "supersecretkey"  # Secret key to manage session security
socketio = SocketIO(app, cors_allowed_origins="*")  # Enable real-time communication via SocketIO

pd.set_option('future.no_silent_downcasting', True)

# Function to create a database connection using DSN
def get_db_connection():
    return pyodbc.connect('DSN=AdherenceTracker')

# Redirect the root URL to login page
@app.route('/')
def index():
    return redirect('/login')

# Route to handle user registration
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        data = request.form  # Get form data from the POST request
        conn = get_db_connection()
        cursor = conn.cursor()
        # Insert new user data into the cred table
        process_list = request.form.getlist('process')  # ['probe', 'profile']

        for process in process_list:
            cursor.execute("""
                INSERT INTO cred (emp_id, name, password, role, email, process)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (data['emp_id'], data['username'], data['password'], data['role'], data['email'], process))


        conn.commit()  # Save changes
        conn.close()
        return redirect('/login')  # Redirect to login after registration
    return render_template('register.html')  # Render registration page on GET request

@app.before_request
def load_active_session():
    if 'user' in session and 'active_session' not in session:
        emp_id = session['user']['emp_id']
        active_session = get_active_session(emp_id)
        if active_session:
            session['active_session'] = active_session

# Route to handle user login
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        emp_id = request.form['employee_id']
        password = request.form['password']

        user = get_user(emp_id)
        if user and user['password'] == password:
            session['emp_id'] = user['emp_id']
            session['name'] = user['name']
            session['role'] = user['role']
            session['process'] = user['process']
            
            print("@@@@@@@@@@@",user)
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM cred WHERE emp_id=? AND password=?", emp_id, password)
            user = cursor.fetchone()
            conn.close()
            session['emp_id'] = emp_id

            store_login(emp_id)  # Record login time
            if user:
                session['user'] = dict(emp_id=user.emp_id, role=user.role,process=user.process)
                return redirect('/associate' if user.role == 'associate' else '/manager')
            else:
                error = "Incorrect password"
                return render_template('login.html', error=error)
        else:
            error = "Incorrect password"
            return render_template('login.html', error=error)


    #    return "Invalid credentials"
    return render_template('login.html') # Render login page on GET or failed login

# Route to load associate dashboard
@app.route('/associate')
def associate_dashboard():
    # Restrict access to associates only
    if 'user' not in session or session['user']['role'] != 'associate':
        return redirect('/login')

    emp_id = session['user']['emp_id']
    # print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!",session.get('process'))

    
    process = session['process']
    
    tasks = get_tasks_for_process(process)

    if 'active_session' not in session:
        active_session = get_active_session(emp_id)
        if active_session:
            session['active_session'] = active_session

    login_time = datetime.now()  # Capture current login time

    conn = get_db_connection()
    cursor = conn.cursor()
    # Log the login activity in logs table
    # cursor.execute("""
    #     INSERT INTO logs (emp_id, activity_type, description, timestamp)
    #     VALUES (?, ?, ?, ?)""",
    #     emp_id, 'login', 'User logged in', login_time)
    conn.commit()
    conn.close()

    # Send login event to frontend via SocketIO
    socketio.emit('new_activity', {
        'emp_id': emp_id,
        'type': 'login',
        'desc': f'Logged in at {login_time.strftime("%H:%M:%S")}'
    }, namespace='/')

    # Render the associate dashboard
    return render_template('associate.html', emp_id=emp_id,name=session['name'], tasks=tasks, login_time=login_time.strftime('%Y-%m-%d %H:%M:%S'),active_session=session.get('active_session'))

# Route to record new activity (task/break/session)
@app.route('/activity', methods=['POST'])
def activity():
    if 'user' not in session:
        return 'Unauthorized', 401
    data = request.get_json()  # Get JSON data from POST request
    conn = get_db_connection()
    cursor = conn.cursor()
    # Log the activity in the logs table
    cursor.execute("""
        INSERT INTO logs (emp_id, activity_type, description)
        VALUES (?, ?, ?)""",
        session['user']['emp_id'], data['type'], data['description'])
    conn.commit()
    conn.close()

    # Broadcast the activity using SocketIO to all connected clients
    socketio.emit('new_activity', {
        'emp_id': session['user']['emp_id'],
        'type': data['type'],
        'desc': data['description']
    }, namespace='/', broadcast=True)
    return '', 204  # Return empty response with 204 No Content

# Route to handle user logout
@app.route('/logout', methods=['GET', 'POST'])
def logout():
    emp_id = session.get('user', {}).get('emp_id')

    # If user was logged in, log the logout activity
    if emp_id:
        store_logout(emp_id)
        conn = get_db_connection()
        cursor = conn.cursor()
        # cursor.execute("""
        #     INSERT INTO logs (emp_id, activity_type, description, timestamp)
        #     VALUES (?, ?, ?, ?)
        # """, emp_id, 'logout', 'User logged out', datetime.now())
        
        conn.commit()
        conn.close()

    if 'user' in session:
        stop_all_open_activities(session['user']['emp_id'])

    # flash("You have been logged out.", "info")
    session.clear()  # Clear session data
    return redirect('/login')



########################## Activity ###############################################

# Route to start an activity (task, break, session)
@app.route('/start', methods=['POST'])
def start_activity():
    activity_type = request.form.get('type')
    activity_name = request.form.get('label')
    session['activity_start_time'] = datetime.now().isoformat()
    session['activity_type'] = activity_type
    session['activity_name'] = activity_name

    # Insert into AssociateActivity table
    emp_id = session['user']['emp_id']
    start_time = datetime.now()

    # Prepare activity data for logging
    activity_data = {
        'emp_id': session['user']['emp_id'],
        'activity_type': session.get('activity_type'),
        'activity_name': session.get('activity_name'),
        'start_time': start_time.strftime('%Y-%m-%d %H:%M:%S'),
        'stop_time': None,
        'total_duration': None
    }
    print("emp_id:", emp_id)
    print("activity_name:", activity_name)

    conn = get_db_connection()
    cursor = conn.cursor()

    # Map activity type to corresponding table
    table_map = {
        'break': 'breaks',
        'task': 'task',
        'session': 'session_time'
    }

    table = table_map.get(activity_data['activity_type'])  # Get table name
    if not table:
        return jsonify({'status': 'error', 'message': 'Invalid activity type'}), 400

    # Insert activity log into respective table
    try: 
        cursor.execute(f"""
        INSERT INTO {table} (emp_id, activity_name, start_time, stop_time, total_duration)
        VALUES (?, ?, ?, ?, ?)""",
        activity_data['emp_id'], activity_data['activity_name'], activity_data['start_time'],
        activity_data['stop_time'], activity_data['total_duration'])

        # try: 
        # cursor.execute("""
        #     INSERT INTO Current_Activity (emp_id, activity_type, activity_name, start_time)
        #     VALUES (?, ?, ?, ?)
        # """, emp_id, activity_type, activity_name, start_time)
    except Exception as e:
        print("Error inserting into AssociateActivity:", e)


    conn.commit()
    conn.close()    

    return jsonify({'status': 'success'})

# Route to stop an activity and log it
@app.route('/stop', methods=['POST'])
def stop_activity():
    
    if 'activity_start_time' not in session:
        return 'No activity in session', 400

    start_time = datetime.fromisoformat(session.pop('activity_start_time'))
    stop_time = datetime.now()
    delta = stop_time - start_time
    duration = str(timedelta(seconds=int(delta.total_seconds())))

    activity_data = {
        'emp_id': session['user']['emp_id'],
        'activity_type': session.pop('activity_type'),
        'activity_name': session.pop('activity_name'),
        'start_time': start_time.strftime('%Y-%m-%d %H:%M:%S'),
        'stop_time': stop_time.strftime('%Y-%m-%d %H:%M:%S'),
        'total_duration': duration
    }

    conn = get_db_connection()
    cursor = conn.cursor()

    table_map = {
        'break': 'breaks',
        'task': 'task',
        'session': 'session_time'
    }

    table = table_map.get(activity_data['activity_type'])
    if not table:
        return jsonify({'status': 'error', 'message': 'Invalid activity type'}), 400

    # UPDATE the existing row (no new INSERT here)
    cursor.execute(f"""
        UPDATE {table}
        SET stop_time = ?, total_duration = ?
        WHERE emp_id = ? AND activity_name = ? AND start_time = ?
    """, activity_data['stop_time'], activity_data['total_duration'],
         activity_data['emp_id'], activity_data['activity_name'], activity_data['start_time'])
    


    # Also delete from Current_Activity table
    cursor.execute("""
        DELETE FROM Current_Activity
        WHERE emp_id = ?
    """, activity_data['emp_id'])

    conn.commit()
    conn.close()

    return jsonify({'status': 'success'})


@app.route('/stop-activity-on-exit', methods=['POST'])
# @login_required
def stop_activity_on_exit():
    if 'user' in session:
        data = request.get_data(as_text=True)
        app.logger.info(f"Tab closed event: {data}")
        print("session['user']['emp_id']",session['user']['emp_id'])
        stop_all_open_activities(session['user']['emp_id'])
    return '', 204



######## Manager Portal #############################################################

# Route to load the manager dashboard
@app.route('/manager')
def manager_dashboard():
    if 'user' not in session or session['user']['role'] != 'manager':
        return redirect('/login')

    manager_process = session.get('process', [])
    print('manager_process',manager_process)
    if isinstance(manager_process, str):
        manager_process = [manager_process]

    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    selected_process = request.args.get('process')

    if not selected_process and manager_process:
        selected_process = manager_process[0]

    if selected_process not in manager_process:
        return "Unauthorized process selected", 403

    # Setup default dates
    today = date.today()
    tomorrow = today + timedelta(days=1)

    # Prepare date filters for logins table (uses log_date column)
    login_date_filter = " AND l.log_date >= ? AND l.log_date < ?"
    login_date_params = []
    # Prepare datetime filters for other tables (task, breaks, session_time)
    activity_date_filter = " AND {alias}.start_time >= ? AND {alias}.start_time < ?"
    activity_date_params = []

    if start_date and end_date:
        try:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            end_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
            login_date_params = [start_dt.date(), end_dt.date()]
            activity_date_params = [start_dt, end_dt]
        except ValueError:
            start_dt = end_dt = None
            login_date_params = [today, tomorrow]
            activity_date_params = [datetime.combine(today, datetime.min.time()),
                                    datetime.combine(tomorrow, datetime.min.time())]
    else:
        login_date_params = [today, tomorrow]
        activity_date_params = [datetime.combine(today, datetime.min.time()),
                                datetime.combine(tomorrow, datetime.min.time())]

    conn = get_db_connection()
    cursor = conn.cursor()

    selected_process_list = [selected_process]
    placeholders = ','.join(['?'] * len(selected_process_list))
    # ______________________________________________________________________________________-

    # --- Fetch live tasks (duration) ---
    # query_live_tasks = f"""
    #     SELECT u.name, t.activity_name, t.start_time
    #     FROM task t
    #     JOIN cred u ON t.emp_id = u.emp_id
    #     WHERE u.process IN ({placeholders}) AND t.stop_time IS NULL
    # """
    # cursor.execute(query_live_tasks, selected_process_list)
    # task_associates = []
    # for row in cursor.fetchall():
    #     name, activity_name, start_time = row
    #     if start_time:
    #         # Format start_time as 'HH:MM:SS'
    #         start_time_str = start_time.strftime('%H:%M:%S')
    #     else:
    #         start_time_str = "00:00:00"
    #     task_associates.append({
    #         'name': name,
    #         'activity_name': activity_name,
    #         'start_time': start_time_str  # renamed 'duration' to 'start_time'
    #     })


    # --- Fetch live tasks (start_time) ---
    query_live_tasks = f"""
        SELECT u.name, t.activity_name, CAST(t.start_time AS TIME) AS start_time
        FROM task t
        JOIN cred u ON t.emp_id = u.emp_id
        WHERE u.process IN ({placeholders}) AND t.stop_time IS NULL AND CAST(t.start_time AS DATE) = CAST(GETDATE() AS DATE)
    """
    cursor.execute(query_live_tasks, selected_process_list)
    task_associates = []
    for row in cursor.fetchall():
        name, activity_name, start_time = row
        task_associates.append({
            'name': name,
            'activity_name': activity_name,
            'start_time': str(start_time) if start_time else "00:00:00"  # renamed 'duration' to 'start_time'
        })

    # --- Fetch live breaks ---
    query_live_breaks = f"""
        SELECT u.name, b.activity_name, CAST(b.start_time AS TIME) AS start_time
        FROM breaks b
        JOIN cred u ON b.emp_id = u.emp_id
        WHERE u.process IN ({placeholders}) AND b.stop_time IS NULL AND CAST(b.start_time AS DATE) = CAST(GETDATE() AS DATE)
    """
    cursor.execute(query_live_breaks, selected_process_list)
    break_associates = []
    for row in cursor.fetchall():
        name, activity_name, start_time = row
        # if start_time:
        #     duration = datetime.now() - start_time
        #     duration_str = str(duration).split('.')[0]
        # else:
        #     duration_str = "00:00:00"
        break_associates.append({
            'name': name,
            'activity_name': activity_name,
            # 'duration': duration_str
            'start_time': str(start_time) if start_time else "00:00:00"  
        })

    # --- Fetch live sessions ---
    query_live_sessions = f"""
        SELECT u.name, s.activity_name, CAST(s.start_time AS TIME) AS start_time
        FROM session_time s
        JOIN cred u ON s.emp_id = u.emp_id
        WHERE u.process IN ({placeholders}) AND s.stop_time IS NULL AND CAST(s.start_time AS DATE) = CAST(GETDATE() AS DATE)
    """
    cursor.execute(query_live_sessions, selected_process_list)
    session_associates = []
    for row in cursor.fetchall():
        name, activity_name, start_time = row
        # if start_time:
        #     duration = datetime.now() - start_time
        #     duration_str = str(duration).split('.')[0]
        # else:
        #     duration_str = "00:00:00"
        session_associates.append({
            'name': name,
            'activity_name': activity_name,
            # 'duration': duration_str
            'start_time': str(start_time) if start_time else "00:00:00"
        })


    # -------------------- Live Activities Query --------------------
    query_live = f"""
        SELECT u.name, s.activity_type, s.activity_name, s.start_time
        FROM cred u
        JOIN Current_Activity s ON u.emp_id = s.emp_id
        WHERE u.process IN ({placeholders})
    """
    cursor.execute(query_live, selected_process_list)
    live_activities = [{
        'name': row[0],
        'activity_type': row[1],
        'activity_name': row[2],
        'start_time': row[3]
    } for row in cursor.fetchall()]
    print("######################################",[live_activities])

    # -------------------- Logins Query --------------------
    query_logins = f"""
        SELECT c.name, l.login_time, l.logout_time, l.duration, l.log_date
        FROM logins l
        JOIN cred c ON l.emp_id = c.emp_id
        WHERE c.process IN ({placeholders}) {login_date_filter}
        ORDER BY l.log_date DESC, l.login_time DESC
    """
    cursor.execute(query_logins, selected_process_list + login_date_params)
    login_rows_raw = cursor.fetchall()

    login_rows = []
    for row in login_rows_raw:
        name, login_time, logout_time, duration, log_date = row
        login_time_str = login_time.strftime("%H:%M:%S") if login_time else ''
        logout_time_str = logout_time.strftime("%H:%M:%S") if logout_time else ''
        login_rows.append((name, login_time_str, logout_time_str, duration, log_date))

    # -------------------- Task Logs Query --------------------
    query_task = f"""
        SELECT u.name, t.activity_name, t.start_time, t.stop_time, t.total_duration
        FROM task t
        JOIN cred u ON t.emp_id = u.emp_id
        WHERE u.process IN ({placeholders}) {activity_date_filter.format(alias='t')}
    """
    cursor.execute(query_task, selected_process_list + activity_date_params)
    task_logs = [{
        'name': row[0], 'activity': row[1], 'start': row[2],
        'stop': row[3], 'duration': row[4], 'type': 'Task'
    } for row in cursor.fetchall()]

    # -------------------- Break Logs Query --------------------
    query_break = f"""
        SELECT u.name, b.activity_name, b.start_time, b.stop_time, b.total_duration
        FROM breaks b
        JOIN cred u ON b.emp_id = u.emp_id
        WHERE u.process IN ({placeholders}) {activity_date_filter.format(alias='b')}
    """
    cursor.execute(query_break, selected_process_list + activity_date_params)
    break_logs = [{
        'name': row[0], 'activity': row[1], 'start': row[2],
        'stop': row[3], 'duration': row[4], 'type': 'Break'
    } for row in cursor.fetchall()]

    # -------------------- Session Logs Query --------------------
    query_session = f"""
        SELECT u.name, s.activity_name, s.start_time, s.stop_time, s.total_duration
        FROM session_time s
        JOIN cred u ON s.emp_id = u.emp_id
        WHERE u.process IN ({placeholders}) {activity_date_filter.format(alias='s')}
    """
    cursor.execute(query_session, selected_process_list + activity_date_params)
    session_logs = [{
        'name': row[0], 'activity': row[1], 'start': row[2],
        'stop': row[3], 'duration': row[4], 'type': 'Session'
    } for row in cursor.fetchall()]



    # Combine and sort logs by start time descending
    all_logs = task_logs + break_logs + session_logs
    all_logs.sort(key=lambda x: x['start'], reverse=True)

    # -------------------- Count Active Logs Using AssociateActivity Table --------------------
    counts = get_active_activity_counts(cursor, selected_process_list)
    task_active_count = counts['task']
    break_active_count = counts['break']
    session_active_count = counts['session']

    conn.close()
    return render_template(
        'manager.html',
        login_logout_data=login_rows,
        all_logs=all_logs,
        task_count=len(task_associates),
        break_count=len(break_associates),
        session_count=len(session_associates),
        task_associates=task_associates,
        break_associates=break_associates,
        session_associates=session_associates,
        manager_process=manager_process,
        selected_process=selected_process,
        start_date=start_date,
        end_date=end_date,
    )

################# Excel Report #######################################################3



@app.route('/download-report', methods=['GET'])
def download_team_report():
    selected_process = request.args.get('process')
    print("###############################",selected_process)
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    login_date_filter = ""
    task_date_filter = ""
    break_date_filter = ""
    session_date_filter = ""

    params = []
    task_params = [selected_process]
    break_params = []
    session_params = []

    # Prepare date filters
    if start_date and end_date:
        try:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            end_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)

            login_date_filter = " AND l.log_date >= ? AND l.log_date < ?"
            task_date_filter = " AND t.start_time >= ? AND t.start_time < ?"
            break_date_filter = " WHERE start_time >= ? AND start_time < ?"
            session_date_filter = " WHERE start_time >= ? AND start_time < ?"

            params += [selected_process, start_dt, end_dt]
            task_params += [start_dt, end_dt]
            break_params += [start_dt, end_dt]
            session_params += [start_dt, end_dt]
        except ValueError:
            pass
    else:
        if selected_process:
            params.append(selected_process)

    conn = get_db_connection()
    cursor = conn.cursor()

    # Login Data
    login_query = f"""
        SELECT u.name, u.emp_id, u.process, l.login_time, l.logout_time, l.duration, l.log_date
        FROM cred u
        JOIN logins l ON u.emp_id = l.emp_id
        WHERE u.process = ? {login_date_filter}
    """
    login_df = pd.read_sql(login_query, conn, params=params)
    # print("login_df.shape",login_df.shape)
    # # print("login_df_TNW1632",login_df[login_df['emp_id'] == 'TNW1632']," ")
    # print("login_df_emp_id",login_df['emp_id'].tolist())

    print("login_df.shape", login_df.shape)
    print("login_df EMP IDs:", login_df['emp_id'].unique())
    print("Does TNW1632 exist:", 'TNW1632' in login_df['emp_id'].values)

    if login_df.empty:
        return "No login data found", 404

    # Task Data
    task_query = f"""
        SELECT t.emp_id, t.activity_name, CAST(t.start_time AS DATE) AS date,
            SUM(DATEDIFF(SECOND, 0, TRY_CAST(t.total_duration AS TIME))) AS duration
        FROM task t
        JOIN Process_Tasks pt ON t.activity_name = pt.TaskName
        WHERE pt.ProcessName = ? {task_date_filter}
        GROUP BY t.emp_id, t.activity_name, CAST(t.start_time AS DATE)
    """
    task_df = pd.read_sql(task_query, conn, params=task_params)
    task_cursor = conn.cursor()
    task_cursor.execute("SELECT TaskName FROM Process_Tasks WHERE ProcessName = ?", (selected_process,))
    task_names = [row[0] for row in task_cursor.fetchall()]
    task_pivot = task_df.pivot_table(index=["emp_id", "date"], columns="activity_name", values="duration", aggfunc="sum").fillna(0).reset_index()

    # Break Data
    break_query = f"""
        SELECT emp_id, activity_name, CAST(start_time AS DATE) AS date,
            SUM(DATEDIFF(SECOND, 0, TRY_CAST(total_duration AS TIME))) AS duration
        FROM breaks
        {break_date_filter}
        GROUP BY emp_id, activity_name, CAST(start_time AS DATE)
    """
    break_df = pd.read_sql(break_query, conn, params=break_params)
    break_pivot = break_df.pivot_table(index=["emp_id", "date"], columns="activity_name", values="duration", aggfunc="sum").fillna(0).reset_index()

    # Session Data
    session_query = f"""
        SELECT emp_id, activity_name, CAST(start_time AS DATE) AS date,
            SUM(DATEDIFF(SECOND, 0, TRY_CAST(total_duration AS TIME))) AS duration
        FROM session_time
        {session_date_filter}
        GROUP BY emp_id, activity_name, CAST(start_time AS DATE)
    """
    session_df = pd.read_sql(session_query, conn, params=session_params)
    session_pivot = session_df.pivot_table(index=["emp_id", "date"], columns="activity_name", values="duration", aggfunc="sum").fillna(0).reset_index()
    print("###########################",session_df)

    # Merge all data
    login_df.rename(columns={'log_date': 'date'}, inplace=True)
    df = login_df.merge(task_pivot, on=["emp_id", "date"], how="left")
    df = df.merge(break_pivot, on=["emp_id", "date"], how="left")
    df = df.merge(session_pivot, on=["emp_id", "date"], how="left")
    df.fillna(0, inplace=True)

    # Rename known session activities
    rename_map = {
        "Internal Meeting": "Internal Meeting",
        "External Meeting": "External Meeting",
        "Training Session": "Training",
        "Waiting for work": "Waiting For Work",
        "New Hire Training": "New Hire Training",
        "On-Job-Training": "On-Job-Training",
        "Downtime": "Downtime",
        "Team Huddle": "Team Huddle"
    }
    df.rename(columns=rename_map, inplace=True)

    for task in task_names:
        if task not in df.columns:
            df[task] = 0

    break_cols = ["Break 1", "Lunch Break", "Break 2", "RR"]
    for col in break_cols:
        if col not in df.columns:
            df[col] = 0

    session_cols = list(rename_map.values())
    for col in session_cols:
        if col not in df.columns:
            df[col] = 0

    df[break_cols + session_cols] = df[break_cols + session_cols].apply(pd.to_numeric, errors='coerce').fillna(0)
    df['Break Total Time'] = df[break_cols].sum(axis=1)
    df['Session & Downtime'] = df[session_cols].sum(axis=1)
    df['Occupancy'] = df[session_cols + task_names].sum(axis=1)
    df['Utilization'] = df[task_names].sum(axis=1)

    # print("df.shape",df.shape)
    # print("df_TNW1632",df[df['emp_id'] == 'TNW1632'])

    final_cols = ["date", "name", "emp_id", "login_time", "logout_time", "process", "duration"] + \
                 task_names + break_cols + session_cols + \
                 ["Break Total Time", "Session & Downtime", "Occupancy", "Utilization"]

    def format_seconds(seconds):
        seconds = int(seconds)
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        return f"{hours:02}:{minutes:02}:{secs:02}"

    time_columns = ["Break Total Time", "Session & Downtime", "Occupancy", "Utilization"] + task_names + break_cols + session_cols
    for col in time_columns:
        if col in df.columns:
            df[col] = df[col].apply(lambda x: format_seconds(x) if x > 0 else "0")

    df_final = df[final_cols]



    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df_final.to_excel(writer, index=False, sheet_name="Team Report")
    output.seek(0)

    report_date = start_date or datetime.today().strftime('%Y-%m-%d')
    filename = f"Team_Report_{selected_process or 'All'}_{report_date}.xlsx"
    return send_file(output, as_attachment=True, download_name=filename,
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

# Run the app with SocketIO support
if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)
