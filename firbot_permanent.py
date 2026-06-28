# firbot_permanent.py - FIR Bot with Gemini AI and QR Payment

import os
import logging
import json
import uuid
import re
from datetime import datetime
from pathlib import Path
import asyncio
import threading

# Web server for Render health checks
from flask import Flask, jsonify

# Telegram
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler, filters, ContextTypes
)
from telegram.constants import ParseMode

# QR Code
import qrcode
from PIL import Image, ImageDraw, ImageFont

# Google Gemini AI
import google.generativeai as genai

# Environment
from dotenv import load_dotenv

# Load environment
load_dotenv()

# ============================================================
# CONFIGURATION
# ============================================================

TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
PORT = int(os.environ.get('PORT', 10000))

if not TELEGRAM_TOKEN:
    print("❌ ERROR: TELEGRAM_TOKEN not found in .env file!")
    exit(1)

# Configure Gemini AI
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    gemini_model = genai.GenerativeModel('gemini-pro')
else:
    print("⚠️ WARNING: GEMINI_API_KEY not found.")
    gemini_model = None

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ============================================================
# UPI PAYMENT CONFIGURATION
# ============================================================

UPI_CONFIG = {
    'upi_id': 'ashishgpandey@ybl',
    'payee_name': 'Ashish Gaurav Pandey',
    'amount': 10,
    'currency': 'INR'
}

FIR_AMOUNT = 10

# ============================================================
# SIMPLE DATABASE
# ============================================================

