from flask import Flask, request, jsonify
import requests
import os
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, firestore
from google import genai
import json
from datetime import datetime
import base64, json as json_module

load_dotenv()
app = Flask(__name__)

# --- TELEGRAM CONFIG ---
# Replace your WhatsApp variables with these
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELE_API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# --- GENAI & FIREBASE CONFIG (Kept from your original) ---
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
MODEL = "gemini-2.5-flash"

firebase_creds_str = os.getenv("FIREBASE_CREDENTIALS_BASE64")
firebase_creds = json_module.loads(base64.b64decode(firebase_creds_str).decode())
cred = credentials.Certificate(firebase_creds)
firebase_admin.initialize_app(cred)
db = firestore.client()

# ─────────────────────────────────────
# RECEIVE MESSAGES (TELEGRAM WEBHOOK)
# ─────────────────────────────────────
@app.route("/tele-webhook", methods=["POST"])
def receive():
    data = request.get_json()
    
    if "message" in data:
        msg = data["message"]
        chat_id = str(msg["chat"]["id"]) # chat_id replaces phone number as the document ID
        
        # Handle Text Messages
        if "text" in msg:
            handle_text(chat_id, msg["text"])
            
        # Handle Image Messages (Certificates/Bank Docs)
        elif "photo" in msg:
            # Telegram provides a list of photos; the last one is usually the highest resolution
            photo_id = msg["photo"][-1]["file_id"]
            handle_image(chat_id, photo_id)
            
    return jsonify({"status": "ok"}), 200

# ─────────────────────────────────────
# SEND MESSAGE (TELEGRAM API)
# ─────────────────────────────────────
def send_message(chat_id, text):
    """Replaces your old WhatsApp send_message function"""
    url = f"{TELE_API_URL}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown" # Allows you to keep your *Bold* and _Italic_ formatting
    }
    requests.post(url, json=payload)

# ─────────────────────────────────────
# HANDLE IMAGE (TELEGRAM VERSION)
# ─────────────────────────────────────
def handle_image(chat_id, file_id):
    """Downloads the file from Telegram then proceeds with your original logic"""
    # 1. Get the file path from Telegram
    file_info = requests.get(f"{TELE_API_URL}/getFile?file_id={file_id}").json()
    file_path = file_info["result"]["file_path"]
    download_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}"
    
    # 2. Download the image bytes
    image_data = requests.get(download_url).content
    
    # ... Insert your existing Gemini Vision/OCR logic here ...
    # (Same as your original app.py handle_image logic)

# ─────────────────────────────────────
# YOUR EXISTING LOGIC (handle_text, COUNTRY_CONFIG, etc.)
# ─────────────────────────────────────
# All your handle_text() logic remains identical. 
# Just ensure you use chat_id where you previously used phone.