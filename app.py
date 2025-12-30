#!/usr/bin/env python3
import os
import requests
import pandas as pd
import sqlite3
from flask import Flask, request, render_template, redirect, url_for, flash
from dotenv import load_dotenv
from datetime import datetime
import ast

# --- Load environment ---
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
CHAT_ID = os.getenv("CHAT_ID", "")
EXCEL_FILE = "sales_reports.xlsx"
DB_FILE = "app.db"

# --- Flask setup ---
app = Flask(__name__, static_folder="static", template_folder="templates")
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "change-me")

# --- Telegram helpers ---
def tg_send_message(text: str) -> dict:
    if not BOT_TOKEN or not CHAT_ID:
        return {"ok": False, "error": "BOT_TOKEN or CHAT_ID not set"}
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        resp = requests.post(url, json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"})
        return resp.json()
    except Exception as e:
        return {"ok": False, "error": str(e)}

def tg_send_file(file, filename):
    if not BOT_TOKEN or not CHAT_ID:
        return {"ok": False, "error": "BOT_TOKEN or CHAT_ID not set"}
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
        resp = requests.post(
            url,
            files={"document": (filename, file.stream, file.mimetype)},
            data={"chat_id": CHAT_ID}
        )
        return resp.json()
    except Exception as e:
        return {"ok": False, "error": str(e)}

# --- Excel helper ---
def save_to_excel(data: dict):
    df_new = pd.DataFrame([data])
    try:
        if os.path.exists(EXCEL_FILE):
            df_old = pd.read_excel(EXCEL_FILE)
            df_all = pd.concat([df_old, df_new], ignore_index=True)
        else:
            df_all = df_new
        df_all.to_excel(EXCEL_FILE, index=False)
    except Exception as e:
        print(f"Error saving Excel: {e}")

# --- Database setup ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user TEXT,
            action TEXT,
            data TEXT,
            timestamp TEXT
        )
    """)
    conn.commit()
    conn.close()

def log_to_db(user: str, action: str, data: dict):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT INTO logs (user, action, data, timestamp) VALUES (?, ?, ?, ?)",
              (user, action, str(data), datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()

def get_last_record():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT data FROM logs ORDER BY id DESC LIMIT 1")
    row = c.fetchone()
    conn.close()
    if row:
        try:
            return ast.literal_eval(row[0])
        except:
            return {}
    return {}

# --- Clean/format data ---
def clean_record(record: dict) -> dict:
    cleaned = {}
    for k, v in record.items():
        if isinstance(v, str):
            val = v.strip()
            if val == "":
                val = "-"
            cleaned[k] = val
        else:
            cleaned[k] = v
    return cleaned

# --- Routes ---
@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        fields = ["date","time","shift","staff","total_money","aba_usd","aba_khr",
                  "acleda_usd","acleda_khr","other_bank","cash_usd","cash_khr",
                  "expense","balance_status","balance_amount"]

        # Build record
        record = {field.capitalize().replace("_"," "): request.form.get(field,"") for field in fields}
        record["Submitted At"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 🔥 Clean data before saving/sending
        record = clean_record(record)

        # Save to Excel and DB
        save_to_excel(record)
        log_to_db(record.get("Staff","unknown"), "Submitted Sales Report", record)

        # Build Telegram message using already-cleaned record
        message = (
            f"🛒 <b>របាយការណ៍លក់</b>\n"
            f"📅 កាលបរិច្ឆេទ: <b>{record.get('Date')}</b>\n"
            f"⏰ ម៉ោង: {record.get('Time')}\n"
            f"⏰ វេន: {record.get('Shift')}\n"
            f"👤 បុគ្គលិក: <b>{record.get('Staff')}</b>\n\n"
            f"💵 <b>លុយសរុប:</b> {record.get('Total money')}\n"
            f"🏦 ABA ($): {record.get('Aba usd')} | ABA (៛): {record.get('Aba khr')}\n"
            f"🏦 ACLEDA ($): {record.get('Acleda usd')} | ACLEDA (៛): {record.get('Acleda khr')}\n"
            f"🏦 Other Bank: {record.get('Other bank')}\n\n"
            f"💰 Cash ($): {record.get('Cash usd')} | Cash (៛): {record.get('Cash khr')}\n\n"
            f"💸 ចំណាយ: {record.get('Expense')}\n"
            f"⚖️ លើស/បាត: {record.get('Balance status')} {record.get('Balance amount')}\n"
        )
        send_res = tg_send_message(message)

        # Handle file attachment
        file = request.files.get("attachment")
        if file and file.filename:
            file_res = tg_send_file(file, file.filename)
            if not file_res.get("ok"):
                flash(f"❌ Failed to send file: {file_res.get('error')}", "error")

        if send_res.get("ok"):
            flash("✅ Sales report sent & saved", "success")
            return redirect(url_for("index") + "?clear_draft=1")
        else:
            flash(f"❌ Failed to send report: {send_res.get('error')}", "error")
            return redirect(url_for("index"))

    form_data = get_last_record()
    return render_template("index.html", chat_set=bool(BOT_TOKEN and CHAT_ID), form_data=form_data)

@app.route("/logs")
def view_logs():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT id, user, action, data, timestamp FROM logs ORDER BY id DESC")
    rows = c.fetchall()
    conn.close()

    logs = []
    for row in rows:
        try:
            parsed_data = ast.literal_eval(row[3])
        except:
            parsed_data = {}
        logs.append({
            "id": row[0],
            "user": row[1],
            "action": row[2],
            "timestamp": row[4],
            "data": parsed_data
        })

    return render_template("log.html", logs=logs)

@app.route("/clear_logs")
def clear_logs():
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("DELETE FROM logs")
        conn.commit()
        conn.close()
        flash("🗑️ All logs cleared successfully", "success")
    except Exception as e:
        flash(f"❌ Failed to clear logs: {e}", "error")
    return redirect(url_for("view_logs"))

# --- Run app ---
if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5600)), debug=True)
