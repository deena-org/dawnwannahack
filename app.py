from flask import Flask, request, jsonify
import requests
import os
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, firestore
from google import genai
from google.genai import types
import json
from datetime import datetime
from io import BytesIO
import base64, json as json_module

load_dotenv()
app = Flask(__name__)

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
MODEL = "gemini-2.5-flash"

firebase_creds_str = os.getenv("FIREBASE_CREDENTIALS_BASE64")
firebase_creds = json_module.loads(base64.b64decode(firebase_creds_str).decode())
cred = credentials.Certificate(firebase_creds)
firebase_admin.initialize_app(cred)
db = firestore.client()

# ─────────────────────────────────────
# WEBHOOK VERIFICATION
# ─────────────────────────────────────
@app.route("/webhook", methods=["GET"])
def verify():
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if token == VERIFY_TOKEN:
        return challenge
    return "Unauthorized", 403

# ─────────────────────────────────────
# RECEIVE MESSAGES
# ─────────────────────────────────────
@app.route("/webhook", methods=["POST"])
def receive():
    data = request.get_json()
    phone = None
    try:
        entry = data["entry"][0]["changes"][0]["value"]
        if "messages" in entry:
            msg = entry["messages"][0]
            phone = msg["from"]
            if msg["type"] == "text":
                handle_text(phone, msg["text"]["body"])
            elif msg["type"] == "image":
                handle_image(phone, msg["image"]["id"])
    except Exception as e:
        import traceback
        print(f"[ERROR] {e}")
        print(traceback.format_exc())
        if phone:
            try:
                send_message(phone, "⚠️ Maaf, berlaku ralat teknikal. Sila cuba lagi.\n\nSorry, a technical error occurred. Please try again.")
            except:
                pass
    return jsonify({"status": "ok"}), 200

# ─────────────────────────────────────
# LANGUAGE HELPER
# ─────────────────────────────────────
def is_english(user_data):
    return user_data.get("language", "bm") == "en"

def t(user_data, bm_text, en_text):
    return en_text if is_english(user_data) else bm_text

# ─────────────────────────────────────
# ASEAN COUNTRY CONFIG
# ─────────────────────────────────────
COUNTRY_CONFIG = {
    "MY": {
        "name": "Malaysia",
        "flag": "🇲🇾",
        "currency": "RM",
        "loan_program": "TEKUN",
        "loan_amount": "RM50,000",
        "loan_rate": "4%",
        "registration": "SSM",
        "reg_url": "ssm.com.my",
        "reg_question_bm": "Adakah perniagaan awak dah *daftar SSM*?",
        "reg_question_en": "Is your business *registered with SSM*?",
        "income_examples": "RM500, RM2000, RM5000",
        "sale_example_bm": "Jual 10 bekas kuih dapat RM150",
        "sale_example_en": "Sold 10 boxes of cookies for RM150",
        "states": {
            "1": "Johor", "2": "Kedah", "3": "Kelantan", "4": "Melaka",
            "5": "Negeri Sembilan", "6": "Pahang", "7": "Perak", "8": "Perlis",
            "9": "Pulau Pinang", "10": "Sabah", "11": "Sarawak", "12": "Selangor",
            "13": "Terengganu", "14": "KL", "15": "Putrajaya", "16": "Labuan",
        },
    },
    "ID": {
        "name": "Indonesia",
        "flag": "🇮🇩",
        "currency": "Rp",
        "loan_program": "KUR (Kredit Usaha Rakyat)",
        "loan_amount": "Rp500 juta",
        "loan_rate": "6%",
        "registration": "NIB",
        "reg_url": "oss.go.id",
        "reg_question_bm": "Adakah perniagaan awak dah *daftar NIB*?",
        "reg_question_en": "Is your business *registered with NIB (OSS)*?",
        "income_examples": "Rp2jt, Rp5jt, Rp10jt",
        "sale_example_bm": "Jual 10 bungkus nasi dapat Rp500rb",
        "sale_example_en": "Sold 10 packs of food for Rp500k",
        "states": {
            "1": "Jakarta", "2": "Jawa Barat", "3": "Jawa Tengah", "4": "Jawa Timur",
            "5": "Bali", "6": "Sumatera Utara", "7": "Sumatera Barat", "8": "Sumatera Selatan",
            "9": "Kalimantan", "10": "Sulawesi", "11": "Papua", "12": "Yogyakarta",
        },
    },
    "PH": {
        "name": "Philippines",
        "flag": "🇵🇭",
        "currency": "₱",
        "loan_program": "SB Corp (Small Business Corp)",
        "loan_amount": "₱500,000",
        "loan_rate": "8%",
        "registration": "DTI",
        "reg_url": "bnrs.dti.gov.ph",
        "reg_question_bm": "Adakah perniagaan awak dah *daftar DTI*?",
        "reg_question_en": "Is your business *registered with DTI*?",
        "income_examples": "₱10k, ₱30k, ₱50k",
        "sale_example_bm": "Jual 10 item dapat ₱5000",
        "sale_example_en": "Sold 10 items for ₱5000",
        "states": {
            "1": "Metro Manila", "2": "Cebu", "3": "Davao", "4": "Calabarzon",
            "5": "Central Luzon", "6": "Western Visayas", "7": "Central Visayas",
            "8": "Northern Mindanao", "9": "Ilocos", "10": "Bicol",
        },
    },
}

def get_country(user_data):
    """Get country config for user, defaults to Malaysia"""
    code = user_data.get("country", "MY")
    return COUNTRY_CONFIG.get(code, COUNTRY_CONFIG["MY"])

def get_currency(user_data):
    return get_country(user_data)["currency"]

