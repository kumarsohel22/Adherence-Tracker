# ⏱️ Adherence Tracker

A **Flask + SocketIO** web application that helps managers and associates track **real-time activities, adherence, and productivity**.  
Includes dashboards for **associates** and **managers**, plus **Excel-based reports**.

---

## 🚀 Features
- 🔑 **User Authentication** (Register, Login, Logout)
- 👥 **Role-based Dashboards**
  - **Associate Dashboard** → start/stop activities (task, session, break)
  - **Manager Dashboard** → view live activities of all associates
- 📊 **Reports**
  - Generate detailed **Excel reports** with occupancy/utilization metrics
- 🔔 **Real-time Updates** using **Flask-SocketIO**
- 🗄️ **Database Integration**
  - Tracks users, logins, tasks, breaks, sessions
- 📱 **Responsive UI** with clean, modern design

---

## 📂 Project Structure
Adherence-Tracker/
│── app.py # Main Flask application
│── templates/ # HTML templates
│ ├── register.html # Registration page
│ ├── login.html # Login page
│ ├── associate.html # Associate dashboard
│ ├── manager.html # Manager dashboard
│── static/ # Static assets (CSS, JS, images)
│── requirements.txt # Python dependencies
│── README.md # Project documentation
