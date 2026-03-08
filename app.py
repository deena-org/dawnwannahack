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
        print(f"Error: {e}")
    return jsonify({"status": "ok"}), 200

# ─────────────────────────────────────
# LANGUAGE HELPER
# ─────────────────────────────────────
def is_english(user_data):
    return user_data.get("language", "bm") == "en"

def t(user_data, bm_text, en_text):
    return en_text if is_english(user_data) else bm_text

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
        send_message(phone,
            "🌐 *Language switched to English!*\n\n"
            "All responses will now be in English.\n"
            "Type *BM* to switch back to Bahasa Malaysia."
        )
        return

    if text_upper == "BM":
        if user.exists:
            user_ref.update({"language": "bm"})
        send_message(phone,
            "🌐 *Bahasa ditukar ke Bahasa Malaysia!*\n\n"
            "Semua respons akan dalam Bahasa Malaysia.\n"
            "Taip *ENGLISH* untuk tukar ke Bahasa Inggeris."
        )
        return

    if not user.exists:
        user_ref.set({"state": "ask_owner_name", "sales": [], "language": "bm"})
        send_message(phone,
            "👋 *Selamat datang ke BizBuddy!*\n\n"
            "Saya akan bantu awak bina profil perniagaan dalam masa 5 minit.\n\n"
            "💡 _Tip: Taip ENGLISH untuk tukar bahasa_\n\n"
            "Soalan 1️⃣: Apa *nama awak*?"
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

    # Onboarding states
    if state == "ask_owner_name":
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
        user_ref.update({"product": text, "state": "ask_revenue"})
        if lang == "bm":
            send_message(phone, f"*{text}* — menarik! 🛍️\n\nSoalan 4️⃣: Dalam sebulan, lebih kurang berapa *pendapatan* awak?\n_(Contoh: RM500, RM2000, RM5000)_")
        else:
            send_message(phone, f"*{text}* — interesting! 🛍️\n\nQuestion 4️⃣: Roughly how much is your *monthly income*?\n_(Example: RM500, RM2000, RM5000)_")

    elif state == "ask_revenue":
        user_data = user_ref.get().to_dict()
        owner_name = user_data.get("owner_name", "")
        business_name = user_data.get("business_name", "")
        product = user_data.get("product", "")
        user_ref.update({"monthly_revenue": text, "state": "menu"})
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
            sales = user_data.get("sales", [])
            total = sum(s.get("amount", 0) for s in sales)
            score = user_data.get("credit_score", 0)
            if lang == "bm":
                send_message(phone,
                    f"👋 *Selamat kembali, {owner_name}!*\n\n"
                    f"📊 Jualan terkumpul: RM{total}\n"
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
                    f"📊 Total sales: RM{total}\n"
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
            if text_upper in ["1","2","3","4","5","6","MENU","PROFIL","PROFILE","SIJIL","CERTIFICATE","PINJAMAN","LOAN","RESET"]:
                handle_menu(phone, text, user_ref)
            else:
                smart_handle(phone, text, user_ref)

    elif state == "log_sale":
        handle_log_sale(phone, text, user_ref)

    elif state == "ai_chat":
        handle_ai_chat(phone, text, user_ref)

    elif state == "credit_q1":
        user_ref.update({"biz_age": text, "state": "credit_q2"})
        if lang == "bm":
            send_message(phone, f"✅ Noted!\n\nSoalan 2️⃣: Adakah awak ada *akaun bank perniagaan*?\n_(Balas: Ya / Tidak)_")
        else:
            send_message(phone, f"✅ Noted!\n\nQuestion 2️⃣: Do you have a *business bank account*?\n_(Reply: Yes / No)_")

    elif state == "credit_q2":
        user_ref.update({"has_bank_account": text, "state": "credit_q3"})
        if lang == "bm":
            send_message(phone, f"✅ Noted!\n\nSoalan 3️⃣: Adakah perniagaan awak dah *daftar SSM*?\n_(Balas: Ya / Tidak)_")
        else:
            send_message(phone, f"✅ Noted!\n\nQuestion 3️⃣: Is your business *registered with SSM*?\n_(Reply: Yes / No)_")

    elif state == "content_menu":
        handle_content_menu(phone, text, user_ref)

    elif state == "content_generate":
        handle_content_generate(phone, text, user_ref)

    elif state == "credit_q3":
        user_ref.update({"has_ssm": text, "state": "menu"})
        if lang == "bm":
            send_message(phone, "⏳ Sedang mengira skor kredit awak...")
        else:
            send_message(phone, "⏳ Calculating your credit score...")
        generate_credit_score(phone, user_ref)

# ─────────────────────────────────────
# SMART INTENT DETECTION
# ─────────────────────────────────────
def smart_handle(phone, text, user_ref):
    user_data = user_ref.get().to_dict()
    lang = user_data.get("language", "bm")
    text_upper = text.upper().strip()

    # Hard commands — no AI needed
    if text_upper == "MENU":
        handle_menu(phone, "MENU", user_ref)
        return
    if text_upper in ["1","2","3","4","5"]:
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
    if text_upper == "RESET":
        user_ref.delete()
        send_message(phone, "🔄 Profil dipadam. Taip HAI untuk mula semula." if lang=="bm" else "🔄 Profile deleted. Type HI to start again.")
        return

    # AI intent detection
    prompt = f"""
You are an intent classifier for a WhatsApp business bot.
Classify this message into ONE of these intents:

INTENTS:
- log_sale: user is recording a sale (mentions selling, jual, dapat, sold, received money)
- log_expense: user is recording an expense (mentions buying supplies, beli bahan, spent, beli, purchase)
- check_score: user asking about credit score (skor, score, markah)
- check_summary: user asking about sales summary (ringkasan, summary, jualan, berapa duit)
- ask_ai: user asking a business question (how to, macam mana, tips, advice, cara)
- show_menu: user wants to see menu options
- unknown: cannot classify

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
            send_message(phone, f"✅ *Jualan direkod terus!*\n\n💵 Jumlah: RM{sale['amount']}\n📦 Item: {sale['item']}\n\nTaip *MENU* untuk pilihan lain.")
        else:
            send_message(phone, f"✅ *Sale recorded directly!*\n\n💵 Amount: RM{sale['amount']}\n📦 Item: {sale['item']}\n\nType *MENU* for other options.")

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
            send_message(phone, f"✅ *Perbelanjaan direkod!*\n\n💸 Jumlah: RM{expense['amount']}\n📦 Item: {expense['item']}\n\nTaip *MENU* untuk pilihan lain.")
        else:
            send_message(phone, f"✅ *Expense recorded!*\n\n💸 Amount: RM{expense['amount']}\n📦 Item: {expense['item']}\n\nType *MENU* for other options.")

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

    if t_upper in ["MENU", "HI", "HAI", "START"]:
        if lang == "bm":
            send_message(phone,
                f"📱 *Menu BizBuddy — {name}*\n\n"
                "1️⃣ Rekod Jualan Hari Ini\n"
                "2️⃣ Jana Skor Kredit Saya\n"
                "3️⃣ Tanya Soalan Perniagaan (AI)\n"
                "4️⃣ Hantar Gambar Resit/Bayaran\n"
                "5️⃣ Ringkasan Jualan Saya\n\n"
                "6️⃣ Jana Kandungan Media Sosial\n\n"
                "💡 Taip *PROFIL* untuk eksport profil\n"
                "💡 Taip *SIJIL* untuk sijil kredit\n"
                "💡 Taip *ENGLISH* untuk tukar bahasa\n"
                "💡 Taip *PINJAMAN* untuk semak kelayakan pinjaman\n\n"
                "_Balas dengan nombor pilihan_"
            )
        else:
            send_message(phone,
                f"📱 *BizBuddy Menu — {name}*\n\n"
                "1️⃣ Record Today's Sales\n"
                "2️⃣ Generate My Credit Score\n"
                "3️⃣ Ask Business Question (AI)\n"
                "4️⃣ Send Receipt/Payment Photo\n"
                "5️⃣ My Sales Summary\n\n"
                "6️⃣ Generate Social Media Content\n\n"
                "💡 Type *PROFILE* to export profile\n"
                "💡 Type *CERTIFICATE* for credit certificate\n"
                "💡 Type *BM* to switch to Bahasa Malaysia\n"
                "💡 Type *LOAN* to check loan eligibility\n\n"
                "_Reply with your choice number_"
            )
    elif t_upper == "1":
        user_ref.update({"state": "log_sale"})
        if lang == "bm":
            send_message(phone, "💰 *Rekod Jualan*\n\nCeritakan jualan awak hari ini.\n_(Contoh: Jual 10 bekas kuih dapat RM150)_")
        else:
            send_message(phone, "💰 *Record Sales*\n\nTell me about your sales today.\n_(Example: Sold 10 boxes of cookies for RM150)_")
    elif t_upper == "2":
        user_ref.update({"state": "credit_q1"})
        if lang == "bm":
            send_message(phone, "📊 *Jana Skor Kredit*\n\nSaya perlu tanya 3 soalan tambahan untuk skor yang lebih tepat.\n\nSoalan 1️⃣: Berapa lama perniagaan awak dah beroperasi?\n_(Contoh: 3 bulan, 1 tahun, 5 tahun)_")
        else:
            send_message(phone, "📊 *Generate Credit Score*\n\nI need to ask 3 additional questions for a more accurate score.\n\nQuestion 1️⃣: How long has your business been operating?\n_(Example: 3 months, 1 year, 5 years)_")
    elif t_upper == "3":
        user_ref.update({"state": "ai_chat"})
        if lang == "bm":
            send_message(phone, "🤖 *AI Penasihat Perniagaan*\n\nTanya apa sahaja! Contoh:\n• Macam mana nak tetapkan harga?\n• Macam mana nak mohon pinjaman TEKUN?\n• Macam mana nak promosi online?\n\n_(Taip MENU untuk kembali)_")
        else:
            send_message(phone, "🤖 *AI Business Advisor*\n\nAsk me anything! Examples:\n• How do I set my prices?\n• How do I apply for a TEKUN loan?\n• How do I promote online?\n\n_(Type MENU to go back)_")
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
        send_message(phone, f"✅ *Jualan direkod!*\n\n💵 Jumlah: RM{sale['amount']}\n📦 Item: {sale['item']}\n\nData ini disimpan untuk profil kredit awak 📊\nTaip *MENU* untuk kembali")
    else:
        send_message(phone, f"✅ *Sale recorded!*\n\n💵 Amount: RM{sale['amount']}\n📦 Item: {sale['item']}\n\nThis data is saved for your credit profile 📊\nType *MENU* to go back")

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
# CREDIT SCORE
# ─────────────────────────────────────
def generate_credit_score(phone, user_ref):
    user_data = user_ref.get().to_dict()
    sales = user_data.get("sales", [])
    total = sum(s.get("amount", 0) for s in sales)
    count = len(sales)
    lang = user_data.get("language", "bm")

    lang_instruction = "Bahasa Malaysia" if lang == "bm" else "English"
    prompt = f"""
    Generate a credit readiness score in {lang_instruction} for this entrepreneur:
    - Name: {user_data.get('owner_name')}
    - Business: {user_data.get('business_name')}
    - Product: {user_data.get('product')}
    - Reported income: {user_data.get('monthly_revenue')}
    - Total recorded sales: RM{total}
    - Number of transactions: {count}
    - Years in operation: {user_data.get('biz_age', 'Unknown')}
    - Has business bank account: {user_data.get('has_bank_account', 'Unknown')}
    - SSM registered: {user_data.get('has_ssm', 'Unknown')}

    Use EXACTLY this format, nothing else:
    SKOR: [number 0-100]
    TAHAP: [Rendah/Sederhana/Baik/Cemerlang]
    SEBAB: [1 sentence]
    LANGKAH 1: [improvement step]
    LANGKAH 2: [improvement step]
    LANGKAH 3: [improvement step]
    """
    response = client.models.generate_content(model=MODEL, contents=prompt)

    # Save score to Firebase
    score_text = response.text
    try:
        score_line = [l for l in score_text.split('\n') if l.startswith('SKOR:')][0]
        score_num = int(''.join(filter(str.isdigit, score_line)))
        user_ref.update({"credit_score": score_num, "score_date": str(datetime.now().date())})
    except:
        pass

    if lang == "bm":
        send_message(phone, f"📊 *Laporan Skor Kredit Awak*\n\n{response.text}\n\n💡 Rekod lebih banyak jualan untuk tingkatkan skor!\nTaip *SIJIL* untuk jana sijil kredit awak\nTaip *MENU* untuk kembali")
    else:
        send_message(phone, f"📊 *Your Credit Score Report*\n\n{response.text}\n\n💡 Record more sales to improve your score!\nType *CERTIFICATE* to generate your credit certificate\nType *MENU* to go back")

# ─────────────────────────────────────
# SALES SUMMARY
# ─────────────────────────────────────
def show_sales_summary(phone, user_ref):
    user_data = user_ref.get().to_dict()
    sales = user_data.get("sales", [])
    lang = user_data.get("language", "bm")

    if not sales:
        if lang == "bm":
            send_message(phone, "📊 *Ringkasan Jualan*\n\nAwak belum rekod sebarang jualan lagi.\nTaip *1* untuk rekod jualan pertama awak!\n\nTaip *MENU* untuk kembali")
        else:
            send_message(phone, "📊 *Sales Summary*\n\nYou haven't recorded any sales yet.\nType *1* to record your first sale!\n\nType *MENU* to go back")
        return

    total = sum(s.get("amount", 0) for s in sales)
    count = len(sales)
    average = total / count if count > 0 else 0
    best = max(s.get("amount", 0) for s in sales)

    recent = sales[-5:]
    recent_text = ""
    for s in reversed(recent):
        recent_text += f"• RM{s.get('amount', 0)} — {s.get('item', '-')} ({s.get('date', '-')})\n"

    if lang == "bm":
        send_message(phone,
            "📊 *Ringkasan Jualan Awak*\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"💵 Jumlah Keseluruhan: RM{total}\n"
            f"🔢 Jumlah Transaksi: {count}\n"
            f"📈 Purata Per Transaksi: RM{average:.0f}\n"
            f"🏆 Jualan Terbesar: RM{best}\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📋 *5 Transaksi Terkini:*\n{recent_text}\n"
            "Taip *MENU* untuk kembali"
        )
    else:
        send_message(phone,
            "📊 *Your Sales Summary*\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"💵 Total Revenue: RM{total}\n"
            f"🔢 Total Transactions: {count}\n"
            f"📈 Average Per Transaction: RM{average:.0f}\n"
            f"🏆 Biggest Sale: RM{best}\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📋 *Last 5 Transactions:*\n{recent_text}\n"
            "Type *MENU* to go back"
        )

# ─────────────────────────────────────
# EXPORT PROFILE
# ─────────────────────────────────────
def show_profile(phone, user_ref):
    user_data = user_ref.get().to_dict()
    lang = user_data.get("language", "bm")
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
            f"💵 Pendapatan Bulanan: {user_data.get('monthly_revenue', '-')}\n"
            f"⏱️ Lama Beroperasi: {user_data.get('biz_age', '-')}\n"
            f"🏦 Akaun Bank: {user_data.get('has_bank_account', '-')}\n"
            f"📝 SSM: {user_data.get('has_ssm', '-')}\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 Jumlah Jualan Direkod: RM{total}\n"
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
            f"💵 Monthly Income: {user_data.get('monthly_revenue', '-')}\n"
            f"⏱️ Years Operating: {user_data.get('biz_age', '-')}\n"
            f"🏦 Bank Account: {user_data.get('has_bank_account', '-')}\n"
            f"📝 SSM Registered: {user_data.get('has_ssm', '-')}\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 Total Recorded Sales: RM{total}\n"
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
# HANDLE IMAGE
# ─────────────────────────────────────
def handle_image(phone, image_id):
    user_ref = db.collection("users").document(phone)
    user_data = user_ref.get().to_dict() if user_ref.get().exists else {}
    lang = user_data.get("language", "bm")

    if lang == "bm":
        send_message(phone, "📸 Gambar diterima! Sedang menganalisis... ⏳")
    else:
        send_message(phone, "📸 Image received! Analyzing... ⏳")

    url = f"https://graph.facebook.com/v18.0/{image_id}"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
    media_info = requests.get(url, headers=headers).json()
    image_url = media_info.get("url", "")
    img_response = requests.get(image_url, headers=headers)

    import PIL.Image
    img = PIL.Image.open(BytesIO(img_response.content))

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
            send_message(phone, f"✅ *Bayaran direkod dari gambar!*\n\n💵 Jumlah: RM{data['amount']}\n📦 Item: {data.get('item', 'Jualan')}\n\nTaip *MENU* untuk kembali")
        else:
            send_message(phone, f"✅ *Payment recorded from image!*\n\n💵 Amount: RM{data['amount']}\n📦 Item: {data.get('item', 'Sale')}\n\nType *MENU* to go back")
    else:
        if lang == "bm":
            send_message(phone, "Saya tidak dapat mengesan bayaran dalam gambar ini.\nCuba hantar screenshot yang lebih jelas.\n\nTaip *MENU* untuk kembali")
        else:
            send_message(phone, "I could not detect a payment in this image.\nPlease send a clearer screenshot.\n\nType *MENU* to go back")

# ─────────────────────────────────────
# LOAN READINESS CHECKLIST
# ─────────────────────────────────────
def show_loan_checklist(phone, user_ref):
    user_data = user_ref.get().to_dict()
    lang = user_data.get("language", "bm")
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
         "Berdaftar SSM" if lang=="bm" else "SSM registered",
         "Daftar SSM di ssm.com.my" if lang=="bm" else "Register at ssm.com.my"),
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

    if pct == 100:
        status = "🎉 TAHNIAH! Awak layak mohon pinjaman TEKUN!" if lang=="bm" else "🎉 CONGRATULATIONS! You qualify for a TEKUN loan!"
    elif pct >= 70:
        status = f"🔥 Hampir layak! Siapkan {total-done} lagi syarat." if lang=="bm" else f"🔥 Almost there! Complete {total-done} more requirements."
    elif pct >= 40:
        status = f"💪 Dalam proses. Perlukan {total-done} lagi syarat." if lang=="bm" else f"💪 In progress. Need {total-done} more requirements."
    else:
        status = f"📈 Baru bermula. Perlukan {total-done} lagi syarat." if lang=="bm" else f"📈 Just starting. Need {total-done} more requirements."

    if lang == "bm":
        send_message(phone,
            "🏦 *SENARAI SEMAK PINJAMAN TEKUN*\n\n"
            f"Kemajuan: [{bar}] {pct}%\n"
            f"({done}/{total} syarat dipenuhi)\n\n"
            f"{lines}\n"
            f"{status}\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "💡 TEKUN loan: sehingga RM50,000\n"
            "💡 Faedah rendah: 4% setahun\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Taip *MENU* untuk kembali"
        )
    else:
        send_message(phone,
            "🏦 *TEKUN LOAN READINESS CHECKLIST*\n\n"
            f"Progress: [{bar}] {pct}%\n"
            f"({done}/{total} requirements met)\n\n"
            f"{lines}\n"
            f"{status}\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "💡 TEKUN loan: up to RM50,000\n"
            "💡 Low interest: 4% per year\n"
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
    app.run(port=5000, debug=True)