class SimpleDB:
    def __init__(self, filename='fir_data.json'):
        self.filename = filename
        self.data = self.load()
    
    def load(self):
        if os.path.exists(self.filename):
            try:
                with open(self.filename, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                pass
        return {'firs': [], 'feedback': []}
    
    def save(self):
        with open(self.filename, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, indent=2, default=str, ensure_ascii=False)
    
    def add_fir(self, fir_data):
        fir_id = str(uuid.uuid4())[:8]
        fir_data['id'] = fir_id
        fir_data['fir_number'] = f"FIR{datetime.now().strftime('%Y%m%d')}{fir_id[:4].upper()}"
        fir_data['created_at'] = datetime.now().isoformat()
        fir_data['status'] = 'submitted'
        fir_data['payment_status'] = False
        self.data['firs'].append(fir_data)
        self.save()
        return fir_data
    
    def get_firs(self, user_id):
        return [f for f in self.data['firs'] if f.get('user_id') == user_id]
    
    def get_fir_by_number(self, fir_number):
        for f in self.data['firs']:
            if f.get('fir_number') == fir_number:
                return f
        return None
    
    def update_payment_status(self, fir_number, paid=True):
        for f in self.data['firs']:
            if f.get('fir_number') == fir_number:
                f['payment_status'] = paid
                if paid:
                    f['status'] = 'paid'
                self.save()
                return True
        return False
    
    def get_stats(self):
        total = len(self.data.get('firs', []))
        paid = len([f for f in self.data.get('firs', []) if f.get('payment_status')])
        return {'total': total, 'paid': paid}

db = SimpleDB()

# ============================================================
# FLASK WEB SERVER FOR RENDER
# ============================================================

flask_app = Flask(__name__)

@flask_app.route('/')
def health_check():
    return jsonify({
        'status': 'healthy',
        'bot': 'running',
        'time': datetime.now().isoformat()
    }), 200

def run_web_server():
    try:
        flask_app.run(host='0.0.0.0', port=PORT)
    except Exception as e:
        logger.error(f"Web server error: {e}")

# ============================================================
# CONVERSATION STATES
# ============================================================

SELECT_LANGUAGE, SELECT_PLAN, SELECT_INCIDENT_TYPE, GET_INCIDENT_DATE, \
GET_INCIDENT_LOCATION, GET_DESCRIPTION, GET_COMPLAINANT_NAME, GET_FATHER_NAME, \
GET_COMPLAINANT_PHONE, GET_COMPLAINANT_ADDRESS, GET_ACCUSED_DETAILS, \
GET_WITNESS_DETAILS, GET_EVIDENCE_DETAILS, SELECT_POLICE_STATION, CONFIRM_FIR, \
PROCESS_PAYMENT, PROVIDE_FEEDBACK, STATUS_CHECK = range(18)

# ============================================================
# TEXT DICTIONARY
# ============================================================

TEXTS = {
    'en': {
        'welcome': "🌟 Welcome to <b>LegalFIR Bot</b>!\n\nFile FIR for just ₹10!\n\nPlease select your language:",
        'language_selected': "✅ Language set to English.",
        'plan_selection': "📋 <b>Select Your Plan</b>\n\nBoth plans cost ₹10!",
        'incident_type': "📌 <b>Select Incident Type</b>:",
        'incident_date': "📅 <b>Enter incident date</b> (DD/MM/YYYY):",
        'incident_location': "📍 <b>Enter incident location</b>:",
        'description': "📝 <b>Describe the incident</b>:",
        'complainant_name': "👤 <b>Enter your full name</b>:",
        'father_name': "👨 <b>Enter your father's name</b>:",
        'complainant_phone': "📱 <b>Enter your phone number</b>:",
        'complainant_address': "🏠 <b>Enter your address</b>:",
        'accused_details': "👥 <b>Accused details</b> (type 'skip'):",
        'witness_details': "👀 <b>Witness details</b> (type 'skip'):",
        'evidence_details': "📎 <b>Evidence details</b> (type 'skip'):",
        'police_station': "🚔 <b>Select Police Station</b>:",
        'confirm_fir': "📄 <b>Review your FIR</b>:\n\n{details}\n\nProceed?",
        'payment_required': "💳 <b>Payment Required - ₹10!</b>\n\nAmount: ₹{amount}",
        'payment_success': "✅ <b>Payment Successful!</b>\n\nFIR Number: <code>{fir_number}</code>",
        'filing_success': "✅ <b>FIR Filed!</b>\n\nFIR Number: <code>{fir_number}</code>",
        'feedback': "📝 <b>Please provide your feedback</b>:",
        'feedback_thanks': "🙏 <b>Thank you!</b>",
        'error': "❌ <b>An error occurred</b>.",
        'cancel': "❌ Operation cancelled.",
        'help': "🤖 <b>Help</b>\n\nCommands:\n/start - Start\n/new_fir - File FIR (₹10)\n/status - Check status\n/list - Your FIRs\n/help - This help",
        'status_check': "📊 Enter your FIR number:",
        'status_response': "📊 <b>FIR Status</b>\n\nNumber: <code>{fir_number}</code>\nStatus: {status}",
        'list_response': "📋 <b>Your FIRs</b>\n\n{firs}",
        'no_firs': "📭 No FIRs found.",
        'invalid_fir': "❌ Invalid FIR number.",
        'payment_instructions': "📱 <b>Pay ₹10</b>\n\nUPI ID: <code>{upi_id}</code>",
    },
    'hi': {
        'welcome': "🌟 <b>लीगलFIR बॉट</b> में स्वागत है!\n\nसिर्फ ₹10 में FIR दर्ज करें!\n\nकृपया भाषा चुनें:",
        'language_selected': "✅ भाषा हिंदी में सेट।",
        'plan_selection': "📋 <b>प्लान चुनें</b>\n\nदोनों प्लान ₹10!",
        'incident_type': "📌 <b>घटना का प्रकार चुनें</b>:",
        'incident_date': "📅 <b>घटना की तारीख</b> (DD/MM/YYYY):",
        'incident_location': "📍 <b>घटना का स्थान</b>:",
        'description': "📝 <b>घटना का विवरण</b>:",
        'complainant_name': "👤 <b>अपना पूरा नाम</b>:",
        'father_name': "👨 <b>पिता का नाम</b>:",
        'complainant_phone': "📱 <b>फोन नंबर</b>:",
        'complainant_address': "🏠 <b>पता</b>:",
        'accused_details': "👥 <b>आरोपित व्यक्ति</b> ('skip'):",
        'witness_details': "👀 <b>गवाह</b> ('skip'):",
        'evidence_details': "📎 <b>साक्ष्य</b> ('skip'):",
        'police_station': "🚔 <b>पुलिस स्टेशन चुनें</b>:",
        'confirm_fir': "📄 <b>FIR की समीक्षा करें</b>:\n\n{details}\n\nआगे बढ़ें?",
        'payment_required': "💳 <b>भुगतान - ₹10!</b>\n\nराशि: ₹{amount}",
        'payment_success': "✅ <b>भुगतान सफल!</b>\n\nFIR नंबर: <code>{fir_number}</code>",
        'filing_success': "✅ <b>FIR दर्ज!</b>\n\nFIR नंबर: <code>{fir_number}</code>",
        'feedback': "📝 <b>अपनी प्रतिक्रिया दें</b>:",
        'feedback_thanks': "🙏 <b>धन्यवाद!</b>",
        'error': "❌ <b>त्रुटि</b>.",
        'cancel': "❌ रद्द।",
        'help': "🤖 <b>सहायता</b>\n\nकमांड:\n/start - शुरू करें\n/new_fir - FIR दर्ज करें (₹10)\n/status - स्थिति देखें\n/list - अपनी FIRs\n/help - सहायता",
        'status_check': "📊 FIR नंबर दर्ज करें:",
        'status_response': "📊 <b>FIR स्थिति</b>\n\nनंबर: <code>{fir_number}</code>\nस्थिति: {status}",
        'list_response': "📋 <b>आपकी FIRs</b>\n\n{firs}",
        'no_firs': "📭 कोई FIR नहीं।",
        'invalid_fir': "❌ अमान्य FIR नंबर।",
        'payment_instructions': "📱 <b>₹10 भुगतान</b>\n\nUPI ID: <code>{upi_id}</code>",
    }
}

INCIDENT_TYPES = {
    'theft': "🚨 Theft",
    'assault': "⚔️ Assault",
    'accident': "🚗 Accident",
    'cyber': "💻 Cyber Crime",
    'harassment': "🔞 Harassment",
    'other': "📝 Other"
}

POLICE_STATIONS = {
    'city': "🏛️ City Police Station",
    'town': "🏛️ Town Police Station",
    'cyber': "💻 Cyber Crime Cell"
}

# ============================================================
# COMMAND HANDLERS
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    context.user_data['user_id'] = str(user.id)
    
    keyboard = [
        [InlineKeyboardButton("🇬🇧 English", callback_data='lang_en')],
        [InlineKeyboardButton("🇮🇳 हिंदी", callback_data='lang_hi')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "🌍 Welcome!\n\nPlease select your language:\nकृपया अपनी भाषा चुनें:",
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )
    return SELECT_LANGUAGE

async def select_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    language = query.data.split('_')[1]
    context.user_data['language'] = language
    texts = TEXTS[language]
    
    keyboard = [
        [InlineKeyboardButton("👤 Individual - ₹10", callback_data='plan_individual')],
        [InlineKeyboardButton("⚖️ Advocate - ₹10", callback_data='plan_advocate')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        texts['language_selected'] + "\n\n" + texts['plan_selection'],
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )
    return SELECT_PLAN

async def select_plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    plan = query.data.split('_')[1]
    context.user_data['plan'] = plan
    language = context.user_data.get('language', 'en')
    texts = TEXTS[language]
    
    keyboard = []
    incident_types = INCIDENT_TYPES if language == 'en' else {
        'theft': "🚨 चोरी",
        'assault': "⚔️ हमला",
        'accident': "🚗 दुर्घटना",
        'cyber': "💻 साइबर क्राइम",
        'harassment': "🔞 उत्पीड़न",
        'other': "📝 अन्य"
    }
    context.user_data['incident_types'] = incident_types
    
    for key, value in incident_types.items():
        keyboard.append([InlineKeyboardButton(value, callback_data=f'type_{key}')])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        texts['incident_type'],
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )
    return SELECT_INCIDENT_TYPE

async def select_incident_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    context.user_data['incident_type'] = query.data.split('_')[1]
    language = context.user_data.get('language', 'en')
    texts = TEXTS[language]
    
    await query.edit_message_text(texts['incident_date'], parse_mode=ParseMode.HTML)
    return GET_INCIDENT_DATE

async def get_incident_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        date = datetime.strptime(update.message.text, '%d/%m/%Y')
        context.user_data['incident_date'] = date.strftime('%d/%m/%Y')
        language = context.user_data.get('language', 'en')
        texts = TEXTS[language]
        
        await update.message.reply_text(texts['incident_location'], parse_mode=ParseMode.HTML)
        return GET_INCIDENT_LOCATION
    except ValueError:
        await update.message.reply_text("❌ Invalid date. Use DD/MM/YYYY")
        return GET_INCIDENT_DATE

async def get_incident_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['incident_location'] = update.message.text
    language = context.user_data.get('language', 'en')
    texts = TEXTS[language]
    
    await update.message.reply_text(texts['description'], parse_mode=ParseMode.HTML)
    return GET_DESCRIPTION

async def get_description_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['description'] = update.message.text
    language = context.user_data.get('language', 'en')
    texts = TEXTS[language]
    
    await update.message.reply_text(texts['complainant_name'], parse_mode=ParseMode.HTML)
    return GET_COMPLAINANT_NAME

async def get_description_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📝 Please type your description instead.")
    return GET_DESCRIPTION

async def get_complainant_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['complainant_name'] = update.message.text
    language = context.user_data.get('language', 'en')
    texts = TEXTS[language]
    
    await update.message.reply_text(texts['father_name'], parse_mode=ParseMode.HTML)
    return GET_FATHER_NAME

async def get_father_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['father_name'] = update.message.text
    language = context.user_data.get('language', 'en')
    texts = TEXTS[language]
    
    await update.message.reply_text(texts['complainant_phone'], parse_mode=ParseMode.HTML)
    return GET_COMPLAINANT_PHONE

async def get_complainant_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text.strip()
    if not phone.isdigit() or len(phone) < 10:
        await update.message.reply_text("❌ Enter valid 10-digit phone number:")
        return GET_COMPLAINANT_PHONE
    
    context.user_data['complainant_phone'] = phone
    language = context.user_data.get('language', 'en')
    texts = TEXTS[language]
    
    await update.message.reply_text(texts['complainant_address'], parse_mode=ParseMode.HTML)
    return GET_COMPLAINANT_ADDRESS

async def get_complainant_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['complainant_address'] = update.message.text
    language = context.user_data.get('language', 'en')
    texts = TEXTS[language]
    
    await update.message.reply_text(texts['accused_details'], parse_mode=ParseMode.HTML)
    return GET_ACCUSED_DETAILS

async def get_accused_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['accused_details'] = update.message.text
    language = context.user_data.get('language', 'en')
    texts = TEXTS[language]
    
    await update.message.reply_text(texts['witness_details'], parse_mode=ParseMode.HTML)
    return GET_WITNESS_DETAILS

async def get_witness_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['witness_details'] = update.message.text
    language = context.user_data.get('language', 'en')
    texts = TEXTS[language]
    
    await update.message.reply_text(texts['evidence_details'], parse_mode=ParseMode.HTML)
    return GET_EVIDENCE_DETAILS

async def get_evidence_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['evidence_details'] = update.message.text
    language = context.user_data.get('language', 'en')
    texts = TEXTS[language]
    
    keyboard = []
    police_stations = POLICE_STATIONS if language == 'en' else {
        'city': "🏛️ शहर पुलिस स्टेशन",
        'town': "🏛️ कस्बा पुलिस स्टेशन",
        'cyber': "💻 साइबर सेल"
    }
    for key, value in police_stations.items():
        keyboard.append([InlineKeyboardButton(value, callback_data=f'station_{key}')])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        texts['police_station'],
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )
    return SELECT_POLICE_STATION

async def select_police_station(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    station = query.data.split('_')[1]
    context.user_data['police_station'] = station
    language = context.user_data.get('language', 'en')
    texts = TEXTS[language]
    
    details = f"""
<b>Plan:</b> {context.user_data.get('plan', 'N/A')} - ₹10
<b>Type:</b> {context.user_data.get('incident_type', 'N/A')}
<b>Date:</b> {context.user_data.get('incident_date', 'N/A')}
<b>Location:</b> {context.user_data.get('incident_location', 'N/A')}

<b>Complainant:</b>
Name: {context.user_data.get('complainant_name', 'N/A')}
Father: {context.user_data.get('father_name', 'N/A')}
Phone: {context.user_data.get('complainant_phone', 'N/A')}
Address: {context.user_data.get('complainant_address', 'N/A')}
    """
    
    keyboard = [
        [InlineKeyboardButton("✅ Yes", callback_data='confirm_yes')],
        [InlineKeyboardButton("❌ No", callback_data='confirm_no')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        texts['confirm_fir'].format(details=details),
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )
    return CONFIRM_FIR

async def confirm_fir(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == 'confirm_yes':
        language = context.user_data.get('language', 'en')
        texts = TEXTS[language]
        
        fir_data = {
            'user_id': context.user_data['user_id'],
            'plan': context.user_data.get('plan', 'individual'),
            'incident_type': context.user_data.get('incident_type'),
            'incident_date': context.user_data.get('incident_date'),
            'incident_location': context.user_data.get('incident_location'),
            'description': context.user_data.get('description'),
            'complainant_name': context.user_data.get('complainant_name'),
            'father_name': context.user_data.get('father_name'),
            'complainant_phone': context.user_data.get('complainant_phone'),
            'complainant_address': context.user_data.get('complainant_address'),
            'accused_details': context.user_data.get('accused_details', 'N/A'),
            'witness_details': context.user_data.get('witness_details', 'N/A'),
            'evidence_details': context.user_data.get('evidence_details', 'N/A'),
            'police_station': context.user_data.get('police_station')
        }
        
        saved_fir = db.add_fir(fir_data)
        context.user_data['fir_number'] = saved_fir['fir_number']
        
        keyboard = [
            [InlineKeyboardButton("✅ Pay ₹10", callback_data=f'payment_{saved_fir["fir_number"]}')],
            [InlineKeyboardButton("⏭️ Skip", callback_data=f'payment_skip_{saved_fir["fir_number"]}')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            texts['payment_required'].format(amount=FIR_AMOUNT),
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML
        )
        return PROCESS_PAYMENT
    else:
        await query.edit_message_text("❌ Cancelled.")
        return ConversationHandler.END

async def process_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    language = context.user_data.get('language', 'en')
    texts = TEXTS[language]
    
    parts = query.data.split('_')
    fir_number = parts[1]
    action = parts[0]
    
    if action == 'payment_skip':
        db.update_payment_status(fir_number, True)
        fir = db.get_fir_by_number(fir_number)
        
        await query.edit_message_text(
            texts['payment_success'].format(fir_number=fir_number),
            parse_mode=ParseMode.HTML
        )
        
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=texts['filing_success'].format(fir_number=fir_number),
            parse_mode=ParseMode.HTML
        )
        
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=texts['feedback'],
            parse_mode=ParseMode.HTML
        )
        return PROVIDE_FEEDBACK
    
    else:
        await query.edit_message_text(
            texts['payment_instructions'].format(upi_id=UPI_CONFIG['upi_id']),
            parse_mode=ParseMode.HTML
        )
        
        keyboard = [
            [InlineKeyboardButton("✅ I've Paid", callback_data=f'verify_{fir_number}')],
            [InlineKeyboardButton("❌ Cancel", callback_data=f'payment_cancel_{fir_number}')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="After payment, click 'I've Paid'.",
            reply_markup=reply_markup
        )
        return PROCESS_PAYMENT

async def provide_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    feedback = update.message.text
    language = context.user_data.get('language', 'en')
    texts = TEXTS[language]
    
    db.data['feedback'].append({
        'user_id': str(update.effective_user.id),
        'feedback': feedback,
        'created_at': datetime.now().isoformat()
    })
    db.save()
    
    await update.message.reply_text(texts['feedback_thanks'], parse_mode=ParseMode.HTML)
    return ConversationHandler.END

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    language = context.user_data.get('language', 'en')
    texts = TEXTS[language]
    
    await update.message.reply_text(texts['status_check'], parse_mode=ParseMode.HTML)
    return STATUS_CHECK

async def status_check_response(update: Update, context: ContextTypes.DEFAULT_TYPE):
    fir_number = update.message.text.strip().upper()
    language = context.user_data.get('language', 'en')
    texts = TEXTS[language]
    
    fir = db.get_fir_by_number(fir_number)
    
    if fir:
        await update.message.reply_text(
            texts['status_response'].format(
                fir_number=fir_number,
                status=fir.get('status', 'Unknown')
            ),
            parse_mode=ParseMode.HTML
        )
    else:
        await update.message.reply_text(texts['invalid_fir'], parse_mode=ParseMode.HTML)
    
    return ConversationHandler.END

async def list_firs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    language = context.user_data.get('language', 'en')
    texts = TEXTS[language]
    
    firs = db.get_firs(user_id)
    
    if firs:
        message = ""
        for i, fir in enumerate(firs, 1):
            status_icon = "✅" if fir.get('payment_status') else "⏳"
            message += f"{i}. {status_icon} <code>{fir['fir_number']}</code>\n"
            message += f"   Status: {fir.get('status', 'N/A')}\n\n"
        
        await update.message.reply_text(
            texts['list_response'].format(firs=message),
            parse_mode=ParseMode.HTML
        )
    else:
        await update.message.reply_text(texts['no_firs'], parse_mode=ParseMode.HTML)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    language = context.user_data.get('language', 'en')
    texts = TEXTS[language]
    await update.message.reply_text(texts['help'], parse_mode=ParseMode.HTML)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    language = context.user_data.get('language', 'en')
    texts = TEXTS[language]
    await update.message.reply_text(texts['cancel'], parse_mode=ParseMode.HTML)
    return ConversationHandler.END

async def new_fir_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await start(update, context)

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update {update} caused error {context.error}")
    if update and update.message:
        language = context.user_data.get('language', 'en')
        texts = TEXTS[language]
        await update.message.reply_text(texts['error'], parse_mode=ParseMode.HTML)

# ============================================================
# MAIN FUNCTION
# ============================================================

def main():
    print("=" * 60)
    print("🤖 FIR BOT WITH GEMINI AI")
    print("=" * 60)
    print(f"✅ Bot Token: {TELEGRAM_TOKEN[:15]}...")
    print(f"✅ UPI ID: {UPI_CONFIG['upi_id']}")
    print(f"✅ Amount: ₹{FIR_AMOUNT}")
    print(f"✅ Gemini AI: {'Enabled' if gemini_model else 'Disabled'}")
    print("=" * 60)
    print("✅ Bot is running...")
    print("=" * 60)
    
    # Start web server
    web_thread = threading.Thread(target=run_web_server, daemon=True)
    web_thread.start()
    
    # Create application
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler('start', start),
            CommandHandler('new_fir', new_fir_command),
        ],
        states={
            SELECT_LANGUAGE: [CallbackQueryHandler(select_language)],
            SELECT_PLAN: [CallbackQueryHandler(select_plan)],
            SELECT_INCIDENT_TYPE: [CallbackQueryHandler(select_incident_type)],
            GET_INCIDENT_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_incident_date)],
            GET_INCIDENT_LOCATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_incident_location)],
            GET_DESCRIPTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_description_text),
                MessageHandler(filters.VOICE, get_description_voice),
            ],
            GET_COMPLAINANT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_complainant_name)],
            GET_FATHER_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_father_name)],
            GET_COMPLAINANT_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_complainant_phone)],
            GET_COMPLAINANT_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_complainant_address)],
            GET_ACCUSED_DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_accused_details)],
            GET_WITNESS_DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_witness_details)],
            GET_EVIDENCE_DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_evidence_details)],
            SELECT_POLICE_STATION: [CallbackQueryHandler(select_police_station)],
            CONFIRM_FIR: [CallbackQueryHandler(confirm_fir)],
            PROCESS_PAYMENT: [CallbackQueryHandler(process_payment_callback)],
            PROVIDE_FEEDBACK: [MessageHandler(filters.TEXT & ~filters.COMMAND, provide_feedback)],
            STATUS_CHECK: [MessageHandler(filters.TEXT & ~filters.COMMAND, status_check_response)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
        per_message=False
    )
    
    application.add_handler(conv_handler)
    application.add_handler(CommandHandler('status', status_command))
    application.add_handler(CommandHandler('list', list_firs))
    application.add_handler(CommandHandler('help', help_command))
    application.add_handler(CommandHandler('new_fir', new_fir_command))
    application.add_error_handler(error_handler)
    
    try:
        application.run_polling()
    except Exception as e:
        logger.error(f"Bot error: {e}")
        while True:
            import time
            time.sleep(60)

if __name__ == '__main__':
    main()