# ─────────────────────────────────────
# HANDLE TEXT
# ─────────────────────────────────────
def handle_text(phone, text):
    user_ref = db.collection("users").document(phone)
    user = user_ref.get()
    text_upper = text.upper().strip()

    # Language toggle — works anytime
    if text_upper == "ENGLISH":
        if user.exists:
            user_ref.update({"language": "en"})
            # If still in consent state, re-show welcome in English
            user_data_check = user_ref.get().to_dict()
            if user_data_check.get("state") == "ask_consent":
                send_message(phone,
                    "👋 *Welcome to BizBuddy!*\n\n"
                    "I'll help you build your business profile & credit score in 5 minutes.\n\n"
                    "🔒 *Your Privacy & Data:*\n"
                    "• BizBuddy stores your business data (name, sales, product) to build your credit profile.\n"
                    "• Your data *will not be shared* with any party without your consent.\n"
                    "• You can delete all your data anytime by typing *RESET*.\n\n"
                    "Type *AGREE* to continue"
                )
                return
        send_message(phone,
            "🌐 *Language switched to English!*\n\n"
            "All responses will now be in English.\n"
            "Type *BM* to switch back to Bahasa Malaysia."
        )
        return

    if text_upper == "BM":
        if user.exists:
            user_ref.update({"language": "bm"})
            # If still in consent state, re-show welcome in BM
            user_data_check = user_ref.get().to_dict()
            if user_data_check.get("state") == "ask_consent":
                send_message(phone,
                    "👋 *Selamat datang ke BizBuddy!*\n\n"
                    "Saya akan bantu awak bina profil perniagaan & skor kredit dalam masa 5 minit.\n\n"
                    "🔒 *Privasi & Data Awak:*\n"
                    "• BizBuddy menyimpan data perniagaan awak (nama, jualan, produk) untuk membina profil kredit.\n"
                    "• Data awak *tidak akan dikongsi* dengan mana-mana pihak tanpa kebenaran awak.\n"
                    "• Awak boleh padam semua data bila-bila masa dengan taip *RESET*.\n\n"
                    "Taip *SETUJU* untuk teruskan"
                )
                return
        send_message(phone,
            "🌐 *Bahasa ditukar ke Bahasa Malaysia!*\n\n"
            "Semua respons akan dalam Bahasa Malaysia.\n"
            "Taip *ENGLISH* untuk tukar ke Bahasa Inggeris."
        )
        return

    if not user.exists:
        user_ref.set({"state": "ask_consent", "sales": [], "language": "bm"})
        send_message(phone,
            "👋 *Selamat datang ke BizBuddy!*\n\n"
            "Saya akan bantu awak bina profil perniagaan & skor kredit dalam masa 5 minit.\n\n"
            "🔒 *Privasi & Data Awak:*\n"
            "• BizBuddy menyimpan data perniagaan awak (nama, jualan, produk) untuk membina profil kredit.\n"
            "• Data awak *tidak akan dikongsi* dengan mana-mana pihak tanpa kebenaran awak.\n"
            "• Awak boleh padam semua data bila-bila masa dengan taip *RESET*.\n\n"
            "💡 _Tip: Taip ENGLISH untuk tukar bahasa_\n\n"
            "Taip *SETUJU* untuk teruskan\n"
            "Taip *ENGLISH* dahulu jika mahu tukar bahasa"
        )
        return

    user_data = user.to_dict()
    state = user_data.get("state", "menu")
    lang = user_data.get("language", "bm")

    # RESET — works anytime
    if text_upper == "RESET":
        user_ref.delete()
        send_message(phone,
            "🔄 *Profil awak telah dipadam.*\n\nTaip *HAI* untuk mulakan semula."
            if lang == "bm" else
            "🔄 *Your profile has been deleted.*\n\nType *HI* to start again."
        )
        return

    # BATAL/CANCEL — exits any pending state (e.g. await_ssm_cert)
    if text_upper in ["BATAL", "CANCEL"]:
        current_state = user_data.get("state", "menu")
        if current_state == "await_ssm_cert":
            user_ref.update({"state": "menu"})
            send_message(phone,
                "❌ Pengesahan SSM dibatalkan.\n\nTaip *MENU* untuk kembali."
                if lang == "bm" else
                "❌ SSM verification cancelled.\n\nType *MENU* to go back."
            )
        else:
            send_message(phone,
                "Tiada tindakan untuk dibatalkan.\n\nTaip *MENU* untuk kembali."
                if lang == "bm" else
                "Nothing to cancel.\n\nType *MENU* to go back."
            )
        return

    # PROFIL command — works anytime
    if text_upper == "PROFIL" or text_upper == "PROFILE":
        show_profile(phone, user_ref)
        return

    # SIJIL command — works anytime
    if text_upper == "SIJIL" or text_upper == "CERTIFICATE":
        show_certificate(phone, user_ref)
        return
    
    # PINJAMAN command — works anytime
    if text_upper == "PINJAMAN" or text_upper == "LOAN":
        show_loan_checklist(phone, user_ref)
        return

    # DATA command — privacy: show stored data
    if text_upper == "DATA":
        show_stored_data(phone, user_ref)
        return

    # BREAKDOWN command — show score breakdown anytime
    if text_upper in ["BREAKDOWN", "PECAHAN"]:
        show_score_breakdown(phone, user_ref)
        return

    # RUJUK/REFER command — loan referral
    if text_upper in ["RUJUK", "REFER"]:
        show_loan_referral(phone, user_ref)
        return

    # VERIFY command — SSM/NIB/DTI certificate verification
    if text_upper in ["VERIFY", "SAHKAN", "SSM", "NIB", "DTI"]:
        prompt_ssm_verification(phone, user_ref)
        return

    # LANGKAU/SKIP — skip any pending verification
    if text_upper in ["LANGKAU", "SKIP"]:
        current_state = user_data.get("state", "menu")
        user_data_now = user_ref.get().to_dict()
        cc = get_country(user_data_now)
        if current_state in ("await_ssm_cert", "await_ssm_cert_then_score"):
            # Self-declared SSM = 7 pts
            user_ref.update({"state": "menu"})
            if lang == "bm":
                send_message(phone, "⏭️ Pengesahan SSM dilangkau (7 mata, bukan 10).\n\nTaip *SKOR* untuk lihat skor kredit\nTaip *MENU* untuk kembali")
            else:
                send_message(phone, "⏭️ SSM verification skipped (7 pts instead of 10).\n\nType *SCORE* to view credit score\nType *MENU* to go back")
        elif current_state == "await_bank_doc_then_reg":
            # Self-declared bank = 7 pts, then move to SSM question
            user_ref.update({"state": "credit_q3"})
            if lang == "bm":
                send_message(phone, f"⏭️ Pengesahan bank dilangkau (7 mata, bukan 10).\n\nSoalan 3️⃣: {cc['reg_question_bm']}\n_(Balas: Ya / Tidak)_")
            else:
                send_message(phone, f"⏭️ Bank verification skipped (7 pts instead of 10).\n\nQuestion 3️⃣: {cc['reg_question_en']}\n_(Reply: Yes / No)_")
        elif current_state in ("await_bank_doc_then_score", "await_bank_doc"):
            user_ref.update({"state": "menu"})
            if lang == "bm":
                send_message(phone, "⏭️ Pengesahan bank dilangkau (7 mata, bukan 10).\n\nTaip *MENU* untuk kembali")
            else:
                send_message(phone, "⏭️ Bank verification skipped (7 pts instead of 10).\n\nType *MENU* to go back")
        elif current_state in ("content_generate", "content_menu", "log_sale", "ai_chat"):
            pass  # Let these states handle SKIP themselves — do NOT return
        else:
            if lang == "bm":
                send_message(phone, "Tiada tindakan untuk dilangkau.\n\nTaip *MENU* untuk kembali.")
            else:
                send_message(phone, "Nothing to skip.\n\nType *MENU* to go back.")
            return
        # Only return early if we handled SKIP above; passthrough states continue below

    # KEMASKINI/UPDATE command — re-answer credit questions
    if text_upper in ["KEMASKINI", "UPDATE"]:
        user_ref.update({"state": "credit_q1"})
        cc_temp = get_country(user_data)
        if lang == "bm":
            send_message(phone,
                "🔄 *Kemaskini Maklumat Kredit*\n\n"
                "Soalan 1️⃣: Berapa lama perniagaan awak dah beroperasi?\n"
                "_(Contoh: 3 bulan, 1 tahun, 5 tahun)_"
            )
        else:
            send_message(phone,
                "🔄 *Update Credit Info*\n\n"
                "Question 1️⃣: How long has your business been operating?\n"
                "_(Example: 3 months, 1 year, 5 years)_"
            )
        return

    # Onboarding states
    if state == "ask_consent":
        if text_upper in ["SETUJU", "AGREE", "YES", "YA", "OK"]:
            user_ref.update({
                "state": "ask_country",
                "consent": True,
                "consent_date": str(datetime.now())
            })
            if lang == "bm":
                send_message(phone,
                    "✅ *Terima kasih!* Data awak dilindungi.\n\n"
                    "🌏 *Negara mana awak beroperasi?*\n\n"
                    "1️⃣ 🇲🇾 Malaysia\n"
                    "2️⃣ 🇮🇩 Indonesia\n"
                    "3️⃣ 🇵🇭 Philippines\n\n"
                    "_Balas dengan nombor pilihan_"
                )
            else:
                send_message(phone,
                    "✅ *Thank you!* Your data is protected.\n\n"
                    "🌏 *Which country do you operate in?*\n\n"
                    "1️⃣ 🇲🇾 Malaysia\n"
                    "2️⃣ 🇮🇩 Indonesia\n"
                    "3️⃣ 🇵🇭 Philippines\n\n"
                    "_Reply with your choice number_"
                )
        else:
            if lang == "bm":
                send_message(phone,
                    "⚠️ Awak perlu bersetuju untuk menggunakan BizBuddy.\n\n"
                    "Taip *SETUJU* untuk teruskan\n"
                    "Taip *ENGLISH* untuk tukar bahasa dahulu"
                )
            else:
                send_message(phone,
                    "⚠️ You need to agree to use BizBuddy.\n\n"
                    "Type *AGREE* to continue\n"
                    "Type *BM* to switch to Bahasa Malaysia first"
                )

    elif state == "ask_country":
        country_map = {"1": "MY", "2": "ID", "3": "PH"}
        if text_upper in country_map:
            code = country_map[text_upper]
            cc = COUNTRY_CONFIG[code]
            user_ref.update({"country": code, "state": "ask_state"})
            # Build state list
            states = cc.get("states", {})
            state_list = "\n".join([f"{k}️⃣ {v}" for k, v in sorted(states.items(), key=lambda x: int(x[0]))])
            max_num = len(states)
            if lang == "bm":
                send_message(phone,
                    f"{cc['flag']} *{cc['name']} dipilih!*\n\n"
                    f"📍 *Di negeri/wilayah mana awak beroperasi?*\n\n"
                    f"{state_list}\n\n"
                    f"_Balas dengan nombor (1-{max_num})_"
                )
            else:
                send_message(phone,
                    f"{cc['flag']} *{cc['name']} selected!*\n\n"
                    f"📍 *Which state/region do you operate in?*\n\n"
                    f"{state_list}\n\n"
                    f"_Reply with a number (1-{max_num})_"
                )
        else:
            if lang == "bm":
                send_message(phone, "Sila pilih 1-3:\n1️⃣ 🇲🇾 Malaysia\n2️⃣ 🇮🇩 Indonesia\n3️⃣ 🇵🇭 Philippines")
            else:
                send_message(phone, "Please choose 1-3:\n1️⃣ 🇲🇾 Malaysia\n2️⃣ 🇮🇩 Indonesia\n3️⃣ 🇵🇭 Philippines")

    elif state == "ask_state":
        user_data_now = user_ref.get().to_dict()
        cc = get_country(user_data_now)
        states = cc.get("states", {})
        if text_upper in states:
            state_name = states[text_upper]
            user_ref.update({"user_state": state_name, "state": "ask_owner_name"})
            if lang == "bm":
                send_message(phone,
                    f"📍 *{state_name}* — noted!\n\n"
                    f"Mata wang: {cc['currency']}\n"
                    f"Program pinjaman: {cc['loan_program']}\n"
                    f"Pendaftaran: {cc['registration']}\n\n"
                    "Jom mulakan! 🚀\n\n"
                    "Soalan 1️⃣: Apa *nama awak*?"
                )
            else:
                send_message(phone,
                    f"📍 *{state_name}* — noted!\n\n"
                    f"Currency: {cc['currency']}\n"
                    f"Loan program: {cc['loan_program']}\n"
                    f"Registration: {cc['registration']}\n\n"
                    "Let's get started! 🚀\n\n"
                    "Question 1️⃣: What is your *name*?"
                )
        else:
            max_num = len(states)
            if lang == "bm":
                send_message(phone, f"Sila pilih nombor 1-{max_num} sahaja.")
            else:
                send_message(phone, f"Please choose a number from 1-{max_num}.")

    elif state == "ask_owner_name":
        user_ref.update({"owner_name": text, "state": "ask_business_name"})
        if lang == "bm":
            send_message(phone, f"Hai *{text}*! 😊\n\nSoalan 2️⃣: Apa *nama perniagaan* awak?\n_(Contoh: Kuih Farah, Tudung Siti, Kedai Ahmad)_")
        else:
            send_message(phone, f"Hi *{text}*! 😊\n\nQuestion 2️⃣: What is your *business name*?\n_(Example: Farah Kuih, Siti Hijab, Ahmad Store)_")

    elif state == "ask_business_name":
        user_ref.update({"business_name": text, "state": "ask_product"})
        if lang == "bm":
            send_message(phone, f"*{text}* — nama yang menarik! 🌟\n\nSoalan 3️⃣: Apa yang awak *jual atau tawarkan*?\n_(Contoh: kuih tradisional, tudung, servis gunting rambut)_")
        else:
            send_message(phone, f"*{text}* — great name! 🌟\n\nQuestion 3️⃣: What do you *sell or offer*?\n_(Example: traditional kuih, hijab, haircut service)_")

    elif state == "ask_product":
        # Extract product keywords from natural language
        extract_prompt = f"""
Extract ONLY the product or service keywords from this text: "{text}"
Return a short comma-separated list of products/services, maximum 5 words total.
Do NOT include filler words like "kedai saya", "I sell", "my shop is", "yang menjual" etc.
Examples:
- "kedai saya ialah bakeri yang menjual roti, pastri dan cookies" → "roti, pastri, cookies"
- "I sell traditional kuih and catering services" → "kuih tradisional, katering"
- "tudung dan pakaian muslimah" → "tudung, pakaian muslimah"
- "servis gunting rambut" → "servis gunting rambut"
Return ONLY the extracted keywords, nothing else.
"""
        try:
            extract_response = client.models.generate_content(model=MODEL, contents=extract_prompt)
            product_clean = extract_response.text.strip().strip('"').strip("'")
            # Fallback if AI returns something too long or empty
            if len(product_clean) > 60 or len(product_clean) < 2:
                product_clean = text
        except:
            product_clean = text

        user_ref.update({"product": product_clean, "state": "ask_revenue"})
        user_data_now = user_ref.get().to_dict()
        cc = get_country(user_data_now)
        if lang == "bm":
            send_message(phone, f"*{product_clean}* — menarik! 🛍️\n\nSoalan 4️⃣: Dalam sebulan, lebih kurang berapa *pendapatan* awak?\n_(Contoh: {cc['income_examples']})_")
        else:
            send_message(phone, f"*{product_clean}* — interesting! 🛍️\n\nQuestion 4️⃣: Roughly how much is your *monthly income*?\n_(Example: {cc['income_examples']})_")

    elif state == "ask_revenue":
        user_data = user_ref.get().to_dict()
        owner_name = user_data.get("owner_name", "")
        business_name = user_data.get("business_name", "")
        product = user_data.get("product", "")
        user_ref.update({"monthly_revenue": text, "state": "menu", "registered_date": str(datetime.now().date())})
        if lang == "bm":
            send_message(phone,
                f"🎉 *Profil perniagaan awak dah siap, {owner_name}!*\n\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "📋 *PROFIL PERNIAGAAN AWAK*\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 Nama: {owner_name}\n"
                f"🏪 Perniagaan: {business_name}\n"
                f"📦 Produk: {product}\n"
                f"💵 Pendapatan: {text}/bulan\n"
                f"📅 Tarikh Daftar: {str(datetime.now().date())}\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                "Taip *MENU* untuk mula rekod jualan awak! 🚀"
            )
        else:
            send_message(phone,
                f"🎉 *Your business profile is ready, {owner_name}!*\n\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "📋 *YOUR BUSINESS PROFILE*\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 Name: {owner_name}\n"
                f"🏪 Business: {business_name}\n"
                f"📦 Product: {product}\n"
                f"💵 Income: {text}/month\n"
                f"📅 Registered: {str(datetime.now().date())}\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                "Type *MENU* to start recording your sales! 🚀"
            )

    elif state == "menu":
        if text_upper in ["HAI", "HI", "HELLO", "START"]:
            user_data = user_ref.get().to_dict()
            owner_name = user_data.get("owner_name", "Peniaga")
            cur = get_currency(user_data)
            sales = user_data.get("sales", [])
            total = sum(s.get("amount", 0) for s in sales)
            score = user_data.get("credit_score", 0)
            if lang == "bm":
                send_message(phone,
                    f"👋 *Selamat kembali, {owner_name}!*\n\n"
                    f"📊 Jualan terkumpul: {cur}{total}\n"
                    f"⭐ Skor kredit: {score if score else 'Belum dijana'}\n\n"
                    "Awak boleh terus taip apa sahaja!\n"
                    "Contoh:\n"
                    "• _jual 10 tudung dapat rm150_\n"
                    "• _beli bahan rm80_\n"
                    "• _macam mana nak promosi?_\n\n"
                    "Atau taip *MENU* untuk lihat semua pilihan."
                )
            else:
                send_message(phone,
                    f"👋 *Welcome back, {owner_name}!*\n\n"
                    f"📊 Total sales: {cur}{total}\n"
                    f"⭐ Credit score: {score if score else 'Not yet generated'}\n\n"
                    "You can just type anything naturally!\n"
                    "Examples:\n"
                    "• _sold 10 hijabs for rm150_\n"
                    "• _bought supplies rm80_\n"
                    "• _how to promote my business?_\n\n"
                    "Or type *MENU* to see all options."
                )
        else:
            # Route menu numbers directly, smart_handle for natural language
            if text_upper in ["1","2","3","4","5","6","7","8","9","MENU","PROFIL","PROFILE","SIJIL","CERTIFICATE","PINJAMAN","LOAN","RESET","DATA","BREAKDOWN","PECAHAN","RUJUK","REFER","KEMASKINI","UPDATE"]:
                handle_menu(phone, text, user_ref)
            else:
                smart_handle(phone, text, user_ref)

    elif state == "log_sale":
        handle_log_sale(phone, text, user_ref)

    elif state == "ai_chat":
        handle_ai_chat(phone, text, user_ref)

    elif state == "credit_confirm":
        if text_upper in ["YA", "YES", "Y", "SAMA", "BETUL", "CORRECT"]:
            user_ref.update({"state": "menu"})
            if lang == "bm":
                send_message(phone, "⏳ Sedang mengira skor kredit awak...")
            else:
                send_message(phone, "⏳ Calculating your credit score...")
            generate_credit_score(phone, user_ref)
        elif text_upper in ["TIDAK", "NO", "N", "TAK", "CHANGE"]:
            # Ask only the 2 questions that might change (bank + registration)
            user_ref.update({"state": "credit_update_bank"})
            if lang == "bm":
                send_message(phone, "🔄 *Kemaskini Maklumat*\n\nSoalan 1️⃣: Adakah awak ada *akaun bank perniagaan*?\n_(Balas: Ya / Tidak)_")
            else:
                send_message(phone, "🔄 *Update Info*\n\nQuestion 1️⃣: Do you have a *business bank account*?\n_(Reply: Yes / No)_")
        elif text_upper == "MENU":
            user_ref.update({"state": "menu"})
            handle_menu(phone, "MENU", user_ref)
        else:
            if lang == "bm":
                send_message(phone, "Sila balas *YA* atau *TIDAK*\n\nYA → Jana skor terus\nTIDAK → Kemaskini maklumat\nMENU → Kembali")
            else:
                send_message(phone, "Please reply *YES* or *NO*\n\nYES → Generate score now\nNO → Update info\nMENU → Go back")

    elif state == "credit_update_bank":
        user_data_now = user_ref.get().to_dict()
        cc = get_country(user_data_now)
        YES_ANSWERS = {"ya", "yes", "y", "sudah", "ada", "dah", "yep", "yup", "ye"}
        NO_ANSWERS = {"tidak", "no", "n", "belum", "tak", "tiada", "nope"}
        if text_upper.lower() in YES_ANSWERS:
            user_ref.update({"has_bank_account": "yes", "state": "await_bank_doc_then_reg"})
            if lang == "bm":
                send_message(phone,
                    "🏦 *Sahkan Akaun Bank Awak*\n\n"
                    "Hantar screenshot atau gambar:\n"
                    "• Penyata bank\n• Buku bank (passbook)\n• Online banking\n• E-wallet (TNG, GoPay, dll)\n\n"
                    "✅ Pastikan *nama pemegang akaun* kelihatan.\n\n"
                    "📸 *Hantar gambar sekarang*\n\n"
                    "Taip *LANGKAU* untuk langkau (7 mata, bukan 10)"
                )
            else:
                send_message(phone,
                    "🏦 *Verify Your Bank Account*\n\n"
                    "Send a screenshot or photo of:\n"
                    "• Bank statement\n• Passbook\n• Online banking\n• E-wallet (TNG, GoPay, etc)\n\n"
                    "✅ Make sure *account holder name* is visible.\n\n"
                    "📸 *Send the image now*\n\n"
                    "Type *SKIP* to skip (7 pts instead of 10)"
                )
            return
        elif text_upper.lower() in NO_ANSWERS:
            user_ref.update({"has_bank_account": "no", "state": "credit_update_reg"})
        else:
            if lang == "bm":
                send_message(phone, "⚠️ Sila balas *Ya* atau *Tidak* sahaja.\n\nSoalan 1️⃣: Adakah awak ada *akaun bank perniagaan*?\n_(Balas: Ya / Tidak)_")
            else:
                send_message(phone, "⚠️ Please reply *Yes* or *No* only.\n\nQuestion 1️⃣: Do you have a *business bank account*?\n_(Reply: Yes / No)_")
            return
        if lang == "bm":
            send_message(phone, f"✅ Dikemaskini!\n\nSoalan 2️⃣: {cc['reg_question_bm']}\n_(Balas: Ya / Tidak)_")
        else:
            send_message(phone, f"✅ Updated!\n\nQuestion 2️⃣: {cc['reg_question_en']}\n_(Reply: Yes / No)_")

    elif state == "credit_update_reg":
        user_data_now = user_ref.get().to_dict()
        cc = get_country(user_data_now)
        YES_ANSWERS = {"ya", "yes", "y", "sudah", "ada", "dah", "yep", "yup", "ye"}
        NO_ANSWERS = {"tidak", "no", "n", "belum", "tak", "tiada", "nope"}
        if text_upper.lower() in YES_ANSWERS:
            # User claims they have SSM — ask them to verify with cert image
            user_ref.update({"has_ssm": "yes", "state": "await_ssm_cert_then_score"})
            if lang == "bm":
                send_message(phone,
                    f"✅ Bagus! Awak ada {cc['registration']}.\n\n"
                    f"📄 *Hantar gambar sijil {cc['registration']} awak untuk pengesahan.*\n\n"
                    "Ini membantu meningkatkan skor kredit awak!\n\n"
                    "✅ Pastikan gambar jelas dan nombor pendaftaran kelihatan.\n\n"
                    f"📸 *Hantar gambar sijil {cc['registration']} sekarang*\n\n"
                    "Taip *LANGKAU* jika tidak mahu sahkan sekarang"
                )
            else:
                send_message(phone,
                    f"✅ Great! You have {cc['registration']}.\n\n"
                    f"📄 *Please send a photo of your {cc['registration']} certificate to verify.*\n\n"
                    "This helps boost your credit score!\n\n"
                    "✅ Make sure the image is clear and registration number is visible.\n\n"
                    f"📸 *Send your {cc['registration']} certificate image now*\n\n"
                    "Type *SKIP* if you don't want to verify now"
                )
        elif text_upper.lower() in NO_ANSWERS:
            user_ref.update({"has_ssm": "no", "state": "menu"})
            if lang == "bm":
                send_message(phone, "⏳ Sedang mengira skor kredit awak...")
            else:
                send_message(phone, "⏳ Calculating your credit score...")
            generate_credit_score(phone, user_ref)
        else:
            if lang == "bm":
                send_message(phone, f"⚠️ Sila balas *Ya* atau *Tidak* sahaja.\n\n{cc['reg_question_bm']}\n_(Balas: Ya / Tidak)_")
            else:
                send_message(phone, f"⚠️ Please reply *Yes* or *No* only.\n\n{cc['reg_question_en']}\n_(Reply: Yes / No)_")

    elif state == "credit_q1":
        user_ref.update({"biz_age": text, "state": "credit_q2"})
        if lang == "bm":
            send_message(phone, f"✅ Noted!\n\nSoalan 2️⃣: Adakah awak ada *akaun bank perniagaan*?\n_(Balas: Ya / Tidak)_")
        else:
            send_message(phone, f"✅ Noted!\n\nQuestion 2️⃣: Do you have a *business bank account*?\n_(Reply: Yes / No)_")

    elif state == "credit_q2":
        user_data_now = user_ref.get().to_dict()
        cc = get_country(user_data_now)
        YES_ANSWERS = {"ya", "yes", "y", "sudah", "ada", "dah", "yep", "yup", "ye"}
        NO_ANSWERS = {"tidak", "no", "n", "belum", "tak", "tiada", "nope"}
        if text_upper.lower() in YES_ANSWERS:
            user_ref.update({"has_bank_account": "yes", "state": "await_bank_doc_then_reg"})
            if lang == "bm":
                send_message(phone,
                    "🏦 *Sahkan Akaun Bank Awak*\n\n"
                    "Hantar screenshot atau gambar:\n"
                    "• Penyata bank\n• Buku bank (passbook)\n• Online banking\n• E-wallet (TNG, GoPay, dll)\n\n"
                    "✅ Pastikan *nama pemegang akaun* kelihatan.\n\n"
                    "📸 *Hantar gambar sekarang*\n\n"
                    "Taip *LANGKAU* untuk langkau (7 mata, bukan 10)"
                )
            else:
                send_message(phone,
                    "🏦 *Verify Your Bank Account*\n\n"
                    "Send a screenshot or photo of:\n"
                    "• Bank statement\n• Passbook\n• Online banking\n• E-wallet (TNG, GoPay, etc)\n\n"
                    "✅ Make sure *account holder name* is visible.\n\n"
                    "📸 *Send the image now*\n\n"
                    "Type *SKIP* to skip (7 pts instead of 10)"
                )
            return
        elif text_upper.lower() in NO_ANSWERS:
            user_ref.update({"has_bank_account": "no", "state": "credit_q3"})
        else:
            if lang == "bm":
                send_message(phone, "⚠️ Sila balas *Ya* atau *Tidak* sahaja.\n\nSoalan 2️⃣: Adakah awak ada *akaun bank perniagaan*?\n_(Balas: Ya / Tidak)_")
            else:
                send_message(phone, "⚠️ Please reply *Yes* or *No* only.\n\nQuestion 2️⃣: Do you have a *business bank account*?\n_(Reply: Yes / No)_")
            return
        if lang == "bm":
            send_message(phone, f"✅ Noted!\n\nSoalan 3️⃣: {cc['reg_question_bm']}\n_(Balas: Ya / Tidak)_")
        else:
            send_message(phone, f"✅ Noted!\n\nQuestion 3️⃣: {cc['reg_question_en']}\n_(Reply: Yes / No)_")

    elif state == "content_menu":
        handle_content_menu(phone, text, user_ref)

    elif state == "content_generate":
        handle_content_generate(phone, text, user_ref)

    elif state == "credit_q3":
        user_data_now = user_ref.get().to_dict()
        cc = get_country(user_data_now)
        YES_ANSWERS = {"ya", "yes", "y", "sudah", "ada", "dah", "yep", "yup", "ye"}
        NO_ANSWERS = {"tidak", "no", "n", "belum", "tak", "tiada", "nope"}
        if text_upper.lower() in YES_ANSWERS:
            # User claims they have SSM — ask them to verify with cert image
            user_ref.update({"has_ssm": "yes", "state": "await_ssm_cert_then_score"})
            if lang == "bm":
                send_message(phone,
                    f"✅ Bagus! Awak ada {cc['registration']}.\n\n"
                    f"📄 *Hantar gambar sijil {cc['registration']} awak untuk pengesahan.*\n\n"
                    "Ini membantu meningkatkan skor kredit awak!\n\n"
                    "✅ Pastikan gambar jelas dan nombor pendaftaran kelihatan.\n\n"
                    f"📸 *Hantar gambar sijil {cc['registration']} sekarang*\n\n"
                    "Taip *LANGKAU* jika tidak mahu sahkan sekarang"
                )
            else:
                send_message(phone,
                    f"✅ Great! You have {cc['registration']}.\n\n"
                    f"📄 *Please send a photo of your {cc['registration']} certificate to verify.*\n\n"
                    "This helps boost your credit score!\n\n"
                    "✅ Make sure the image is clear and registration number is visible.\n\n"
                    f"📸 *Send your {cc['registration']} certificate image now*\n\n"
                    "Type *SKIP* if you don't want to verify now"
                )
        elif text_upper.lower() in NO_ANSWERS:
            user_ref.update({"has_ssm": "no", "state": "menu"})
            if lang == "bm":
                send_message(phone, "⏳ Sedang mengira skor kredit awak...")
            else:
                send_message(phone, "⏳ Calculating your credit score...")
            generate_credit_score(phone, user_ref)
        else:
            if lang == "bm":
                send_message(phone, f"⚠️ Sila balas *Ya* atau *Tidak* sahaja.\n\n{cc['reg_question_bm']}\n_(Balas: Ya / Tidak)_")
            else:
                send_message(phone, f"⚠️ Please reply *Yes* or *No* only.\n\n{cc['reg_question_en']}\n_(Reply: Yes / No)_")

