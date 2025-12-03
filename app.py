from flask import Flask, request, jsonify, send_from_directory
from web3 import Web3
import json
import os
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, UTC
from dotenv import load_dotenv



app = Flask(__name__)

load_dotenv()


MODE = os.getenv("BPNI", "LOCAL")

def get_env(key):
    return os.getenv(f"{MODE}_{key}")


# =============================
# ===== CONFIG BLOCKCHAIN =====
# =============================
RPC_URL = get_env("RPC_URL")
CONTRACT_ADDRESS = get_env("CONTRACT_ADDRESS")
ABI_FILE = os.getenv("ABI_FILE")
if(MODE == "LOCAL"):
    UTC_KEYSTORE_FILE = get_env("KEYSTORE_FILE")
    PASSWORD = get_env("WALLET_PASSWORD")
elif(MODE == "BPNI"):
    PRIVATE_KEY = get_env("PRIVATE_KEY")
SENDER_ADDRESS = get_env("SENDER_ADDRESS")



# =============================
# ====== CONFIG DATABASE ======
# =============================
DB_CONFIG = {
    "host": os.getenv("DB_HOST"),
    "database": os.getenv("DB_NAME"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "port": os.getenv("DB_PORT")
}

def db_conn():
    return psycopg2.connect(**DB_CONFIG, cursor_factory=RealDictCursor)

# =============================
# ====== CONNECT WEB3 ========
# =============================
w3 = Web3(Web3.HTTPProvider(RPC_URL))
assert w3.is_connected(), "RPC tidak connect"

with open(ABI_FILE) as f:
    abi = json.load(f)

contract = w3.eth.contract(address=CONTRACT_ADDRESS, abi=abi)

# =============================
# ===== DECRYPT WALLET (LOCAL ONLY) ========
# =============================

if(MODE == "LOCAL"):
    with open(UTC_KEYSTORE_FILE) as keyfile:
        encrypted = keyfile.read()

    PRIVATE_KEY = w3.eth.account.decrypt(encrypted, PASSWORD)


# =============================
# ======= HELPERS ============
# =============================
def hash_string(s: str) -> bytes:
    return Web3.keccak(text=s)


# =============================
# ========= ROUTES ===========
# =============================

@app.route("/")
def home():
    return send_from_directory("templates", "index.html")


# ---------------------------------------------------------
# 🔍 VERIFY ABSENSI (ON-CHAIN)
# ---------------------------------------------------------
@app.route("/verify", methods=["GET"])
def verify_attendance():
    student_id = request.args.get("student_id")
    date = request.args.get("date")

    if not student_id or not date:
        return jsonify({"error": "student_id and date required"}), 400

    try:
        date_int = int(date)
        id_hash = hash_string(student_id)

        present, reasonHash, name = contract.functions.verifyAttendance(
            id_hash,
            date_int
        ).call()

        return jsonify({
            "present": present,
            "reasonHash": reasonHash.hex(),
            "name": name
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------
# 📝 LOG ABSENSI (DB + BLOCKCHAIN)
# ---------------------------------------------------------
@app.route("/log", methods=["POST"])
def log_attendance():
    data = request.json

    required = ["student_id", "date", "is_present", "name"]
    for k in required:
        if k not in data:
            return jsonify({"error": f"{k} is required"}), 400

    student_id = data["student_id"].strip()
    name = data["name"].strip()
    is_present = bool(data["is_present"])
    date = int(data["date"])
    reason_txt = data.get("reason", "").strip()

    # ===== VALIDASI ABSENSI ======
    if is_present and reason_txt != "":
        return jsonify({"error": "If present, reason must be empty"}), 400

    if not is_present and reason_txt == "":
        return jsonify({"error": "If absent, reason must be filled"}), 400

    conn = db_conn()
    cur = conn.cursor()

    # ======================================================
    # 1️⃣ VALIDATE / REGISTER STUDENT
    # ======================================================
    cur.execute("SELECT name FROM students WHERE student_id=%s", (student_id,))
    existing = cur.fetchone()

    if not existing:
        # belum ada → register
        cur.execute(
            "INSERT INTO students (student_id, name) VALUES (%s, %s)",
            (student_id, name)
        )
        conn.commit()
    else:
        # ada tapi nama beda → blok
        real_name = existing["name"]
        if real_name.lower() != name.lower():
            cur.close()
            conn.close()
            return jsonify({
                "error": "Student ID already registered under another name",
                "registered_name": real_name,
                "attempted_name": name
            }), 409

    # ======================================================
    # 2️⃣ HASHING
    # ======================================================
    id_hash = hash_string(student_id)
    reason_hash = hash_string(reason_txt) if reason_txt else bytes(32)

    try:
        nonce = w3.eth.get_transaction_count(SENDER_ADDRESS)

        tx = contract.functions.logAttendance(
            id_hash,
            date,
            is_present,
            reason_hash,
            name
        ).build_transaction({
            "from": SENDER_ADDRESS,
            "nonce": nonce,
            "gasPrice": w3.eth.gas_price,
            "gas": 350_000
        })

        signed = w3.eth.account.sign_transaction(tx, PRIVATE_KEY)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)

        # ----------------------------
        # SAVE OFF-CHAIN DB
        # ----------------------------
        # date_normal = datetime.utcfromtimestamp(date).date()
        date_normal = datetime.fromtimestamp(date, UTC).date()
        cur.execute("""
            INSERT INTO attendance_logs
            (student_id, name, date, is_present, reason, tx_hash)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (student_id, name, date_normal, is_present, reason_txt, tx_hash.hex()))

        conn.commit()
        cur.close()
        conn.close()

        return jsonify({
            "tx": tx_hash.hex(),
            "block": receipt.blockNumber,
            "status": "attendance_logged"
        })

    except Exception as e:
        cur.close()
        conn.close()
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------
# 📦 GET HISTORY (ALL)
# ---------------------------------------------------------
@app.route("/history", methods=["GET"])
def history():
    try:
        conn = db_conn()
        cur = conn.cursor()

        cur.execute("SELECT * FROM attendance_logs ORDER BY created_at DESC")
        rows = cur.fetchall()

        cur.close()
        conn.close()
        return jsonify(rows)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------
# 🔍 FILTER BY STUDENT
# ---------------------------------------------------------
@app.route("/history/<student_id>", methods=["GET"])
def get_history_student(student_id):
    try:
        conn = db_conn()
        cur = conn.cursor()

        cur.execute("""
            SELECT * FROM attendance_logs
            WHERE student_id = %s
            ORDER BY created_at DESC
        """, (student_id,))
        rows = cur.fetchall()

        cur.close()
        conn.close()
        return jsonify(rows)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =====================================================
# ================== RUN APP ==========================
# =====================================================
if __name__ == "__main__":
    app.run(debug=True)