# ─────────────────────────────────────
# SMART INTENT DETECTION
# ─────────────────────────────────────
def smart_handle(phone, text, user_ref):
    user_data = user_ref.get().to_dict()
    lang = user_data.get("language", "bm")
    cur = get_currency(user_data)
    text_upper = text.upper().strip()

    # Hard commands — no AI needed
    if text_upper == "MENU":
        handle_menu(phone, "MENU", user_ref)
        return
    if text_upper in ["1","2","3","4","5","6","7","8","9"]:
        handle_menu(phone, text, user_ref)
        return
    if text_upper in ["PROFIL","PROFILE"]:
        show_profile(phone, user_ref)
        return
    if text_upper in ["SIJIL","CERTIFICATE"]:
        show_certificate(phone, user_ref)
        return
    if text_upper in ["PINJAMAN","LOAN"]:
        show_loan_checklist(phone, user_ref)
        return
    if text_upper == "DATA":
        show_stored_data(phone, user_ref)
        return
    if text_upper in ["BREAKDOWN", "PECAHAN"]:
        show_score_breakdown(phone, user_ref)
        return
    if text_upper in ["RUJUK", "REFER"]:
        show_loan_referral(phone, user_ref)
        return
    if text_upper in ["KEMASKINI", "UPDATE"]:
        user_ref.update({"state": "credit_q1"})
        cc_temp = get_country(user_data)
        if lang == "bm":
            send_message(phone, "🔄 *Kemaskini Maklumat Kredit*\n\nSoalan 1️⃣: Berapa lama perniagaan awak dah beroperasi?\n_(Contoh: 3 bulan, 1 tahun, 5 tahun)_")
        else:
            send_message(phone, "🔄 *Update Credit Info*\n\nQuestion 1️⃣: How long has your business been operating?\n_(Example: 3 months, 1 year, 5 years)_")
        return
    if text_upper == "RESET":
        user_ref.delete()
        send_message(phone, "🔄 Profil dipadam. Taip HAI untuk mula semula." if lang=="bm" else "🔄 Profile deleted. Type HI to start again.")
        return

    # AI intent detection — include user's business context for better classification
    business_product = user_data.get("product", "")
    prompt = f"""
You are an intent classifier for a WhatsApp business bot.
The user's business sells/offers: {business_product}

Classify this message into ONE of these intents:

INTENTS:
- log_sale: user is recording INCOME/REVENUE. Keywords: jual, dapat, sold, received money, orang, customer, client, pelanggan. IMPORTANT: If the user mentions their own product/service (like "{business_product}") and mentions receiving money or serving customers, this is a SALE not an expense. For service businesses (potong rambut, servis, repair, etc), serving customers = making a sale.
- log_expense: user is recording a COST/SPENDING. Keywords: beli bahan, bought supplies, spent on, bayar bil, purchase materials, restock. This is money GOING OUT to suppliers/bills, NOT money coming in from customers.
- check_score: user asking about credit score (skor, score, markah)
- check_summary: user asking about sales summary (ringkasan, summary, jualan, berapa duit)
- ask_ai: user asking a business question (how to, macam mana, tips, advice, cara)
- show_menu: user wants to see menu options
- unknown: cannot classify

KEY RULE: If the message mentions "dapat" (received) with an amount, it is ALWAYS a sale.
KEY RULE: If the message mentions serving customers or doing their service work, it is a SALE.
KEY RULE: Only classify as expense if the user is BUYING supplies or PAYING bills.

Message: "{text}"

Reply with ONLY the intent word, nothing else.
Example: log_sale
"""
    response = client.models.generate_content(model=MODEL, contents=prompt)
    intent = response.text.strip().lower().replace("'","").replace('"','')

    if intent == "log_sale":
        # Extract and log sale directly
        extract_prompt = f"""
Extract sale information from: "{text}"
Return ONLY valid JSON:
{{"amount": number, "item": "string"}}
If cannot extract amount use 0.
"""
        sale_response = client.models.generate_content(model=MODEL, contents=extract_prompt)
        try:
            clean = sale_response.text.strip().replace("```json","").replace("```","")
            sale = json.loads(clean)
        except:
            sale = {"amount": 0, "item": text}

        user_ref.update({
            "sales": firestore.ArrayUnion([{
                "amount": sale["amount"],
                "item": sale["item"],
                "date": str(datetime.now().date())
            }])
        })
        if lang == "bm":
            send_message(phone, f"✅ *Jualan direkod terus!*\n\n💵 Jumlah: {cur}{sale['amount']}\n📦 Item: {sale['item']}\n\nTaip *MENU* untuk pilihan lain.")
        else:
            send_message(phone, f"✅ *Sale recorded directly!*\n\n💵 Amount: {cur}{sale['amount']}\n📦 Item: {sale['item']}\n\nType *MENU* for other options.")

    elif intent == "log_expense":
        extract_prompt = f"""
Extract expense information from: "{text}"
Return ONLY valid JSON:
{{"amount": number, "item": "string"}}
If cannot extract amount use 0.
"""
        exp_response = client.models.generate_content(model=MODEL, contents=extract_prompt)
        try:
            clean = exp_response.text.strip().replace("```json","").replace("```","")
            expense = json.loads(clean)
        except:
            expense = {"amount": 0, "item": text}

        user_ref.update({
            "expenses": firestore.ArrayUnion([{
                "amount": expense["amount"],
                "item": expense["item"],
                "date": str(datetime.now().date())
            }])
        })
        if lang == "bm":
            send_message(phone, f"✅ *Perbelanjaan direkod!*\n\n💸 Jumlah: {cur}{expense['amount']}\n📦 Item: {expense['item']}\n\nTaip *MENU* untuk pilihan lain.")
        else:
            send_message(phone, f"✅ *Expense recorded!*\n\n💸 Amount: {cur}{expense['amount']}\n📦 Item: {expense['item']}\n\nType *MENU* for other options.")

    elif intent == "check_score":
        show_certificate(phone, user_ref)

    elif intent == "check_summary":
        show_sales_summary(phone, user_ref)

    elif intent == "ask_ai":
        lang_instruction = "Bahasa Malaysia mudah" if lang == "bm" else "simple English"
        ai_prompt = f"""
You are an AI business advisor for small Malaysian entrepreneurs.
Answer in {lang_instruction}. Maximum 4 sentences.

User business:
- Name: {user_data.get('business_name', 'Unknown')}
- Product: {user_data.get('product', 'Unknown')}
- Income: {user_data.get('monthly_revenue', 'Unknown')}

Question: {text}
"""
        ai_response = client.models.generate_content(model=MODEL, contents=ai_prompt)
        if lang == "bm":
            send_message(phone, f"🤖 *AI Penasihat:*\n\n{ai_response.text}\n\n_(Tanya lagi atau taip MENU)_")
        else:
            send_message(phone, f"🤖 *AI Advisor:*\n\n{ai_response.text}\n\n_(Ask more or type MENU)_")

    elif intent == "show_menu":
        handle_menu(phone, "MENU", user_ref)

    else:
        # Unknown — treat as AI question
        lang_instruction = "Bahasa Malaysia mudah" if lang == "bm" else "simple English"
        ai_prompt = f"""
You are an AI business advisor for small Malaysian entrepreneurs.
Answer in {lang_instruction}. Maximum 4 sentences.
If this is not a business question, politely redirect them to type MENU.

Question: {text}
"""
        ai_response = client.models.generate_content(model=MODEL, contents=ai_prompt)
        if lang == "bm":
            send_message(phone, f"🤖 {ai_response.text}\n\n_(Taip MENU untuk pilihan)_")
        else:
            send_message(phone, f"🤖 {ai_response.text}\n\n_(Type MENU for options)_")

# ─────────────────────────────────────
# MENU
# ─────────────────────────────────────
def handle_menu(phone, text, user_ref):
    t_upper = text.upper().strip()
    user_data = user_ref.get().to_dict()
    name = user_data.get("owner_name", user_data.get("business_name", "Peniaga"))
    lang = user_data.get("language", "bm")
    cc = get_country(user_data)
    cur = cc["currency"]

    if t_upper in ["MENU", "HI", "HAI", "START"]:
        if lang == "bm":
            send_message(phone,
                f"📱 *Menu BizBuddy — {name}*\n"
                "━━━━━━━━━━━━━━━━━━\n\n"
                "📊 *JUALAN & JEJAK*\n"
                "1️⃣  Rekod Jualan Hari Ini\n"
                "5️⃣  Ringkasan Jualan Saya\n\n"
                "💳 *KREDIT & PINJAMAN*\n"
                "2️⃣  Jana Skor Kredit Saya\n"
                "4️⃣  Hantar Gambar Resit/Bayaran\n"
                "7️⃣  Ramalan Jualan AI\n\n"
                "🤖 *BANTUAN AI*\n"
                "3️⃣  Tanya Soalan Perniagaan\n"
                "6️⃣  Jana Kandungan Media Sosial\n"
                "8️⃣  Tip Rantaian Bekalan\n"
                "9️⃣  Panduan Eksport ASEAN\n\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "📋 PROFIL • 🎓 SIJIL • 📊 PECAHAN\n"
                "💰 PINJAMAN • ✉️ RUJUK • ✓ SAHKAN\n"
                "🌐 ENGLISH • 🔒 DATA\n\n"
                "_Balas 1-9 atau taip arahan_"
            )
        else:
            send_message(phone,
                f"📱 *BizBuddy Menu — {name}*\n"
                "━━━━━━━━━━━━━━━━━━\n\n"
                "📊 *SALES & TRACKING*\n"
                "1️⃣  Record Today's Sales\n"
                "5️⃣  My Sales Summary\n\n"
                "💳 *CREDIT & LOANS*\n"
                "2️⃣  Generate My Credit Score\n"
                "4️⃣  Send Receipt/Payment Photo\n"
                "7️⃣  AI Sales Forecast\n\n"
                "🤖 *AI ASSISTANCE*\n"
                "3️⃣  Ask Business Question\n"
                "6️⃣  Generate Social Media Content\n"
                "8️⃣  AI Supply Chain Tips\n"
                "9️⃣  ASEAN Export Guide\n\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "📋 PROFILE • 🎓 CERTIFICATE • 📊 BREAKDOWN\n"
                "💰 LOAN • ✉️ REFER • ✓ VERIFY\n"
                "🌐 BM • 🔒 DATA\n\n"
                "_Reply 1-9 or type command_"
            )
    elif t_upper == "1":
        user_ref.update({"state": "log_sale"})
        if lang == "bm":
            send_message(phone, f"💰 *Rekod Jualan*\n\nCeritakan jualan awak hari ini.\n_(Contoh: {cc['sale_example_bm']})_")
        else:
            send_message(phone, f"💰 *Record Sales*\n\nTell me about your sales today.\n_(Example: {cc['sale_example_en']})_")
    elif t_upper == "2":
        # Check if user already answered the 3 credit questions before
        check_data = user_ref.get().to_dict()
        has_answers = check_data.get("biz_age") and check_data.get("has_bank_account") and check_data.get("has_ssm")
        if has_answers:
            # Show current info and ask if anything changed
            user_ref.update({"state": "credit_confirm"})
            if lang == "bm":
                send_message(phone,
                    "📊 *Jana Skor Kredit*\n\n"
                    "Maklumat semasa awak:\n\n"
                    f"🏦 Akaun bank: *{check_data.get('has_bank_account')}*\n"
                    f"📝 {cc['registration']}: *{check_data.get('has_ssm')}*\n\n"
                    "Adakah maklumat ini masih *sama*?\n\n"
                    "Taip *YA* → Jana skor terus\n"
                    "Taip *TIDAK* → Kemaskini maklumat"
                )
            else:
                send_message(phone,
                    "📊 *Generate Credit Score*\n\n"
                    "Your current info:\n\n"
                    f"🏦 Bank account: *{check_data.get('has_bank_account')}*\n"
                    f"📝 {cc['registration']}: *{check_data.get('has_ssm')}*\n\n"
                    "Is this info still *correct*?\n\n"
                    "Type *YES* → Generate score now\n"
                    "Type *NO* → Update info"
                )
        else:
            user_ref.update({"state": "credit_q1"})
            if lang == "bm":
                send_message(phone, "📊 *Jana Skor Kredit*\n\nSaya perlu tanya 3 soalan tambahan untuk skor yang lebih tepat.\n\nSoalan 1️⃣: Berapa lama perniagaan awak dah beroperasi?\n_(Contoh: 3 bulan, 1 tahun, 5 tahun)_")
            else:
                send_message(phone, "📊 *Generate Credit Score*\n\nI need to ask 3 additional questions for a more accurate score.\n\nQuestion 1️⃣: How long has your business been operating?\n_(Example: 3 months, 1 year, 5 years)_")
    elif t_upper == "3":
        user_ref.update({"state": "ai_chat"})
        if lang == "bm":
            send_message(phone, f"🤖 *AI Penasihat Perniagaan*\n\nTanya apa sahaja! Contoh:\n• Macam mana nak tetapkan harga?\n• Macam mana nak mohon pinjaman {cc['loan_program']}?\n• Macam mana nak promosi online?\n\n_(Taip MENU untuk kembali)_")
        else:
            send_message(phone, f"🤖 *AI Business Advisor*\n\nAsk me anything! Examples:\n• How do I set my prices?\n• How do I apply for a {cc['loan_program']} loan?\n• How do I promote online?\n\n_(Type MENU to go back)_")
    elif t_upper == "4":
        if lang == "bm":
            send_message(phone, "📸 *Hantar Gambar Resit*\n\nHantar gambar resit atau screenshot bayaran WhatsApp awak.\nSaya akan rekod jualan awak secara automatik!\n\n_(Taip MENU untuk kembali)_")
        else:
            send_message(phone, "📸 *Send Receipt Photo*\n\nSend a photo of your receipt or WhatsApp payment screenshot.\nI will automatically record your sale!\n\n_(Type MENU to go back)_")
    elif t_upper == "5":
        show_sales_summary(phone, user_ref)
    elif t_upper == "6":
        user_ref.update({"state": "content_menu"})
        if lang == "bm":
            send_message(phone,
                "✨ *Jana Kandungan Media Sosial*\n\n"
                "Pilih jenis kandungan:\n\n"
                "1️⃣ Caption Instagram\n"
                "2️⃣ Mesej WhatsApp Blast\n"
                "3️⃣ Skrip Video TikTok\n"
                "4️⃣ Post Facebook\n"
                "5️⃣ Idea Promosi Musim\n\n"
                "_(Taip MENU untuk kembali)_"
            )
        else:
            send_message(phone,
                "✨ *Social Media Content Generator*\n\n"
                "Choose content type:\n\n"
                "1️⃣ Instagram Caption\n"
                "2️⃣ WhatsApp Blast Message\n"
                "3️⃣ TikTok Video Script\n"
                "4️⃣ Facebook Post\n"
                "5️⃣ Seasonal Promotion Ideas\n\n"
                "_(Type MENU to go back)_"
            )
    elif t_upper == "7":
        show_sales_forecast(phone, user_ref)
    elif t_upper == "8":
        show_supply_chain_tips(phone, user_ref)
    elif t_upper == "9":
        show_export_guide(phone, user_ref)
    else:
        if lang == "bm":
            send_message(phone, "Taip *MENU* untuk lihat pilihan awak 😊")
        else:
            send_message(phone, "Type *MENU* to see your options 😊")

# ─────────────────────────────────────
# LOG SALE
# ─────────────────────────────────────
def handle_log_sale(phone, text, user_ref):
    user_data = user_ref.get().to_dict()
    lang = user_data.get("language", "bm")
    cur = get_currency(user_data)

    if text.upper() == "MENU":
        user_ref.update({"state": "menu"})
        handle_menu(phone, "MENU", user_ref)
        return

    prompt = f"""
    Extract sale information from this text: "{text}"
    Return ONLY valid JSON, nothing else:
    {{"amount": number, "item": "string", "quantity": number}}
    If cannot extract amount, use 0.
    """
    response = client.models.generate_content(model=MODEL, contents=prompt)
    try:
        clean = response.text.strip().replace("```json","").replace("```","")
        sale = json.loads(clean)
    except:
        sale = {"amount": 0, "item": text, "quantity": 1}

    user_ref.update({
        "state": "menu",
        "sales": firestore.ArrayUnion([{
            "amount": sale["amount"],
            "item": sale["item"],
            "date": str(datetime.now().date())
        }])
    })

    if lang == "bm":
        send_message(phone, f"✅ *Jualan direkod!*\n\n💵 Jumlah: {cur}{sale['amount']}\n📦 Item: {sale['item']}\n\nData ini disimpan untuk profil kredit awak 📊\nTaip *MENU* untuk kembali")
    else:
        send_message(phone, f"✅ *Sale recorded!*\n\n💵 Amount: {cur}{sale['amount']}\n📦 Item: {sale['item']}\n\nThis data is saved for your credit profile 📊\nType *MENU* to go back")

# ─────────────────────────────────────
# AI CHAT
# ─────────────────────────────────────
def handle_ai_chat(phone, text, user_ref):
    user_data = user_ref.get().to_dict()
    lang = user_data.get("language", "bm")

    if text.upper() == "MENU":
        user_ref.update({"state": "menu"})
        handle_menu(phone, "MENU", user_ref)
        return

    lang_instruction = "Bahasa Malaysia yang mudah dan praktikal" if lang == "bm" else "simple and practical English"
    prompt = f"""
    You are an AI business advisor for small Malaysian entrepreneurs.
    Answer in {lang_instruction}. Maximum 4 sentences.

    User business:
    - Name: {user_data.get('business_name', 'Unknown')}
    - Product: {user_data.get('product', 'Unknown')}
    - Income: {user_data.get('monthly_revenue', 'Unknown')}

    Question: {text}
    """
    response = client.models.generate_content(model=MODEL, contents=prompt)
    if lang == "bm":
        send_message(phone, f"🤖 *AI Penasihat:*\n\n{response.text}\n\n_(Tanya lagi atau taip MENU)_")
    else:
        send_message(phone, f"🤖 *AI Advisor:*\n\n{response.text}\n\n_(Ask more or type MENU)_")

# ─────────────────────────────────────
# SHOW STORED DATA (Privacy)
# ─────────────────────────────────────
def show_stored_data(phone, user_ref):
    user_data = user_ref.get().to_dict()
    lang = user_data.get("language", "bm")
    sales = user_data.get("sales", [])
    expenses = user_data.get("expenses", [])

    if lang == "bm":
        send_message(phone,
            "🔒 *DATA YANG DISIMPAN TENTANG AWAK*\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 Nama: {user_data.get('owner_name', '-')}\n"
            f"🏪 Perniagaan: {user_data.get('business_name', '-')}\n"
            f"📦 Produk: {user_data.get('product', '-')}\n"
            f"💵 Pendapatan: {user_data.get('monthly_revenue', '-')}\n"
            f"⏱️ Lama Beroperasi: {user_data.get('biz_age', '-')}\n"
            f"🏦 Akaun Bank: {user_data.get('has_bank_account', '-')}\n"
            f"📝 SSM: {user_data.get('has_ssm', '-')}\n"
            f"⭐ Skor Kredit: {user_data.get('credit_score', '-')}\n"
            f"📊 Jumlah Rekod Jualan: {len(sales)}\n"
            f"📊 Jumlah Rekod Perbelanjaan: {len(expenses)}\n"
            f"✅ Persetujuan: {user_data.get('consent_date', '-')}\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "🗑️ Taip *RESET* untuk padam semua data awak\n"
            "Taip *MENU* untuk kembali"
        )
    else:
        send_message(phone,
            "🔒 *DATA STORED ABOUT YOU*\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 Name: {user_data.get('owner_name', '-')}\n"
            f"🏪 Business: {user_data.get('business_name', '-')}\n"
            f"📦 Product: {user_data.get('product', '-')}\n"
            f"💵 Income: {user_data.get('monthly_revenue', '-')}\n"
            f"⏱️ Years Operating: {user_data.get('biz_age', '-')}\n"
            f"🏦 Bank Account: {user_data.get('has_bank_account', '-')}\n"
            f"📝 SSM: {user_data.get('has_ssm', '-')}\n"
            f"⭐ Credit Score: {user_data.get('credit_score', '-')}\n"
            f"📊 Sales Records: {len(sales)}\n"
            f"📊 Expense Records: {len(expenses)}\n"
            f"✅ Consent Given: {user_data.get('consent_date', '-')}\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "🗑️ Type *RESET* to delete all your data\n"
            "Type *MENU* to go back"
        )

# ─────────────────────────────────────
# CREDIT SCORE — DETERMINISTIC FORMULA
# ─────────────────────────────────────
def calculate_credit_score(user_data):
    """
    Hybrid AI Credit Scoring: Deterministic formula for the number,
    AI (Gemini) only for human-readable explanation.
    
    Breakdown (100 points total):
    - Transaction Consistency: 25 pts (how regularly they record sales)
    - Revenue Strength:       20 pts (total sales vs stated income)
    - Business Age:           15 pts (years in operation)
    - Formalization:          20 pts (SSM + bank account)
    - Record Volume:          10 pts (number of transactions)
    - Expense Discipline:     10 pts (tracking expenses shows maturity)
    """
    sales = user_data.get("sales", [])
    expenses = user_data.get("expenses", [])
    total_sales = sum(s.get("amount", 0) for s in sales)
    count = len(sales)

    breakdown = {}

    # 1. TRANSACTION CONSISTENCY (25 pts)
    # How many unique days have sales out of total days since first sale
    consistency_score = 0
    if count > 0:
        dates = sorted(set(s.get("date", "") for s in sales if s.get("date")))
        if len(dates) >= 2:
            from datetime import date
            try:
                first = date.fromisoformat(dates[0])
                last = date.fromisoformat(dates[-1])
                total_days = max((last - first).days, 1)
                unique_days = len(dates)
                ratio = min(unique_days / total_days, 1.0)
                consistency_score = round(ratio * 25)
            except:
                consistency_score = min(count, 5) * 2  # fallback
        else:
            consistency_score = 5  # at least 1 sale recorded
    breakdown["consistency"] = min(consistency_score, 25)

    # 2. REVENUE STRENGTH (20 pts)
    # Compare total recorded sales to stated monthly income
    revenue_score = 0
    monthly_rev_str = user_data.get("monthly_revenue", "0")
    try:
        monthly_rev = int(''.join(filter(str.isdigit, str(monthly_rev_str))))
    except:
        monthly_rev = 0

    if monthly_rev > 0 and total_sales > 0:
        ratio = total_sales / monthly_rev
        if ratio >= 3:
            revenue_score = 20
        elif ratio >= 2:
            revenue_score = 16
        elif ratio >= 1:
            revenue_score = 12
        elif ratio >= 0.5:
            revenue_score = 8
        else:
            revenue_score = 4
    elif total_sales > 0:
        revenue_score = 6
    breakdown["revenue"] = min(revenue_score, 20)

    # 3. BUSINESS AGE (15 pts)
    # Auto-calculate: original biz_age answer + time since registration
    age_score = 0
    biz_age = user_data.get("biz_age", "").lower()
    
    # Calculate total months in business
    total_months = 0
    
    # Parse original answer for starting age
    try:
        age_num = int(''.join(filter(str.isdigit, biz_age)))
        if "year" in biz_age or "tahun" in biz_age:
            total_months = age_num * 12
        elif "month" in biz_age or "bulan" in biz_age:
            total_months = age_num
        else:
            total_months = age_num * 12  # assume years
    except:
        total_months = 0

    # Add months since registration on BizBuddy
    reg_date_str = user_data.get("registered_date", "")
    if reg_date_str:
        try:
            from datetime import date
            reg_date = date.fromisoformat(reg_date_str)
            months_on_platform = max((date.today() - reg_date).days // 30, 0)
            total_months += months_on_platform
        except:
            pass

    # Score based on total months
    if total_months >= 60:       # 5+ years
        age_score = 15
    elif total_months >= 36:     # 3+ years
        age_score = 12
    elif total_months >= 12:     # 1+ year
        age_score = 9
    elif total_months >= 6:      # 6+ months
        age_score = 6
    elif total_months >= 3:      # 3+ months
        age_score = 4
    elif total_months > 0:
        age_score = 2
    else:
        age_score = 1
    breakdown["age"] = min(age_score, 15)

    # 4. FORMALIZATION (20 pts)
    # SSM registration: 10 pts, Bank account: 10 pts
    formal_score = 0
    has_ssm = user_data.get("has_ssm", "").lower()
    has_bank = user_data.get("has_bank_account", "").lower()
    ssm_verified = user_data.get("ssm_verified", False)
    bank_verified = user_data.get("bank_verified", False)

    if has_ssm.startswith("y") or has_ssm.startswith("s"):
        formal_score += 10 if ssm_verified else 7
    elif has_ssm.startswith("t") or has_ssm.startswith("n"):
        formal_score += 0
    else:
        formal_score += 2

    if has_bank.startswith("y") or has_bank.startswith("a"):
        formal_score += 10 if bank_verified else 7
    elif has_bank.startswith("t") or has_bank.startswith("n"):
        formal_score += 0
    else:
        formal_score += 2
    breakdown["formalization"] = min(formal_score, 20)

    # 5. RECORD VOLUME (10 pts)
    if count >= 30:
        vol_score = 10
    elif count >= 20:
        vol_score = 8
    elif count >= 10:
        vol_score = 6
    elif count >= 5:
        vol_score = 4
    elif count >= 1:
        vol_score = 2
    else:
        vol_score = 0
    breakdown["volume"] = vol_score

    # 6. EXPENSE DISCIPLINE (10 pts)
    exp_count = len(expenses)
    if exp_count >= 10:
        exp_score = 10
    elif exp_count >= 5:
        exp_score = 7
    elif exp_count >= 2:
        exp_score = 4
    elif exp_count >= 1:
        exp_score = 2
    else:
        exp_score = 0
    breakdown["expenses"] = exp_score

    # TOTAL
    total_score = sum(breakdown.values())
    total_score = max(0, min(total_score, 100))

    # LEVEL
    if total_score >= 80:
        level = "Cemerlang"
        level_en = "Excellent"
    elif total_score >= 60:
        level = "Baik"
        level_en = "Good"
    elif total_score >= 40:
        level = "Sederhana"
        level_en = "Moderate"
    else:
        level = "Rendah"
        level_en = "Low"

    return total_score, level, level_en, breakdown


def generate_credit_score(phone, user_ref):
    user_data = user_ref.get().to_dict()
    sales = user_data.get("sales", [])
    total = sum(s.get("amount", 0) for s in sales)
    count = len(sales)
    lang = user_data.get("language", "bm")
    cc = get_country(user_data)
    cur = cc["currency"]
    reg = cc["registration"]

    # STEP 1: Calculate deterministic score
    score_num, level_bm, level_en, breakdown = calculate_credit_score(user_data)

    # Save to Firebase
    user_ref.update({
        "credit_score": score_num,
        "score_date": str(datetime.now().date()),
        "score_breakdown": breakdown,
        "score_history": firestore.ArrayUnion([{
            "date": str(datetime.now().date()),
            "score": score_num
        }])
    })

    # STEP 2: Use AI only for explanation and improvement tips
    lang_instruction = "Bahasa Malaysia" if lang == "bm" else "English"
    prompt = f"""
You are a credit advisor for small businesses. The credit score has ALREADY been calculated.
DO NOT change the score. Just explain it and give improvement tips.

Respond in {lang_instruction}.

SCORE: {score_num}/100
LEVEL: {level_bm if lang == "bm" else level_en}

Score breakdown:
- Transaction Consistency: {breakdown['consistency']}/25
- Revenue Strength: {breakdown['revenue']}/20
- Business Age: {breakdown['age']}/15
- Formalization ({reg} + Bank): {breakdown['formalization']}/20
- Record Volume: {breakdown['volume']}/10
- Expense Discipline: {breakdown['expenses']}/10

Business info:
- Name: {user_data.get('owner_name')}
- Business: {user_data.get('business_name')}
- Product: {user_data.get('product')}
- Reported income: {user_data.get('monthly_revenue')}
- Total sales recorded: {cur}{total}
- Transactions: {count}

Use EXACTLY this format:
SKOR: {score_num}/100
TAHAP: {level_bm if lang == "bm" else level_en}

📊 PECAHAN SKOR:
• Konsistensi Jualan: {breakdown['consistency']}/25
• Kekuatan Hasil: {breakdown['revenue']}/20
• Umur Perniagaan: {breakdown['age']}/15
• Formalisasi: {breakdown['formalization']}/20
• Jumlah Rekod: {breakdown['volume']}/10
• Disiplin Perbelanjaan: {breakdown['expenses']}/10

SEBAB: [1 sentence explaining the overall score]

LANGKAH PENAMBAHBAIKAN:
LANGKAH 1: [specific improvement based on lowest scoring area]
LANGKAH 2: [second improvement]
LANGKAH 3: [third improvement]
"""
    response = client.models.generate_content(model=MODEL, contents=prompt)

    if lang == "bm":
        send_message(phone,
            f"📊 *Laporan Skor Kredit Awak*\n\n"
            f"{response.text}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🔬 _Skor dikira menggunakan formula hibrid AI_\n"
            f"_berdasarkan 6 kriteria yang telus dan boleh diaudit._\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"💡 Rekod lebih banyak jualan untuk tingkatkan skor!\n"
            f"Taip *SIJIL* untuk jana sijil kredit awak\n"
            f"Taip *MENU* untuk kembali"
        )
    else:
        send_message(phone,
            f"📊 *Your Credit Score Report*\n\n"
            f"{response.text}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🔬 _Score calculated using hybrid AI formula_\n"
            f"_based on 6 transparent, auditable criteria._\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"💡 Record more sales to improve your score!\n"
            f"Type *CERTIFICATE* to generate your credit certificate\n"
            f"Type *MENU* to go back"
        )

# ─────────────────────────────────────
# SALES SUMMARY
# ─────────────────────────────────────
def show_sales_summary(phone, user_ref):
    user_data = user_ref.get().to_dict()
    sales = user_data.get("sales", [])
    expenses = user_data.get("expenses", [])
    lang = user_data.get("language", "bm")
    cur = get_currency(user_data)

    if not sales and not expenses:
        if lang == "bm":
            send_message(phone, "📊 *Ringkasan Jualan*\n\nAwak belum rekod sebarang jualan lagi.\nTaip *1* untuk rekod jualan pertama awak!\n\nTaip *MENU* untuk kembali")
        else:
            send_message(phone, "📊 *Sales Summary*\n\nYou haven't recorded any sales yet.\nType *1* to record your first sale!\n\nType *MENU* to go back")
        return

    total_sales = sum(s.get("amount", 0) for s in sales)
    total_expenses = sum(e.get("amount", 0) for e in expenses)
    profit = total_sales - total_expenses
    margin = round((profit / total_sales) * 100) if total_sales > 0 else 0
    count = len(sales)
    average = total_sales / count if count > 0 else 0
    best = max(s.get("amount", 0) for s in sales) if sales else 0

    # Profit health indicator
    if margin >= 50:
        health = "🟢 Sihat" if lang == "bm" else "🟢 Healthy"
    elif margin >= 20:
        health = "🟡 Sederhana" if lang == "bm" else "🟡 Moderate"
    elif margin > 0:
        health = "🔴 Rendah" if lang == "bm" else "🔴 Low"
    else:
        health = "⚠️ Rugi" if lang == "bm" else "⚠️ Loss"

    recent = sales[-5:]
    recent_text = ""
    for s in reversed(recent):
        recent_text += f"• {cur}{s.get('amount', 0)} — {s.get('item', '-')} ({s.get('date', '-')})\n"

    if lang == "bm":
        send_message(phone,
            "📊 *Ringkasan Kewangan Awak*\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"💵 Jumlah Jualan: {cur}{total_sales}\n"
            f"💸 Jumlah Perbelanjaan: {cur}{total_expenses}\n"
            f"📈 *Keuntungan: {cur}{profit}*\n"
            f"📊 Margin Keuntungan: {margin}% {health}\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"🔢 Jumlah Transaksi: {count}\n"
            f"📈 Purata Per Transaksi: {cur}{average:.0f}\n"
            f"🏆 Jualan Terbesar: {cur}{best}\n"
            f"📦 Rekod Perbelanjaan: {len(expenses)}\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📋 *5 Jualan Terkini:*\n{recent_text}\n"
            "💡 _Rekod perbelanjaan dengan taip: beli bahan rm50_\n"
            "Taip *MENU* untuk kembali"
        )
    else:
        send_message(phone,
            "📊 *Your Financial Summary*\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"💵 Total Sales: {cur}{total_sales}\n"
            f"💸 Total Expenses: {cur}{total_expenses}\n"
            f"📈 *Profit: {cur}{profit}*\n"
            f"📊 Profit Margin: {margin}% {health}\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"🔢 Transactions: {count}\n"
            f"📈 Average Per Sale: {cur}{average:.0f}\n"
            f"🏆 Biggest Sale: {cur}{best}\n"
            f"📦 Expense Records: {len(expenses)}\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📋 *Last 5 Sales:*\n{recent_text}\n"
            "💡 _Track expenses by typing: bought supplies rm50_\n"
            "Type *MENU* to go back"
        )

# ─────────────────────────────────────
# EXPORT PROFILE
# ─────────────────────────────────────
def show_profile(phone, user_ref):
    user_data = user_ref.get().to_dict()
    lang = user_data.get("language", "bm")
    cc = get_country(user_data)
    cur = cc["currency"]
    sales = user_data.get("sales", [])
    total = sum(s.get("amount", 0) for s in sales)
    count = len(sales)
    score = user_data.get("credit_score", "Belum dijana" if lang == "bm" else "Not yet generated")
    score_date = user_data.get("score_date", "-")

    if lang == "bm":
        send_message(phone,
            "━━━━━━━━━━━━━━━━━━━━\n"
            "📋 *PROFIL PERNIAGAAN RASMI*\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 Nama: {user_data.get('owner_name', '-')}\n"
            f"🏪 Perniagaan: {user_data.get('business_name', '-')}\n"
            f"📦 Produk: {user_data.get('product', '-')}\n"
            f"🌏 Negara: {cc['flag']} {cc['name']}\n"
            f"📍 Negeri: {user_data.get('user_state', '-')}\n"
            f"💵 Pendapatan Bulanan: {user_data.get('monthly_revenue', '-')}\n"
            f"⏱️ Lama Beroperasi: {user_data.get('biz_age', '-')}\n"
            f"🏦 Akaun Bank: {user_data.get('has_bank_account', '-')}\n"
            f"📝 {cc['registration']}: {user_data.get('has_ssm', '-')}\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 Jumlah Jualan Direkod: {cur}{total}\n"
            f"🔢 Bilangan Transaksi: {count}\n"
            f"⭐ Skor Kredit: {score}\n"
            f"📅 Tarikh Skor: {score_date}\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "🏷️ _Powered by BizBuddy_\n\n"
            "Taip *MENU* untuk kembali"
        )
    else:
        send_message(phone,
            "━━━━━━━━━━━━━━━━━━━━\n"
            "📋 *OFFICIAL BUSINESS PROFILE*\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 Name: {user_data.get('owner_name', '-')}\n"
            f"🏪 Business: {user_data.get('business_name', '-')}\n"
            f"📦 Product: {user_data.get('product', '-')}\n"
            f"🌏 Country: {cc['flag']} {cc['name']}\n"
            f"📍 State: {user_data.get('user_state', '-')}\n"
            f"💵 Monthly Income: {user_data.get('monthly_revenue', '-')}\n"
            f"⏱️ Years Operating: {user_data.get('biz_age', '-')}\n"
            f"🏦 Bank Account: {user_data.get('has_bank_account', '-')}\n"
            f"📝 {cc['registration']}: {user_data.get('has_ssm', '-')}\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 Total Recorded Sales: {cur}{total}\n"
            f"🔢 Number of Transactions: {count}\n"
            f"⭐ Credit Score: {score}\n"
            f"📅 Score Date: {score_date}\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "🏷️ _Powered by BizBuddy_\n\n"
            "Type *MENU* to go back"
        )

# ─────────────────────────────────────
# CREDIT CERTIFICATE
# ─────────────────────────────────────
def show_certificate(phone, user_ref):
    user_data = user_ref.get().to_dict()
    lang = user_data.get("language", "bm")
    score = user_data.get("credit_score", 0)
    score_date = user_data.get("score_date", str(datetime.now().date()))

    if not score:
        if lang == "bm":
            send_message(phone, "⚠️ Awak belum jana skor kredit lagi.\nTaip *MENU* → pilih *2* untuk jana skor kredit awak dahulu.")
        else:
            send_message(phone, "⚠️ You haven't generated a credit score yet.\nType *MENU* → choose *2* to generate your credit score first.")
        return

    if score >= 70:
        status_bm = "✅ BERSEDIA UNTUK PINJAMAN"
        status_en = "✅ LOAN READY"
        stars = "⭐⭐⭐⭐⭐" if score >= 85 else "⭐⭐⭐⭐"
    elif score >= 50:
        status_bm = "🔄 DALAM PROSES"
        status_en = "🔄 IN PROGRESS"
        stars = "⭐⭐⭐"
    else:
        status_bm = "📈 PERLU TINGKATKAN"
        status_en = "📈 NEEDS IMPROVEMENT"
        stars = "⭐⭐"

    if lang == "bm":
        send_message(phone,
            "🏆 ━━━━━━━━━━━━━━━━━━━━ 🏆\n"
            "*SIJIL KESEDIAAN KREDIT*\n"
            "🏆 ━━━━━━━━━━━━━━━━━━━━ 🏆\n\n"
            f"👤 Nama: {user_data.get('owner_name', '-')}\n"
            f"🏪 Perniagaan: {user_data.get('business_name', '-')}\n\n"
            f"📊 SKOR KREDIT: *{score}/100*\n"
            f"⭐ TAHAP: {stars}\n"
            f"🎯 STATUS: {status_bm}\n\n"
            f"📅 Tarikh Jana: {score_date}\n"
            f"🆔 ID: NC-{phone[-4:]}-{score_date.replace('-','')}\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Sijil ini mengesahkan bahawa\n"
            "perniagaan ini telah merekod\n"
            "aktiviti kewangan dan dinilai\n"
            "oleh sistem BizBuddy AI.\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "🏷️ _Powered by BizBuddy_\n"
            "_bizbuddy.my_\n\n"
            "💡 Screenshot dan tunjukkan kepada bank!\n"
            "Taip *MENU* untuk kembali"
        )
    else:
        send_message(phone,
            "🏆 ━━━━━━━━━━━━━━━━━━━━ 🏆\n"
            "*CREDIT READINESS CERTIFICATE*\n"
            "🏆 ━━━━━━━━━━━━━━━━━━━━ 🏆\n\n"
            f"👤 Name: {user_data.get('owner_name', '-')}\n"
            f"🏪 Business: {user_data.get('business_name', '-')}\n\n"
            f"📊 CREDIT SCORE: *{score}/100*\n"
            f"⭐ LEVEL: {stars}\n"
            f"🎯 STATUS: {status_en}\n\n"
            f"📅 Date Issued: {score_date}\n"
            f"🆔 ID: NC-{phone[-4:]}-{score_date.replace('-','')}\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "This certificate verifies that\n"
            "this business has recorded\n"
            "financial activity and has been\n"
            "assessed by BizBuddy AI.\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "🏷️ _Powered by BizBuddy_\n"
            "_bizbuddy.my_\n\n"
            "💡 Screenshot and show to your bank!\n"
            "Type *MENU* to go back"
        )

# ─────────────────────────────────────
# SSM VERIFICATION PROMPT
# ─────────────────────────────────────
def prompt_ssm_verification(phone, user_ref):
    user_data = user_ref.get().to_dict()
    lang = user_data.get("language", "bm")
    cc = get_country(user_data)
    reg_type = cc["registration"]

    # Already verified?
    if user_data.get("ssm_verified"):
        reg_number = user_data.get("ssm_reg_number", "N/A")
        verified_date = user_data.get("ssm_verified_date", "N/A")
        cert_biz = user_data.get("ssm_cert_business_name", "-")
        if lang == "bm":
            send_message(phone,
                f"✅ *Perniagaan awak sudah disahkan!*\n\n"
                f"🏢 Nama: {cert_biz}\n"
                f"🔢 No. {reg_type}: {reg_number}\n"
                f"📅 Tarikh Sahkan: {verified_date}\n\n"
                "Taip *MENU* untuk kembali"
            )
        else:
            send_message(phone,
                f"✅ *Your business is already verified!*\n\n"
                f"🏢 Name: {cert_biz}\n"
                f"🔢 {reg_type} No: {reg_number}\n"
                f"📅 Verified on: {verified_date}\n\n"
                "Type *MENU* to go back"
            )
        return

    # Prompt user to send cert image
    user_ref.update({"state": "await_ssm_cert"})
    if lang == "bm":
        send_message(phone,
            f"📄 *Sahkan Pendaftaran {reg_type} Awak*\n\n"
            f"Hantar gambar sijil {reg_type} perniagaan awak.\n\n"
            "✅ Pastikan:\n"
            "• Gambar jelas dan tidak kabur\n"
            "• Nombor pendaftaran kelihatan\n"
            "• Nama perniagaan boleh dibaca\n\n"
            f"📸 *Hantar gambar sijil {reg_type} sekarang*\n\n"
            "Taip *BATAL* untuk batalkan"
        )
    else:
        send_message(phone,
            f"📄 *Verify Your {reg_type} Registration*\n\n"
            f"Please send a photo of your {reg_type} business registration certificate.\n\n"
            "✅ Make sure:\n"
            "• Image is clear and not blurry\n"
            "• Registration number is visible\n"
            "• Business name is readable\n\n"
            f"📸 *Send your {reg_type} certificate image now*\n\n"
            "Type *CANCEL* to cancel"
        )


# ─────────────────────────────────────
# HANDLE IMAGE
# ─────────────────────────────────────
def handle_image(phone, image_id):
    user_ref = db.collection("users").document(phone)
    user_snap = user_ref.get()
    user_data = user_snap.to_dict() if user_snap.exists else {}
    lang = user_data.get("language", "bm")
    state = user_data.get("state", "menu")

    if lang == "bm":
        send_message(phone, "📸 Gambar diterima! Sedang menganalisis... ⏳")
    else:
        send_message(phone, "📸 Image received! Analyzing... ⏳")

    # Download image from WhatsApp
    url = f"https://graph.facebook.com/v18.0/{image_id}"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
    media_info = requests.get(url, headers=headers).json()
    image_url = media_info.get("url", "")
    img_response = requests.get(image_url, headers=headers)

    import PIL.Image
    img = PIL.Image.open(BytesIO(img_response.content))

    # ── Route based on current state ──
    if state in ("await_ssm_cert", "await_ssm_cert_then_score"):
        handle_ssm_verification(phone, user_ref, user_data, img)
        return

    if state in ("await_bank_doc_then_reg", "await_bank_doc_then_score", "await_bank_doc"):
        handle_bank_verification(phone, user_ref, user_data, img, mode=state)
        return

    # ── Otherwise: triage — is this an SSM cert or a payment screenshot? ──
    triage_prompt = """
Analyze this image carefully. What type of document is it?

Return ONLY valid JSON, nothing else:
{
  "doc_type": "ssm_cert" | "payment" | "other",
  "confidence": "high" | "medium" | "low"
}

"ssm_cert" = Malaysian SSM business registration certificate, or NIB/DTI equivalent registration document
"payment" = receipt, invoice, bank transfer, payment screenshot, QR payment confirmation
"other" = anything else
"""
    triage_response = client.models.generate_content(model=MODEL, contents=[triage_prompt, img])
    try:
        triage_clean = triage_response.text.strip().replace("```json","").replace("```","")
        triage_data = json.loads(triage_clean)
    except:
        triage_data = {"doc_type": "other", "confidence": "low"}

    doc_type = triage_data.get("doc_type", "other")

    if doc_type == "ssm_cert":
        # Route to SSM verification
        handle_ssm_verification(phone, user_ref, user_data, img)
        return

    # ── Default: payment screenshot flow ──
    prompt = """
    Analyze this image. Is this a payment screenshot or receipt?
    Return ONLY valid JSON nothing else:
    {"amount": number, "item": "string", "is_payment": true}
    If not payment: {"amount": 0, "item": "unknown", "is_payment": false}
    """
    response = client.models.generate_content(model=MODEL, contents=[prompt, img])

    try:
        clean = response.text.strip().replace("```json","").replace("```","")
        data = json.loads(clean)
    except:
        data = {"amount": 0, "is_payment": False}

    if data.get("is_payment") and data.get("amount", 0) > 0:
        user_ref.update({
            "sales": firestore.ArrayUnion([{
                "amount": data["amount"],
                "item": data.get("item", "jualan"),
                "date": str(datetime.now().date()),
                "source": "screenshot"
            }])
        })
        if lang == "bm":
            send_message(phone, f"✅ *Bayaran direkod dari gambar!*\n\n💵 Jumlah: {get_currency(user_data)}{data['amount']}\n📦 Item: {data.get('item', 'Jualan')}\n\nTaip *MENU* untuk kembali")
        else:
            send_message(phone, f"✅ *Payment recorded from image!*\n\n💵 Amount: {get_currency(user_data)}{data['amount']}\n📦 Item: {data.get('item', 'Sale')}\n\nType *MENU* to go back")
    else:
        if lang == "bm":
            send_message(phone,
                "Saya tidak dapat mengesan bayaran dalam gambar ini.\n"
                "Cuba hantar screenshot yang lebih jelas.\n\n"
                "💡 _Jika ini sijil SSM/pendaftaran perniagaan, taip *VERIFY* untuk sahkan perniagaan awak._\n\n"
                "Taip *MENU* untuk kembali"
            )
        else:
            send_message(phone,
                "I could not detect a payment in this image.\n"
                "Please send a clearer screenshot.\n\n"
                "💡 _If this is your SSM/business registration cert, type *VERIFY* to verify your business._\n\n"
                "Type *MENU* to go back"
            )


# ─────────────────────────────────────
# SSM / BUSINESS CERT VERIFICATION
# ─────────────────────────────────────
def handle_ssm_verification(phone, user_ref, user_data, img, after_score=False):
    """Use Gemini Vision to extract and verify SSM/NIB/DTI certificate details."""
    lang = user_data.get("language", "bm")
    cc = get_country(user_data)
    reg_type = cc["registration"]  # SSM / NIB / DTI
    registered_business_name = user_data.get("business_name", "").strip().lower()

    extract_prompt = f"""
You are verifying a business registration certificate from {cc['name']}.
The registration body is {reg_type}.

Extract the following from this certificate image. Return ONLY valid JSON, nothing else:
{{
  "is_registration_cert": true or false,
  "reg_number": "the registration/certificate number as shown",
  "business_name": "exact business name as printed on the certificate",
  "owner_name": "owner or director name if visible, else null",
  "reg_date": "registration date if visible, else null",
  "status": "active or unknown",
  "cert_type": "type of registration e.g. Sole Proprietor, Partnership, Company, NIB, DTI etc."
}}

If this is NOT a {reg_type} registration certificate, set "is_registration_cert": false and leave other fields null.
"""
    response = client.models.generate_content(model=MODEL, contents=[extract_prompt, img])

    try:
        clean = response.text.strip().replace("```json","").replace("```","")
        cert_data = json.loads(clean)
    except:
        cert_data = {"is_registration_cert": False}

    if not cert_data.get("is_registration_cert"):
        if lang == "bm":
            send_message(phone,
                f"❌ *Dokumen tidak dikenali sebagai sijil {reg_type}.*\n\n"
                f"Sila hantar gambar sijil pendaftaran perniagaan {reg_type} yang jelas.\n\n"
                "Taip *MENU* untuk kembali"
            )
        else:
            send_message(phone,
                f"❌ *Document not recognised as a {reg_type} registration certificate.*\n\n"
                f"Please send a clear photo of your {reg_type} business registration certificate.\n\n"
                "Type *MENU* to go back"
            )
        return

    # Cross-check business name
    cert_biz_name = (cert_data.get("business_name") or "").strip().lower()
    reg_number = cert_data.get("reg_number", "N/A")
    reg_date = cert_data.get("reg_date", "N/A")
    cert_type = cert_data.get("cert_type", reg_type)
    owner_on_cert = cert_data.get("owner_name", "")

    # Fuzzy name match — check if registered_business_name words appear in cert name
    name_match = False
    if registered_business_name and cert_biz_name:
        # Match if either name contains significant words from the other
        reg_words = set(registered_business_name.split())
        cert_words = set(cert_biz_name.split())
        # Remove common filler words
        stopwords = {"sdn","bhd","enterprise","trading","the","and","&","co","sdn.","bhd.","(m)"}
        reg_words -= stopwords
        cert_words -= stopwords
        if reg_words and cert_words:
            overlap = reg_words & cert_words
            name_match = len(overlap) / max(len(reg_words), 1) >= 0.5
        else:
            name_match = True  # one name is all stopwords, give benefit of doubt

    # Save verification result to Firestore
    user_ref.update({
        "has_ssm": "yes",
        "ssm_verified": True,
        "ssm_reg_number": reg_number,
        "ssm_cert_type": cert_type,
        "ssm_reg_date": reg_date,
        "ssm_cert_business_name": cert_data.get("business_name", ""),
        "ssm_name_match": name_match,
        "ssm_verified_date": str(datetime.now().date()),
    })

    # Build verification result message
    match_icon = "✅" if name_match else "⚠️"
    match_note_bm = "Nama perniagaan *sepadan*!" if name_match else "Nama perniagaan *tidak sepadan sepenuhnya* dengan profil awak — sila kemaskini jika perlu."
    match_note_en = "Business name *matches* your profile!" if name_match else "Business name *doesn't fully match* your profile — please update if needed."

    if lang == "bm":
        send_message(phone,
            f"🎉 *Sijil {reg_type} Disahkan!*\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"📋 *Butiran Sijil*\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"🏢 Nama Perniagaan: *{cert_data.get('business_name', 'N/A')}*\n"
            f"🔢 No. Pendaftaran: *{reg_number}*\n"
            f"📄 Jenis: {cert_type}\n"
            f"📅 Tarikh Daftar: {reg_date}\n"
            + (f"👤 Nama Pemilik: {owner_on_cert}\n" if owner_on_cert else "") +
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"{match_icon} {match_note_bm}\n\n"
            "🏅 *+10 mata kredit* untuk pengesahan sijil!\n\n"
            "Taip *SKOR* untuk lihat skor kredit terbaru awak\n"
            "Taip *MENU* untuk kembali ke menu"
        )
    else:
        send_message(phone,
            f"🎉 *{reg_type} Certificate Verified!*\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"📋 *Certificate Details*\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"🏢 Business Name: *{cert_data.get('business_name', 'N/A')}*\n"
            f"🔢 Registration No: *{reg_number}*\n"
            f"📄 Type: {cert_type}\n"
            f"📅 Registration Date: {reg_date}\n"
            + (f"👤 Owner Name: {owner_on_cert}\n" if owner_on_cert else "") +
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"{match_icon} {match_note_en}\n\n"
            "🏅 *+10 credit points* for certificate verification!\n\n"
            "Type *SCORE* to see your updated credit score\n"
            "Type *MENU* to go back"
        )
    # Reset state to menu — user decides when to view score
    user_ref.update({"state": "menu"})

# ─────────────────────────────────────
# BANK ACCOUNT VERIFICATION
# ─────────────────────────────────────
def handle_bank_verification(phone, user_ref, user_data, img, mode="await_bank_doc_then_reg"):
    """Triage then extract bank account document. mode controls what happens after."""
    lang = user_data.get("language", "bm")
    owner_name = user_data.get("owner_name", "").strip().lower()

    # Step 1: Triage
    triage_prompt = """Analyze this image. What type of financial document is it?
Return ONLY valid JSON:
{"doc_type": "bank_statement" | "passbook" | "online_banking" | "e_wallet" | "other", "confidence": "high" | "medium" | "low"}
bank_statement = printed or PDF bank statement
passbook = physical bank savings book
online_banking = mobile/web banking app screenshot (Maybank2u, BCA Mobile, BDO, CIMB etc)
e_wallet = e-wallet screenshot (Touch n Go, GoPay, GCash, Maya, Dana)
other = anything else (receipt, SSM cert, ID, photo)"""

    triage_resp = client.models.generate_content(model=MODEL, contents=[triage_prompt, img])
    try:
        triage_data = json.loads(triage_resp.text.strip().replace("```json","").replace("```",""))
    except:
        triage_data = {"doc_type": "other"}

    doc_type = triage_data.get("doc_type", "other")

    if doc_type == "other":
        if lang == "bm":
            send_message(phone,
                "❌ *Dokumen tidak dikenali sebagai dokumen kewangan.*\n\n"
                "Sila hantar:\n"
                "• Screenshot penyata bank\n"
                "• Gambar buku bank (passbook)\n"
                "• Screenshot online banking / e-wallet\n\n"
                "Taip *LANGKAU* jika tidak mahu sahkan sekarang"
            )
        else:
            send_message(phone,
                "❌ *Document not recognised as a financial document.*\n\n"
                "Please send:\n"
                "• Bank statement screenshot\n"
                "• Bank book (passbook) photo\n"
                "• Online banking / e-wallet screenshot\n\n"
                "Type *SKIP* if you don't want to verify now"
            )
        return

    # Step 2: Tailored extraction
    prompts = {
        "bank_statement": '''Extract from this bank statement. Return ONLY valid JSON:
{"is_bank_document": true, "account_holder_name": "name as printed", "bank_name": "bank name", "account_number_last4": "last 4 digits or null", "business_name_on_account": "business name if present else null", "doc_type": "statement"}''',
        "passbook": '''Extract from this bank passbook. Return ONLY valid JSON:
{"is_bank_document": true, "account_holder_name": "name on passbook", "bank_name": "bank name", "account_number_last4": "last 4 digits or null", "business_name_on_account": null, "doc_type": "passbook"}''',
        "online_banking": '''Extract from this online/mobile banking screenshot. Return ONLY valid JSON:
{"is_bank_document": true, "account_holder_name": "name shown in app", "bank_name": "bank or app name", "account_number_last4": "last 4 digits or null", "business_name_on_account": null, "doc_type": "online_banking"}''',
        "e_wallet": '''Extract from this e-wallet screenshot. Return ONLY valid JSON:
{"is_bank_document": true, "account_holder_name": "registered name", "bank_name": "wallet name (TNG/GoPay/GCash/Maya/Dana)", "account_number_last4": "last 4 of phone/account or null", "business_name_on_account": null, "doc_type": "e_wallet"}''',
    }

    extract_resp = client.models.generate_content(model=MODEL, contents=[prompts.get(doc_type, prompts["online_banking"]), img])
    try:
        bank_data = json.loads(extract_resp.text.strip().replace("```json","").replace("```",""))
        bank_data["is_bank_document"] = True
    except:
        bank_data = {"is_bank_document": False}

    if not bank_data.get("is_bank_document"):
        if lang == "bm":
            send_message(phone, "❌ Gagal membaca dokumen. Sila cuba hantar gambar yang lebih jelas.\n\nTaip *LANGKAU* untuk langkau")
        else:
            send_message(phone, "❌ Failed to read document. Please try a clearer image.\n\nType *SKIP* to skip")
        return

    holder_name = (bank_data.get("account_holder_name") or "").strip().lower()
    biz_on_acc = (bank_data.get("business_name_on_account") or "").strip().lower()
    bank_name = bank_data.get("bank_name", "N/A")
    acc_last4 = bank_data.get("account_number_last4") or ""

    # Fuzzy name match
    stopwords = {"sdn","bhd","enterprise","trading","the","and","&","co","bin","binti","bte","mr","ms","mrs"}
    name_match = True
    if owner_name:
        owner_words = set(owner_name.split()) - stopwords
        holder_words = set(holder_name.split()) - stopwords
        biz_words = set(biz_on_acc.split()) - stopwords if biz_on_acc else set()
        if owner_words and (holder_words or biz_words):
            overlap = max(
                len(owner_words & holder_words) / max(len(owner_words), 1),
                len(owner_words & biz_words) / max(len(owner_words), 1) if biz_words else 0
            )
            name_match = overlap >= 0.5

    user_ref.update({
        "has_bank_account": "yes",
        "bank_verified": True,
        "bank_name": bank_name,
        "bank_holder_name": bank_data.get("account_holder_name", ""),
        "bank_acc_last4": acc_last4,
        "bank_name_match": name_match,
        "bank_verified_date": str(datetime.now().date()),
    })

    match_icon = "✅" if name_match else "⚠️"
    match_bm = "Nama *sepadan* dengan profil awak!" if name_match else "Nama *tidak sepadan sepenuhnya* — kemaskini profil jika perlu."
    match_en = "Name *matches* your profile!" if name_match else "Name *doesn't fully match* — update profile if needed."
    doc_labels = {"statement": "Penyata Bank", "passbook": "Buku Bank", "online_banking": "Online Banking", "e_wallet": "E-Wallet"}
    doc_label_bm = doc_labels.get(doc_type, "Dokumen Bank")
    doc_label_en = {"statement": "Bank Statement", "passbook": "Passbook", "online_banking": "Online Banking", "e_wallet": "E-Wallet"}.get(doc_type, "Bank Document")

    if lang == "bm":
        send_message(phone,
            "🎉 *Akaun Bank Disahkan!*\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"🏦 Bank: *{bank_name}*\n"
            f"👤 Pemegang: *{bank_data.get('account_holder_name', 'N/A')}*\n"
            + (f"🔢 No. Akaun: ****{acc_last4}\n" if acc_last4 else "") +
            f"📄 Jenis: {doc_label_bm}\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"{match_icon} {match_bm}\n\n"
            "🏅 *+10 mata kredit penuh* untuk akaun bank yang disahkan!\n"
        )
    else:
        send_message(phone,
            "🎉 *Bank Account Verified!*\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"🏦 Bank: *{bank_name}*\n"
            f"👤 Holder: *{bank_data.get('account_holder_name', 'N/A')}*\n"
            + (f"🔢 Account: ****{acc_last4}\n" if acc_last4 else "") +
            f"📄 Type: {doc_label_en}\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"{match_icon} {match_en}\n\n"
            "🏅 *+10 full credit points* for verified bank account!\n"
        )

    # Route based on mode
    if mode == "await_bank_doc_then_reg":
        # Came from credit flow — now ask SSM question
        user_data_fresh = user_ref.get().to_dict()
        cc = get_country(user_data_fresh)
        user_ref.update({"state": "credit_q3"})
        if lang == "bm":
            send_message(phone, f"\n⏩ Soalan seterusnya...\n\nSoalan 3️⃣: {cc['reg_question_bm']}\n_(Balas: Ya / Tidak)_")
        else:
            send_message(phone, f"\n⏩ Next question...\n\nQuestion 3️⃣: {cc['reg_question_en']}\n_(Reply: Yes / No)_")
    else:
        # Standalone BANK command — just reset to menu
        user_ref.update({"state": "menu"})
        if lang == "bm":
            send_message(phone, "Taip *SKOR* untuk lihat skor kredit terbaru awak\nTaip *MENU* untuk kembali")
        else:
            send_message(phone, "Type *SCORE* to see your updated credit score\nType *MENU* to go back")


# ─────────────────────────────────────
# LOAN READINESS CHECKLIST
# ─────────────────────────────────────
def show_loan_checklist(phone, user_ref):
    user_data = user_ref.get().to_dict()
    lang = user_data.get("language", "bm")
    cc = get_country(user_data)
    cur = cc["currency"]
    sales = user_data.get("sales", [])
    
    # Check each criteria
    has_profile = bool(user_data.get("owner_name"))
    has_sales = len(sales) > 0
    has_10_txn = len(sales) >= 10
    has_bank = bool(user_data.get("has_bank_account", "").lower().startswith("y"))
    has_ssm = bool(user_data.get("has_ssm", "").lower().startswith("y"))
    has_score = (user_data.get("credit_score", 0) or 0) >= 60
    has_30days = False
    
    # Check if sales span 30+ days
    if len(sales) >= 2:
        dates = sorted([s.get("date","") for s in sales if s.get("date")])
        if len(dates) >= 2:
            from datetime import date
            try:
                first = date.fromisoformat(dates[0])
                last = date.fromisoformat(dates[-1])
                has_30days = (last - first).days >= 30
            except:
                has_30days = False

    reg = cc["registration"]
    checks = [
        (has_profile, 
         "Profil perniagaan wujud" if lang=="bm" else "Business profile created",
         "Daftar profil awak" if lang=="bm" else "Register your profile"),
        (has_sales,
         "Rekod jualan pertama" if lang=="bm" else "First sale recorded", 
         "Rekod jualan pertama awak" if lang=="bm" else "Record your first sale"),
        (has_10_txn,
         f"10+ transaksi ({len(sales)}/10)" if lang=="bm" else f"10+ transactions ({len(sales)}/10)",
         "Rekod lebih banyak jualan" if lang=="bm" else "Record more sales"),
        (has_30days,
         "30 hari rekod jualan" if lang=="bm" else "30 days of sales records",
         "Terus rekod setiap hari" if lang=="bm" else "Keep recording daily"),
        (has_bank,
         "Ada akaun bank perniagaan" if lang=="bm" else "Has business bank account",
         "Buka akaun bank perniagaan" if lang=="bm" else "Open a business bank account"),
        (has_ssm,
         f"Berdaftar {reg}" if lang=="bm" else f"{reg} registered",
         f"Daftar {reg} di {cc['reg_url']}" if lang=="bm" else f"Register at {cc['reg_url']}"),
        (has_score,
         f"Skor kredit 60+ (kini: {user_data.get('credit_score','?')})" if lang=="bm" else f"Credit score 60+ (now: {user_data.get('credit_score','?')})",
         "Jana skor kredit → pilih 2" if lang=="bm" else "Generate credit score → choose 2"),
    ]

    done = sum(1 for c in checks if c[0])
    total = len(checks)
    pct = round(done/total*100)
    
    # Progress bar
    filled = round(pct/10)
    bar = "█" * filled + "░" * (10-filled)

    lines = ""
    for check, label, action in checks:
        if check:
            lines += f"✅ {label}\n"
        else:
            lines += f"⬜ {label}\n    ↳ {action}\n"

    loan = cc["loan_program"]
    if pct == 100:
        status = f"🎉 TAHNIAH! Awak layak mohon pinjaman {loan}!" if lang=="bm" else f"🎉 CONGRATULATIONS! You qualify for a {loan} loan!"
    elif pct >= 70:
        status = f"🔥 Hampir layak! Siapkan {total-done} lagi syarat." if lang=="bm" else f"🔥 Almost there! Complete {total-done} more requirements."
    elif pct >= 40:
        status = f"💪 Dalam proses. Perlukan {total-done} lagi syarat." if lang=="bm" else f"💪 In progress. Need {total-done} more requirements."
    else:
        status = f"📈 Baru bermula. Perlukan {total-done} lagi syarat." if lang=="bm" else f"📈 Just starting. Need {total-done} more requirements."

    if lang == "bm":
        send_message(phone,
            f"🏦 *SENARAI SEMAK PINJAMAN {loan.upper()}*\n\n"
            f"Kemajuan: [{bar}] {pct}%\n"
            f"({done}/{total} syarat dipenuhi)\n\n"
            f"{lines}\n"
            f"{status}\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"💡 {loan}: sehingga {cc['loan_amount']}\n"
            f"💡 Faedah rendah: {cc['loan_rate']} setahun\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Taip *MENU* untuk kembali"
        )
    else:
        send_message(phone,
            f"🏦 *{loan.upper()} LOAN READINESS CHECKLIST*\n\n"
            f"Progress: [{bar}] {pct}%\n"
            f"({done}/{total} requirements met)\n\n"
            f"{lines}\n"
            f"{status}\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"💡 {loan}: up to {cc['loan_amount']}\n"
            f"💡 Low interest: {cc['loan_rate']} per year\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Type *MENU* to go back"
        )
# ─────────────────────────────────────
# CONTENT MENU
# ─────────────────────────────────────
def handle_content_menu(phone, text, user_ref):
    user_data = user_ref.get().to_dict()
    lang = user_data.get("language", "bm")
    t_upper = text.upper().strip()

    if t_upper == "MENU":
        user_ref.update({"state": "menu"})
        handle_menu(phone, "MENU", user_ref)
        return

    content_types = {
        "1": ("instagram", "Caption Instagram", "Instagram Caption"),
        "2": ("whatsapp", "Mesej WhatsApp Blast", "WhatsApp Blast Message"),
        "3": ("tiktok", "Skrip Video TikTok", "TikTok Video Script"),
        "4": ("facebook", "Post Facebook", "Facebook Post"),
        "5": ("promosi", "Idea Promosi Musim", "Seasonal Promotion Ideas"),
    }

    if t_upper in content_types:
        ctype, label_bm, label_en = content_types[t_upper]
        user_ref.update({"state": "content_generate", "content_type": ctype})
        if lang == "bm":
            send_message(phone,
                f"✨ *{label_bm}*\n\n"
                "Beritahu saya lebih detail!\n\n"
                "Contoh:\n"
                "• _promosi raya minggu depan_\n"
                "• _jualan clearance stok lama_\n"
                "• _produk baru baru sampai_\n"
                "• _diskaun 20% untuk 10 pembeli pertama_\n\n"
                "Atau taip *SKIP* untuk jana kandungan umum.\n"
                "_(Taip MENU untuk kembali)_"
            )
        else:
            send_message(phone,
                f"✨ *{label_en}*\n\n"
                "Tell me more details!\n\n"
                "Examples:\n"
                "• _raya promotion next week_\n"
                "• _clearance sale old stock_\n"
                "• _new product just arrived_\n"
                "• _20% discount for first 10 buyers_\n\n"
                "Or type *SKIP* to generate general content.\n"
                "_(Type MENU to go back)_"
            )
    else:
        if lang == "bm":
            send_message(phone, "Sila pilih 1-5 atau taip *MENU* untuk kembali.")
        else:
            send_message(phone, "Please choose 1-5 or type *MENU* to go back.")

# ─────────────────────────────────────
# CONTENT GENERATOR
# ─────────────────────────────────────
def handle_content_generate(phone, text, user_ref):
    user_data = user_ref.get().to_dict()
    lang = user_data.get("language", "bm")
    ctype = user_data.get("content_type", "instagram")

    if text.upper() == "MENU":
        user_ref.update({"state": "menu"})
        handle_menu(phone, "MENU", user_ref)
        return

    detail = "" if text.upper() == "SKIP" else text
    lang_instruction = "Bahasa Malaysia yang menarik dan natural" if lang == "bm" else "natural and engaging English"

    business_name = user_data.get("business_name", "perniagaan saya")
    product = user_data.get("product", "produk")
    owner_name = user_data.get("owner_name", "peniaga")

    prompts = {
        "instagram": f"""
You are a social media expert for small Malaysian businesses.
Create an Instagram caption in {lang_instruction} for:
- Business: {business_name}
- Product: {product}
- Special detail: {detail if detail else 'general promotion'}

Format:
- 3-4 lines of engaging caption
- 2 relevant emojis per line
- Call to action (DM/WhatsApp)
- 10-15 relevant Malaysian hashtags

Make it sound authentic, not corporate. Like a real Malaysian seller.
""",
        "whatsapp": f"""
You are a marketing expert for small Malaysian businesses.
Create a WhatsApp broadcast message in {lang_instruction} for:
- Business: {business_name}
- Product: {product}
- Special detail: {detail if detail else 'general promotion'}

Format:
- Greeting with emoji
- Short exciting offer (2-3 lines)
- Key benefits (3 bullet points)
- Clear call to action
- Contact info placeholder

Keep it under 200 words. Conversational tone like texting a friend.
""",
        "tiktok": f"""
You are a TikTok content creator for small Malaysian businesses.
Create a TikTok video script in {lang_instruction} for:
- Business: {business_name}
- Product: {product}
- Special detail: {detail if detail else 'showcase product'}

Format:
HOOK (0-3 sec): [attention grabbing opening line]
CONTENT (3-25 sec): [what to show/say step by step]
CTA (25-30 sec): [call to action]
CAPTION: [TikTok caption with hashtags]

Make it trendy and fun. Include suggestions for what to film.
""",
        "facebook": f"""
You are a Facebook marketing expert for small Malaysian businesses.
Create a Facebook post in {lang_instruction} for:
- Business: {business_name}
- Product: {product}
- Special detail: {detail if detail else 'general promotion'}

Format:
- Attention-grabbing first line
- Story or benefit (3-4 lines)
- Clear offer or call to action
- 5-8 relevant hashtags

Tone: Friendly, trustworthy, community-focused.
""",
        "promosi": f"""
You are a marketing strategist for small Malaysian businesses.
Generate 3 creative promotion ideas in {lang_instruction} for:
- Business: {business_name}
- Product: {product}
- Context: {detail if detail else 'general seasonal promotion'}

For each idea provide:
- Idea name
- How to execute it (2-3 steps)
- Expected benefit

Focus on low-cost, high-impact ideas suitable for small Malaysian businesses.
Include ideas relevant to Malaysian culture (Raya, Ramadan, Merdeka, etc if applicable).
"""
    }

    if lang == "bm":
        send_message(phone, "⏳ Sedang menjana kandungan untuk awak...")
    else:
        send_message(phone, "⏳ Generating content for you...")

    prompt = prompts.get(ctype, prompts["instagram"])
    response = client.models.generate_content(model=MODEL, contents=prompt)

    type_labels_bm = {
        "instagram": "📸 CAPTION INSTAGRAM",
        "whatsapp": "📱 MESEJ WHATSAPP BLAST",
        "tiktok": "🎵 SKRIP TIKTOK",
        "facebook": "📘 POST FACEBOOK",
        "promosi": "💡 IDEA PROMOSI"
    }
    type_labels_en = {
        "instagram": "📸 INSTAGRAM CAPTION",
        "whatsapp": "📱 WHATSAPP BLAST",
        "tiktok": "🎵 TIKTOK SCRIPT",
        "facebook": "📘 FACEBOOK POST",
        "promosi": "💡 PROMOTION IDEAS"
    }

    label = type_labels_bm.get(ctype) if lang == "bm" else type_labels_en.get(ctype)

    user_ref.update({"state": "content_menu"})

    if lang == "bm":
        send_message(phone,
            f"✨ *{label} SIAP!*\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"{response.text}\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "📋 *Copy dan paste terus!*\n\n"
            "Nak jana lagi?\n"
            "1️⃣ Caption Instagram\n"
            "2️⃣ WhatsApp Blast\n"
            "3️⃣ Skrip TikTok\n"
            "4️⃣ Post Facebook\n"
            "5️⃣ Idea Promosi\n\n"
            "_(Taip MENU untuk kembali)_"
        )
    else:
        send_message(phone,
            f"✨ *{label} READY!*\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"{response.text}\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "📋 *Copy and paste directly!*\n\n"
            "Generate more?\n"
            "1️⃣ Instagram Caption\n"
            "2️⃣ WhatsApp Blast\n"
            "3️⃣ TikTok Script\n"
            "4️⃣ Facebook Post\n"
            "5️⃣ Promotion Ideas\n\n"
            "_(Type MENU to go back)_"
        )
# ─────────────────────────────────────
# SCORE BREAKDOWN (standalone view)
# ─────────────────────────────────────
def show_score_breakdown(phone, user_ref):
    user_data = user_ref.get().to_dict()
    lang = user_data.get("language", "bm")
    cc = get_country(user_data)
    score = user_data.get("credit_score", 0)
    breakdown = user_data.get("score_breakdown", {})

    if not score or not breakdown:
        if lang == "bm":
            send_message(phone, "⚠️ Awak belum jana skor kredit lagi.\nTaip *MENU* → pilih *2* untuk jana skor kredit dahulu.")
        else:
            send_message(phone, "⚠️ You haven't generated a credit score yet.\nType *MENU* → choose *2* to generate your score first.")
        return

    # Find weakest area
    categories = {
        "consistency": {"max": 25, "bm": "Konsistensi Jualan", "en": "Sales Consistency"},
        "revenue": {"max": 20, "bm": "Kekuatan Hasil", "en": "Revenue Strength"},
        "age": {"max": 15, "bm": "Umur Perniagaan", "en": "Business Age"},
        "formalization": {"max": 20, "bm": f"Formalisasi ({cc['registration']})", "en": f"Formalization ({cc['registration']})"},
        "volume": {"max": 10, "bm": "Jumlah Rekod", "en": "Record Volume"},
        "expenses": {"max": 10, "bm": "Disiplin Perbelanjaan", "en": "Expense Discipline"},
    }

    # Build visual bars
    lines = ""
    weakest_key = None
    weakest_pct = 100
    for key, info in categories.items():
        val = breakdown.get(key, 0)
        mx = info["max"]
        pct = round((val / mx) * 100) if mx > 0 else 0
        filled = round(pct / 10)
        bar = "█" * filled + "░" * (10 - filled)
        label = info["bm"] if lang == "bm" else info["en"]
        lines += f"  {label}\n  [{bar}] {val}/{mx}\n\n"
        if pct < weakest_pct:
            weakest_pct = pct
            weakest_key = key

    weakest_label = categories[weakest_key]["bm" if lang == "bm" else "en"] if weakest_key else ""

    if lang == "bm":
        send_message(phone,
            f"📊 *PECAHAN SKOR KREDIT*\n\n"
            f"Skor Keseluruhan: *{score}/100*\n\n"
            f"{lines}"
            f"⚡ *Fokus tingkatkan:* {weakest_label}\n\n"
            "Taip *MENU* untuk kembali"
        )
    else:
        send_message(phone,
            f"📊 *CREDIT SCORE BREAKDOWN*\n\n"
            f"Overall Score: *{score}/100*\n\n"
            f"{lines}"
            f"⚡ *Focus on improving:* {weakest_label}\n\n"
            "Type *MENU* to go back"
        )

# ─────────────────────────────────────
# LOAN REFERRAL PIPELINE
# ─────────────────────────────────────
def show_loan_referral(phone, user_ref):
    user_data = user_ref.get().to_dict()
    lang = user_data.get("language", "bm")
    cc = get_country(user_data)
    cur = cc["currency"]
    score = user_data.get("credit_score", 0)

    if not score or score < 60:
        needed = 60 - (score or 0)
        if lang == "bm":
            send_message(phone,
                f"⚠️ *Skor kredit awak belum mencukupi untuk rujukan pinjaman.*\n\n"
                f"Skor semasa: {score or 0}/100\n"
                f"Skor minimum: 60/100\n"
                f"Perlukan: +{needed} lagi mata\n\n"
                "💡 Cara tingkatkan skor:\n"
                "• Rekod lebih banyak jualan setiap hari\n"
                "• Rekod perbelanjaan awak\n"
                f"• Daftar {cc['registration']} jika belum\n"
                "• Buka akaun bank perniagaan\n\n"
                "Taip *PECAHAN* untuk lihat pecahan skor\n"
                "Taip *MENU* untuk kembali"
            )
        else:
            send_message(phone,
                f"⚠️ *Your credit score is not yet sufficient for loan referral.*\n\n"
                f"Current score: {score or 0}/100\n"
                f"Minimum required: 60/100\n"
                f"Need: +{needed} more points\n\n"
                "💡 How to improve:\n"
                "• Record more sales daily\n"
                "• Track your expenses\n"
                f"• Register with {cc['registration']} if not done\n"
                "• Open a business bank account\n\n"
                "Type *BREAKDOWN* to see score details\n"
                "Type *MENU* to go back"
            )
        return

    # Generate referral message
    owner = user_data.get("owner_name", "-")
    biz = user_data.get("business_name", "-")
    product = user_data.get("product", "-")
    revenue = user_data.get("monthly_revenue", "-")
    sales = user_data.get("sales", [])
    total_sales = sum(s.get("amount", 0) for s in sales)
    txn_count = len(sales)
    score_date = user_data.get("score_date", "-")
    cert_id = f"NC-{phone[-4:]}-{score_date.replace('-', '')}"
    loan = cc["loan_program"]

    referral_msg = (
        f"📋 PERMOHONAN PENILAIAN PINJAMAN\n"
        f"{'='*35}\n\n"
        f"Kepada: Pegawai {loan}\n\n"
        f"Saya ingin memohon penilaian pinjaman mikro.\n\n"
        f"MAKLUMAT PEMOHON:\n"
        f"• Nama: {owner}\n"
        f"• Perniagaan: {biz}\n"
        f"• Produk/Perkhidmatan: {product}\n"
        f"• Pendapatan Bulanan: {revenue}\n"
        f"• Negara: {cc['flag']} {cc['name']}\n"
        f"• Negeri: {user_data.get('user_state', '-')}\n\n"
        f"REKOD KEWANGAN (BizBuddy):\n"
        f"• Jumlah Jualan Direkod: {cur}{total_sales}\n"
        f"• Bilangan Transaksi: {txn_count}\n"
        f"• Skor Kredit BizBuddy: {score}/100\n"
        f"• ID Sijil: {cert_id}\n"
        f"• Tarikh Skor: {score_date}\n\n"
        f"Skor ini dijana oleh BizBuddy AI berdasarkan 6 kriteria yang telus.\n\n"
        f"Terima kasih.\n"
        f"{'='*35}\n"
        f"Powered by BizBuddy | bizbuddy.my"
    ) if lang == "bm" else (
        f"📋 LOAN ASSESSMENT REQUEST\n"
        f"{'='*35}\n\n"
        f"To: {loan} Officer\n\n"
        f"I would like to request a micro-loan assessment.\n\n"
        f"APPLICANT INFO:\n"
        f"• Name: {owner}\n"
        f"• Business: {biz}\n"
        f"• Product/Service: {product}\n"
        f"• Monthly Income: {revenue}\n"
        f"• Country: {cc['flag']} {cc['name']}\n"
        f"• State: {user_data.get('user_state', '-')}\n\n"
        f"FINANCIAL RECORDS (BizBuddy):\n"
        f"• Total Recorded Sales: {cur}{total_sales}\n"
        f"• Number of Transactions: {txn_count}\n"
        f"• BizBuddy Credit Score: {score}/100\n"
        f"• Certificate ID: {cert_id}\n"
        f"• Score Date: {score_date}\n\n"
        f"This score was generated by BizBuddy AI based on 6 transparent criteria.\n\n"
        f"Thank you.\n"
        f"{'='*35}\n"
        f"Powered by BizBuddy | bizbuddy.my"
    )

    if lang == "bm":
        send_message(phone,
            "🏦 *RUJUKAN PINJAMAN SEDIA!*\n\n"
            "Mesej berikut telah dijana untuk awak.\n"
            f"📋 *Copy dan hantar* kepada pegawai {loan}:\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"{referral_msg}\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "📱 *Langkah seterusnya:*\n"
            "1. Screenshot mesej di atas\n"
            f"2. Hantar ke pejabat {loan} terdekat\n"
            "3. Atau email ke pegawai pinjaman\n\n"
            "Taip *SIJIL* untuk sijil kredit awak\n"
            "Taip *MENU* untuk kembali"
        )
    else:
        send_message(phone,
            "🏦 *LOAN REFERRAL READY!*\n\n"
            "The following message has been generated for you.\n"
            f"📋 *Copy and send* to a {loan} officer:\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"{referral_msg}\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "📱 *Next steps:*\n"
            "1. Screenshot the message above\n"
            f"2. Send to your nearest {loan} office\n"
            "3. Or email to a loan officer\n\n"
            "Type *CERTIFICATE* for your credit certificate\n"
            "Type *MENU* to go back"
        )

# ─────────────────────────────────────
# 7️⃣ AI SALES FORECAST (Predictive Analytics)
# ─────────────────────────────────────
def show_sales_forecast(phone, user_ref):
    user_data = user_ref.get().to_dict()
    lang = user_data.get("language", "bm")
    cc = get_country(user_data)
    cur = cc["currency"]
    sales = user_data.get("sales", [])
    expenses = user_data.get("expenses", [])
    total_sales = sum(s.get("amount", 0) for s in sales)
    total_expenses = sum(e.get("amount", 0) for e in expenses)
    count = len(sales)

    if count < 3:
        if lang == "bm":
            send_message(phone, "⚠️ *Perlukan sekurang-kurangnya 3 rekod jualan* untuk ramalan AI.\n\nRekod lebih banyak jualan dahulu, kemudian cuba lagi!\nTaip *MENU* untuk kembali")
        else:
            send_message(phone, "⚠️ *Need at least 3 sales records* for AI forecast.\n\nRecord more sales first, then try again!\nType *MENU* to go back")
        return

    if lang == "bm":
        send_message(phone, "📈 Sedang menganalisis corak jualan awak...")
    else:
        send_message(phone, "📈 Analyzing your sales patterns...")

    # Build sales timeline for AI
    sales_timeline = "\n".join([f"- {s.get('date','?')}: {cur}{s.get('amount',0)} ({s.get('item','?')})" for s in sales[-15:]])
    expense_timeline = "\n".join([f"- {e.get('date','?')}: {cur}{e.get('amount',0)} ({e.get('item','?')})" for e in expenses[-10:]])

    lang_instruction = "Bahasa Malaysia yang mudah" if lang == "bm" else "simple English"
    prompt = f"""
You are a predictive analytics AI for small ASEAN businesses.
Respond in {lang_instruction}.

Analyze this MSME's sales data and provide:

BUSINESS INFO:
- Business: {user_data.get('business_name', '?')}
- Product: {user_data.get('product', '?')}
- Country: {cc['name']}
- State: {user_data.get('user_state', '?')}
- Monthly Revenue (stated): {user_data.get('monthly_revenue', '?')}
- Total Recorded Sales: {cur}{total_sales}
- Total Expenses: {cur}{total_expenses}
- Number of transactions: {count}

RECENT SALES (latest first):
{sales_timeline}

RECENT EXPENSES:
{expense_timeline}

Provide EXACTLY this format:
📈 *RAMALAN JUALAN / SALES FORECAST*

🔮 *Ramalan 30 Hari Seterusnya:*
• Anggaran jualan: {cur}[amount range]
• Trend: [naik/turun/stabil] [reason]

📊 *Corak Yang Dikesan:*
• [pattern 1 - e.g. peak days, best selling items]
• [pattern 2 - e.g. seasonal trends]
• [pattern 3 - e.g. expense ratio insight]

💡 *Cadangan Untuk Tingkatkan Jualan:*
• [specific actionable tip 1 based on their data]
• [specific actionable tip 2]
• [specific actionable tip 3]

⚠️ *Risiko:*
• [1 risk they should watch out for based on the data]

Keep it practical and data-driven. Reference their actual numbers.
"""
    response = client.models.generate_content(model=MODEL, contents=prompt)

    if lang == "bm":
        send_message(phone,
            f"📈 *RAMALAN JUALAN AI*\n"
            f"_{user_data.get('business_name', '')} — {cc['flag']} {user_data.get('user_state', cc['name'])}_\n\n"
            f"{response.text}\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "🔬 _Ramalan dijana oleh AI berdasarkan data jualan sebenar awak_\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "Taip *MENU* untuk kembali"
        )
    else:
        send_message(phone,
            f"📈 *AI SALES FORECAST*\n"
            f"_{user_data.get('business_name', '')} — {cc['flag']} {user_data.get('user_state', cc['name'])}_\n\n"
            f"{response.text}\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "🔬 _Forecast generated by AI based on your actual sales data_\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "Type *MENU* to go back"
        )

# ─────────────────────────────────────
# 8️⃣ AI SUPPLY CHAIN TIPS
# ─────────────────────────────────────
def show_supply_chain_tips(phone, user_ref):
    user_data = user_ref.get().to_dict()
    lang = user_data.get("language", "bm")
    cc = get_country(user_data)
    cur = cc["currency"]
    sales = user_data.get("sales", [])
    expenses = user_data.get("expenses", [])
    total_sales = sum(s.get("amount", 0) for s in sales)
    total_expenses = sum(e.get("amount", 0) for e in expenses)
    profit_margin = round(((total_sales - total_expenses) / total_sales) * 100) if total_sales > 0 else 0

    if lang == "bm":
        send_message(phone, "📦 Sedang menganalisis rantaian bekalan awak...")
    else:
        send_message(phone, "📦 Analyzing your supply chain...")

    # Build expense breakdown for AI
    expense_list = "\n".join([f"- {e.get('date','?')}: {cur}{e.get('amount',0)} ({e.get('item','?')})" for e in expenses[-15:]])
    sales_items = "\n".join([f"- {s.get('item','?')}: {cur}{s.get('amount',0)}" for s in sales[-10:]])

    lang_instruction = "Bahasa Malaysia yang mudah" if lang == "bm" else "simple English"
    prompt = f"""
You are an AI supply chain advisor for small ASEAN businesses.
Respond in {lang_instruction}.

BUSINESS INFO:
- Business: {user_data.get('business_name', '?')}
- Product: {user_data.get('product', '?')}
- Country: {cc['name']}, State: {user_data.get('user_state', '?')}
- Total Sales: {cur}{total_sales}
- Total Expenses: {cur}{total_expenses}
- Profit Margin: {profit_margin}%

EXPENSE RECORDS (what they buy/spend on):
{expense_list if expense_list else "No expenses recorded yet"}

WHAT THEY SELL:
{sales_items}

Provide EXACTLY this format:

📦 *ANALISIS RANTAIAN BEKALAN*

💰 *Kesihatan Kos:*
• Margin keuntungan: {profit_margin}% — [assessment: sihat/perlu perhatian/kritikal]
• Nisbah kos bahan: [analysis of their expense ratio]

🏭 *Cadangan Pembekal & Inventori:*
• [Tip 1 - specific to their product type, e.g. buy in bulk, find wholesale supplier]
• [Tip 2 - inventory management tip]
• [Tip 3 - seasonal stocking advice]

📉 *Cara Kurangkan Kos:*
• [Cost saving tip 1 based on their expenses]
• [Cost saving tip 2]

🤝 *Peluang Kerjasama:*
• [Suggestion to partner with other MSMEs or join a cooperative]
• [Platform/marketplace suggestion for their country]

Keep it practical for a small {cc['name']} business. Reference their actual expense data.
"""
    response = client.models.generate_content(model=MODEL, contents=prompt)

    if lang == "bm":
        send_message(phone,
            f"📦 *TIP RANTAIAN BEKALAN AI*\n"
            f"_{user_data.get('business_name', '')} — {cc['flag']} {user_data.get('user_state', cc['name'])}_\n\n"
            f"{response.text}\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "🔬 _Analisis dijana oleh AI berdasarkan data perbelanjaan sebenar awak_\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "💡 Rekod perbelanjaan awak untuk analisis lebih tepat!\n"
            "Taip *MENU* untuk kembali"
        )
    else:
        send_message(phone,
            f"📦 *AI SUPPLY CHAIN TIPS*\n"
            f"_{user_data.get('business_name', '')} — {cc['flag']} {user_data.get('user_state', cc['name'])}_\n\n"
            f"{response.text}\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "🔬 _Analysis generated by AI based on your actual expense data_\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "💡 Record your expenses for more accurate analysis!\n"
            "Type *MENU* to go back"
        )

# ─────────────────────────────────────
# 9️⃣ ASEAN CROSS-BORDER EXPORT GUIDE
# ─────────────────────────────────────
def show_export_guide(phone, user_ref):
    user_data = user_ref.get().to_dict()
    lang = user_data.get("language", "bm")
    cc = get_country(user_data)
    cur = cc["currency"]
    sales = user_data.get("sales", [])
    total_sales = sum(s.get("amount", 0) for s in sales)

    if lang == "bm":
        send_message(phone, "🌏 Sedang menganalisis peluang eksport ASEAN...")
    else:
        send_message(phone, "🌏 Analyzing ASEAN export opportunities...")

    # Determine target markets (other ASEAN countries)
    other_countries = {k: v for k, v in COUNTRY_CONFIG.items() if k != user_data.get("country", "MY")}
    target_list = ", ".join([f"{v['flag']} {v['name']}" for v in other_countries.values()])

    lang_instruction = "Bahasa Malaysia yang mudah" if lang == "bm" else "simple English"
    prompt = f"""
You are an ASEAN cross-border trade advisor for small businesses.
Respond in {lang_instruction}.

BUSINESS INFO:
- Business: {user_data.get('business_name', '?')}
- Product: {user_data.get('product', '?')}
- Home Country: {cc['name']} ({cc['flag']})
- State: {user_data.get('user_state', '?')}
- Monthly Revenue: {user_data.get('monthly_revenue', '?')}
- Total Recorded Sales: {cur}{total_sales}
- Credit Score: {user_data.get('credit_score', 'N/A')}/100

TARGET MARKETS: {target_list}

Provide EXACTLY this format:

🌏 *PANDUAN EKSPORT ASEAN*

📊 *Penilaian Kesediaan Eksport:*
• Kesediaan: [Sedia / Hampir sedia / Perlu persediaan] — [1 sentence why]

🎯 *Pasaran Sasaran Terbaik:*
• [Country 1] — [why their product fits this market, e.g. demand, cultural fit]
• [Country 2] — [why]

📋 *Langkah Untuk Mula Eksport:*
1. [Step 1 - e.g. get export license, specific to their country]
2. [Step 2 - e.g. find a distributor/platform]
3. [Step 3 - e.g. comply with regulations]
4. [Step 4 - e.g. logistics/shipping]

💰 *Anggaran Kos Eksport:*
• [Typical costs for a small MSME to start exporting from their country]

🛒 *Platform E-Commerce Serantau:*
• [2-3 actual ASEAN marketplace platforms relevant to their product, e.g. Shopee, Lazada, Tokopedia]

⚖️ *Peraturan Penting:*
• [1-2 key regulations, e.g. halal certification for food, ASEAN trade agreements]

Keep it specific to their product ({user_data.get('product', '?')}) and their home country ({cc['name']}).
Focus on practical, low-cost entry strategies for small MSMEs.
Mention ASEAN Free Trade Area (AFTA) benefits where relevant.
"""
    response = client.models.generate_content(model=MODEL, contents=prompt)

    if lang == "bm":
        send_message(phone,
            f"🌏 *PANDUAN EKSPORT ASEAN*\n"
            f"_{user_data.get('business_name', '')} — {cc['flag']} {user_data.get('user_state', cc['name'])}_\n\n"
            f"{response.text}\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "🔬 _Panduan dijana oleh AI berdasarkan profil perniagaan awak_\n"
            "🌐 _Memanfaatkan rangka kerja ASEAN Free Trade Area (AFTA)_\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "Taip *MENU* untuk kembali"
        )
    else:
        send_message(phone,
            f"🌏 *ASEAN EXPORT GUIDE*\n"
            f"_{user_data.get('business_name', '')} — {cc['flag']} {user_data.get('user_state', cc['name'])}_\n\n"
            f"{response.text}\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "🔬 _Guide generated by AI based on your business profile_\n"
            "🌐 _Leveraging ASEAN Free Trade Area (AFTA) framework_\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "Type *MENU* to go back"
        )

# ─────────────────────────────────────
# SEND MESSAGE
# ─────────────────────────────────────
def send_message(phone, text):
    url = f"https://graph.facebook.com/v18.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "text",
        "text": {"body": text}
    }
    requests.post(url, headers=headers, json=payload)

if __name__ == "__main__":
    app.run(port=5000, debug=False)