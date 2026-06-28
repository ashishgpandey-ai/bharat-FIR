# firbot.py - Complete Working Version with All Features

import os
import logging
import json
import uuid
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

# Telegram
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler, filters, ContextTypes
)
from telegram.constants import ParseMode

# Environment
from dotenv import load_dotenv

# Load environment
load_dotenv()

# ============================================================
# CONFIGURATION
# ============================================================

TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')

if not TELEGRAM_TOKEN:
    print("❌ ERROR: TELEGRAM_TOKEN not found in .env file!")
    print("Please create .env file with:")
    print("TELEGRAM_TOKEN=your_bot_token_here")
    exit(1)

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ============================================================
# SIMPLE DATABASE (JSON based - no SQL needed)
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
                return {'firs': [], 'users': {}, 'feedback': []}
        return {'firs': [], 'users': {}, 'feedback': []}
    
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
    
    def get_fir_by_id(self, fir_id):
        for f in self.data['firs']:
            if f.get('id') == fir_id:
                return f
        return None
    
    def update_fir_status(self, fir_number, status):
        for f in self.data['firs']:
            if f.get('fir_number') == fir_number:
                f['status'] = status
                self.save()
                return True
        return False
    
    def update_payment_status(self, fir_number, paid=True):
        for f in self.data['firs']:
            if f.get('fir_number') == fir_number:
                f['payment_status'] = paid
                if paid:
                    f['status'] = 'paid'
                self.save()
                return True
        return False
    
    def add_feedback(self, user_id, feedback):
        self.data['feedback'].append({
            'user_id': user_id,
            'feedback': feedback,
            'created_at': datetime.now().isoformat()
        })
        self.save()
    
    def get_all_firs(self):
        return self.data['firs']
    
    def get_stats(self):
        total = len(self.data['firs'])
        paid = len([f for f in self.data['firs'] if f.get('payment_status')])
        pending = len([f for f in self.data['firs'] if f.get('status') == 'submitted'])
        return {'total': total, 'paid': paid, 'pending': pending}

# Initialize database
db = SimpleDB()

# ============================================================
# CONVERSATION STATES
# ============================================================

(
    SELECT_LANGUAGE,
    SELECT_PLAN,
    SELECT_INCIDENT_TYPE,
    GET_INCIDENT_DATE,
    GET_INCIDENT_LOCATION,
    GET_DESCRIPTION,
    GET_COMPLAINANT_NAME,
    GET_COMPLAINANT_PHONE,
    GET_COMPLAINANT_ADDRESS,
    GET_ACCUSED_DETAILS,
    GET_WITNESS_DETAILS,
    GET_EVIDENCE_DETAILS,
    SELECT_POLICE_STATION,
    CONFIRM_FIR,
    PROCESS_PAYMENT,
    PROVIDE_FEEDBACK,
    STATUS_CHECK,
    DOWNLOAD_FIR,
    ADMIN_MENU,
    ADMIN_VIEW_FIR,
    ADMIN_UPDATE_STATUS
) = range(21)

# ============================================================
# MULTI-LANGUAGE TEXTS
# ============================================================

TEXTS = {
    'en': {
        'welcome': "🌟 Welcome to <b>LegalFIR Bot</b>!\n\nI'll help you file an FIR (First Information Report) quickly and legally.\n\nPlease select your language:",
        'language_selected': "✅ Language set to English.",
        'plan_selection': "📋 <b>Select Your Plan</b>\n\n🔹 <b>Individual Plan</b> - ₹500\n• Basic FIR drafting\n• PDF download\n• Email copy\n\n🔹 <b>Advocate Plan</b> - ₹1500\n• Professional FIR drafting\n• Legal review by advocate\n• Application to SHO\n• PDF with stamp\n• Priority processing",
        'incident_type': "📌 <b>Select Incident Type</b>:",
        'incident_date': "📅 <b>Enter incident date</b> (DD/MM/YYYY):",
        'incident_location': "📍 <b>Enter incident location</b> (address, city):",
        'description': "📝 <b>Describe the incident in detail</b>:\n\nYou can type or send a voice message.",
        'complainant_name': "👤 <b>Enter your full name</b> (as per ID proof):",
        'complainant_phone': "📱 <b>Enter your phone number</b> (10 digits):",
        'complainant_address': "🏠 <b>Enter your complete address</b>:",
        'accused_details': "👥 <b>Provide details of accused persons</b> (type 'skip' if not known):",
        'witness_details': "👀 <b>Provide witness details</b> (type 'skip' if none):",
        'evidence_details': "📎 <b>Describe any evidence you have</b> (type 'skip' if none):",
        'police_station': "🚔 <b>Select Police Station</b>:",
        'confirm_fir': "📄 <b>Please review your FIR details</b>:\n\n{details}\n\nDo you want to proceed?",
        'payment_required': "💳 <b>Payment Required</b>\n\nAmount: ₹{amount}\nPlan: {plan}\n\nPlease complete the payment:",
        'payment_success': "✅ <b>Payment Successful!</b>\n\nFIR Number: <code>{fir_number}</code>\nStatus: {status}",
        'payment_failed': "❌ Payment failed. Please try again.",
        'filing_success': "✅ <b>FIR Filed Successfully!</b>\n\nFIR Number: <code>{fir_number}</code>\nStatus: {status}\n\nUse /status to check updates.",
        'feedback': "📝 <b>Please provide your feedback</b> about our service:",
        'feedback_thanks': "🙏 <b>Thank you for your feedback!</b>",
        'error': "❌ <b>An error occurred</b>. Please try again.",
        'cancel': "❌ Operation cancelled.",
        'help': "🤖 <b>LegalFIR Bot Help</b>\n\n<i>Commands:</i>\n/start - Start the bot\n/new_fir - File a new FIR\n/status - Check FIR status\n/list - List all your FIRs\n/help - Show this help\n/cancel - Cancel current operation\n/support - Contact support\n/feedback - Give feedback",
        'status_check': "📊 Enter your FIR number to check status:",
        'status_response': "📊 <b>FIR Status</b>\n\nNumber: <code>{fir_number}</code>\nStatus: {status}\nDate: {date}\nPlan: {plan}",
        'list_response': "📋 <b>Your FIRs</b>\n\n{firs}",
        'no_firs': "📭 You haven't filed any FIRs yet.\n\nSend /new_fir to get started!",
        'support': "📞 <b>Support</b>\n\nEmail: support@legalfir.com\nPhone: +91-XXXXXXXXXX\n\nHours: 9:00 AM - 6:00 PM IST",
        'invalid_fir': "❌ Invalid FIR number. Please check and try again.",
        'already_exists': "⚠️ You already have a pending FIR. Please wait for it to be processed.",
        'download_instructions': "📥 Enter FIR number to download PDF:",
        'download_success': "📄 Here's your FIR PDF:",
        'admin_welcome': "🔐 <b>Admin Panel</b>\n\nSelect an option:",
        'admin_stats': "📊 <b>Statistics</b>\n\nTotal FIRs: {total}\nPaid: {paid}\nPending: {pending}",
        'admin_list': "📋 <b>All FIRs</b>\n\n{firs}",
        'admin_update_status': "Update status for FIR <code>{fir_number}</code>:\n\nCurrent status: {status}",
        'admin_status_updated': "✅ Status updated to: {status}",
        'admin_no_firs': "No FIRs found.",
        'admin_back': "🔙 Back to Admin Menu",
    },
    'hi': {
        'welcome': "🌟 <b>लीगलFIR बॉट</b> में आपका स्वागत है!\n\nमैं आपको FIR (प्रथम सूचना रिपोर्ट) दर्ज करने में मदद करूंगा।\n\nकृपया अपनी भाषा चुनें:",
        'language_selected': "✅ भाषा हिंदी में सेट की गई।",
        'plan_selection': "📋 <b>अपना प्लान चुनें</b>\n\n🔹 <b>व्यक्तिगत प्लान</b> - ₹500\n• बुनियादी FIR\n• PDF डाउनलोड\n\n🔹 <b>अधिवक्ता प्लान</b> - ₹1500\n• व्यावसायिक FIR\n• कानूनी समीक्षा\n• SHO को आवेदन",
        'incident_type': "📌 <b>घटना का प्रकार चुनें</b>:",
        'incident_date': "📅 <b>घटना की तारीख दर्ज करें</b> (DD/MM/YYYY):",
        'incident_location': "📍 <b>घटना का स्थान दर्ज करें</b> (पता, शहर):",
        'description': "📝 <b>घटना का विवरण दें</b>:\n\nआप टाइप कर सकते हैं या वॉइस मैसेज भेज सकते हैं।",
        'complainant_name': "👤 <b>अपना पूरा नाम दर्ज करें</b> (जैसा ID पर है):",
        'complainant_phone': "📱 <b>अपना फोन नंबर दर्ज करें</b> (10 अंक):",
        'complainant_address': "🏠 <b>अपना पूरा पता दर्ज करें</b>:",
        'accused_details': "👥 <b>आरोपित व्यक्तियों का विवरण दें</b> ('skip' टाइप करें यदि नहीं ज्ञात):",
        'witness_details': "👀 <b>गवाहों का विवरण दें</b> ('skip' टाइप करें यदि कोई नहीं):",
        'evidence_details': "📎 <b>साक्ष्यों का विवरण दें</b> ('skip' टाइप करें यदि कोई नहीं):",
        'police_station': "🚔 <b>पुलिस स्टेशन चुनें</b>:",
        'confirm_fir': "📄 <b>कृपया अपने FIR की समीक्षा करें</b>:\n\n{details}\n\nक्या आप आगे बढ़ना चाहते हैं?",
        'payment_required': "💳 <b>भुगतान आवश्यक</b>\n\nराशि: ₹{amount}\nप्लान: {plan}",
        'payment_success': "✅ <b>भुगतान सफल!</b>\n\nFIR नंबर: <code>{fir_number}</code>\nस्थिति: {status}",
        'payment_failed': "❌ भुगतान विफल। कृपया पुनः प्रयास करें।",
        'filing_success': "✅ <b>FIR सफलतापूर्वक दर्ज!</b>\n\nFIR नंबर: <code>{fir_number}</code>\nस्थिति: {status}",
        'feedback': "📝 <b>कृपया अपनी प्रतिक्रिया दें</b> हमारी सेवा के बारे में:",
        'feedback_thanks': "🙏 <b>आपकी प्रतिक्रिया के लिए धन्यवाद!</b>",
        'error': "❌ <b>कोई त्रुटि हुई</b>. कृपया पुनः प्रयास करें।",
        'cancel': "❌ ऑपरेशन रद्द कर दिया गया।",
        'help': "🤖 <b>लीगलFIR बॉट सहायता</b>\n\n<i>कमांड:</i>\n/start - बॉट शुरू करें\n/new_fir - नई FIR दर्ज करें\n/status - FIR स्थिति देखें\n/list - अपनी FIRs देखें\n/help - यह सहायता\n/cancel - ऑपरेशन रद्द करें\n/support - सहायता से संपर्क करें\n/feedback - प्रतिक्रिया दें",
        'status_check': "📊 स्थिति देखने के लिए FIR नंबर दर्ज करें:",
        'status_response': "📊 <b>FIR स्थिति</b>\n\nनंबर: <code>{fir_number}</code>\nस्थिति: {status}\nतारीख: {date}\nप्लान: {plan}",
        'list_response': "📋 <b>आपकी FIRs</b>\n\n{firs}",
        'no_firs': "📭 आपने अभी तक कोई FIR दर्ज नहीं करवाई है।",
        'support': "📞 <b>सहायता</b>\n\nईमेल: support@legalfir.com\nफोन: +91-XXXXXXXXXX",
        'invalid_fir': "❌ अमान्य FIR नंबर। कृपया जांच करें।",
        'already_exists': "⚠️ आपकी पहले से एक लंबित FIR है।",
        'download_instructions': "📥 PDF डाउनलोड करने के लिए FIR नंबर दर्ज करें:",
        'download_success': "📄 आपका FIR PDF:",
        'admin_welcome': "🔐 <b>एडमिन पैनल</b>\n\nएक विकल्प चुनें:",
        'admin_stats': "📊 <b>आंकड़े</b>\n\nकुल FIR: {total}\nभुगतान: {paid}\nलंबित: {pending}",
        'admin_list': "📋 <b>सभी FIRs</b>\n\n{firs}",
        'admin_update_status': "FIR <code>{fir_number}</code> के लिए स्थिति अपडेट करें:\n\nवर्तमान स्थिति: {status}",
        'admin_status_updated': "✅ स्थिति अपडेट की गई: {status}",
        'admin_no_firs': "कोई FIR नहीं मिली।",
        'admin_back': "🔙 एडमिन मेनू पर वापस",
    }
}

# Incident types
INCIDENT_TYPES = {
    'theft': "🚨 Theft",
    'robbery': "🔫 Robbery", 
    'assault': "⚔️ Assault",
    'accident': "🚗 Accident",
    'property': "🏠 Property Dispute",
    'cyber': "💻 Cyber Crime",
    'harassment': "🔞 Harassment",
    'fraud': "💰 Fraud",
    'missing': "🔍 Missing Person",
    'other': "📝 Other"
}

POLICE_STATIONS = {
    'city': "🏛️ City Police Station",
    'town': "🏛️ Town Police Station",
    'rural': "🏛️ Rural Police Station",
    'cyber': "💻 Cyber Crime Cell",
    'women': "👩 Women's Police Station"
}

# ============================================================
# COMMAND HANDLERS
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command"""
    user = update.effective_user
    context.user_data['user_id'] = str(user.id)
    context.user_data['username'] = user.username or "User"
    
    keyboard = [
        [InlineKeyboardButton("🇬🇧 English", callback_data='lang_en')],
        [InlineKeyboardButton("🇮🇳 हिंदी", callback_data='lang_hi')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "🌍 Welcome to LegalFIR Bot!\n\nPlease select your language:\nकृपया अपनी भाषा चुनें:",
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )
    return SELECT_LANGUAGE

async def select_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle language selection"""
    query = update.callback_query
    await query.answer()
    
    language = query.data.split('_')[1]
    context.user_data['language'] = language
    texts = TEXTS[language]
    
    # Incident types in selected language
    if language == 'hi':
        incident_types = {
            'theft': "🚨 चोरी",
            'robbery': "🔫 डकैती",
            'assault': "⚔️ हमला",
            'accident': "🚗 दुर्घटना",
            'property': "🏠 संपत्ति विवाद",
            'cyber': "💻 साइबर क्राइम",
            'harassment': "🔞 उत्पीड़न",
            'fraud': "💰 धोखाधड़ी",
            'missing': "🔍 लापता व्यक्ति",
            'other': "📝 अन्य"
        }
    else:
        incident_types = INCIDENT_TYPES
    
    context.user_data['incident_types'] = incident_types
    
    keyboard = [
        [InlineKeyboardButton("👤 Individual - ₹500", callback_data='plan_individual')],
        [InlineKeyboardButton("⚖️ Advocate - ₹1500", callback_data='plan_advocate')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        texts['language_selected'] + "\n\n" + texts['plan_selection'],
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )
    return SELECT_PLAN

async def select_plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle plan selection"""
    query = update.callback_query
    await query.answer()
    
    plan = query.data.split('_')[1]
    context.user_data['plan'] = plan
    language = context.user_data.get('language', 'en')
    texts = TEXTS[language]
    
    # Show incident types
    keyboard = []
    incident_types = context.user_data.get('incident_types', INCIDENT_TYPES)
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
    """Handle incident type selection"""
    query = update.callback_query
    await query.answer()
    
    incident_type = query.data.split('_')[1]
    context.user_data['incident_type'] = incident_type
    language = context.user_data.get('language', 'en')
    texts = TEXTS[language]
    
    await query.edit_message_text(
        texts['incident_date'],
        parse_mode=ParseMode.HTML
    )
    return GET_INCIDENT_DATE

async def get_incident_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get incident date"""
    try:
        date = datetime.strptime(update.message.text, '%d/%m/%Y')
        context.user_data['incident_date'] = date.strftime('%d/%m/%Y')
        language = context.user_data.get('language', 'en')
        texts = TEXTS[language]
        
        await update.message.reply_text(
            texts['incident_location'],
            parse_mode=ParseMode.HTML
        )
        return GET_INCIDENT_LOCATION
    except ValueError:
        await update.message.reply_text("❌ Invalid date format. Please use DD/MM/YYYY")
        return GET_INCIDENT_DATE

async def get_incident_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get incident location"""
    context.user_data['incident_location'] = update.message.text
    language = context.user_data.get('language', 'en')
    texts = TEXTS[language]
    
    await update.message.reply_text(
        texts['description'],
        parse_mode=ParseMode.HTML
    )
    return GET_DESCRIPTION

async def get_description_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get description via text"""
    context.user_data['description'] = update.message.text
    language = context.user_data.get('language', 'en')
    texts = TEXTS[language]
    
    await update.message.reply_text(
        texts['complainant_name'],
        parse_mode=ParseMode.HTML
    )
    return GET_COMPLAINANT_NAME

async def get_description_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get description via voice"""
    try:
        # Download voice
        voice = await update.message.voice.get_file()
        voice_path = f"voice_{update.message.message_id}.ogg"
        await voice.download_to_drive(voice_path)
        
        # Try to recognize (optional)
        try:
            from pydub import AudioSegment
            import speech_recognition as sr
            
            # Convert to wav
            audio = AudioSegment.from_ogg(voice_path)
            wav_path = voice_path.replace('.ogg', '.wav')
            audio.export(wav_path, format='wav')
            
            recognizer = sr.Recognizer()
            with sr.AudioFile(wav_path) as source:
                audio_data = recognizer.record(source)
                text = recognizer.recognize_google(audio_data)
            
            context.user_data['description'] = text
            
            # Cleanup
            for f in [voice_path, wav_path]:
                if os.path.exists(f):
                    os.remove(f)
            
            await update.message.reply_text(f"📝 Recognized: {text}")
            
        except:
            # If recognition fails, ask to type
            await update.message.reply_text("❌ Could not recognize voice. Please type your description:")
            return GET_DESCRIPTION
        
        language = context.user_data.get('language', 'en')
        texts = TEXTS[language]
        await update.message.reply_text(
            texts['complainant_name'],
            parse_mode=ParseMode.HTML
        )
        return GET_COMPLAINANT_NAME
        
    except Exception as e:
        logger.error(f"Voice error: {e}")
        await update.message.reply_text("❌ Voice error. Please type your description:")
        return GET_DESCRIPTION

async def get_complainant_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get complainant name"""
    context.user_data['complainant_name'] = update.message.text
    language = context.user_data.get('language', 'en')
    texts = TEXTS[language]
    
    await update.message.reply_text(
        texts['complainant_phone'],
        parse_mode=ParseMode.HTML
    )
    return GET_COMPLAINANT_PHONE

async def get_complainant_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get complainant phone"""
    phone = update.message.text.strip()
    # Basic validation
    if not phone.isdigit() or len(phone) < 10:
        await update.message.reply_text("❌ Please enter a valid 10-digit phone number:")
        return GET_COMPLAINANT_PHONE
    
    context.user_data['complainant_phone'] = phone
    language = context.user_data.get('language', 'en')
    texts = TEXTS[language]
    
    await update.message.reply_text(
        texts['complainant_address'],
        parse_mode=ParseMode.HTML
    )
    return GET_COMPLAINANT_ADDRESS

async def get_complainant_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get complainant address"""
    context.user_data['complainant_address'] = update.message.text
    language = context.user_data.get('language', 'en')
    texts = TEXTS[language]
    
    await update.message.reply_text(
        texts['accused_details'],
        parse_mode=ParseMode.HTML
    )
    return GET_ACCUSED_DETAILS

async def get_accused_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get accused details"""
    context.user_data['accused_details'] = update.message.text
    language = context.user_data.get('language', 'en')
    texts = TEXTS[language]
    
    await update.message.reply_text(
        texts['witness_details'],
        parse_mode=ParseMode.HTML
    )
    return GET_WITNESS_DETAILS

async def get_witness_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get witness details"""
    context.user_data['witness_details'] = update.message.text
    language = context.user_data.get('language', 'en')
    texts = TEXTS[language]
    
    await update.message.reply_text(
        texts['evidence_details'],
        parse_mode=ParseMode.HTML
    )
    return GET_EVIDENCE_DETAILS

async def get_evidence_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get evidence details"""
    context.user_data['evidence_details'] = update.message.text
    language = context.user_data.get('language', 'en')
    texts = TEXTS[language]
    
    # Police stations
    keyboard = []
    for key, value in POLICE_STATIONS.items():
        keyboard.append([InlineKeyboardButton(value, callback_data=f'station_{key}')])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        texts['police_station'],
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )
    return SELECT_POLICE_STATION

async def select_police_station(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle police station selection"""
    query = update.callback_query
    await query.answer()
    
    station = query.data.split('_')[1]
    context.user_data['police_station'] = station
    language = context.user_data.get('language', 'en')
    texts = TEXTS[language]
    
    # Generate summary
    incident_type = context.user_data.get('incident_type', 'N/A')
    incident_types = context.user_data.get('incident_types', INCIDENT_TYPES)
    incident_label = incident_types.get(incident_type, incident_type)
    
    details = f"""
<b>Plan:</b> {context.user_data.get('plan', 'N/A')}
<b>Type:</b> {incident_label}
<b>Date:</b> {context.user_data.get('incident_date', 'N/A')}
<b>Location:</b> {context.user_data.get('incident_location', 'N/A')}

<b>Complainant:</b>
Name: {context.user_data.get('complainant_name', 'N/A')}
Phone: {context.user_data.get('complainant_phone', 'N/A')}
Address: {context.user_data.get('complainant_address', 'N/A')}

<b>Accused:</b> {context.user_data.get('accused_details', 'N/A')}
<b>Witnesses:</b> {context.user_data.get('witness_details', 'N/A')}
<b>Evidence:</b> {context.user_data.get('evidence_details', 'N/A')}
<b>Police Station:</b> {POLICE_STATIONS.get(station, station)}

<b>Description:</b>
{context.user_data.get('description', 'N/A')[:200]}...
    """
    
    keyboard = [
        [InlineKeyboardButton("✅ Yes, Proceed", callback_data='confirm_yes')],
        [InlineKeyboardButton("❌ No, Cancel", callback_data='confirm_no')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        texts['confirm_fir'].format(details=details),
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )
    return CONFIRM_FIR

async def confirm_fir(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle FIR confirmation"""
    query = update.callback_query
    await query.answer()
    
    if query.data == 'confirm_yes':
        language = context.user_data.get('language', 'en')
        texts = TEXTS[language]
        
        # Prepare FIR data
        fir_data = {
            'user_id': context.user_data['user_id'],
            'username': context.user_data.get('username', ''),
            'language': language,
            'plan': context.user_data.get('plan', 'individual'),
            'incident_type': context.user_data.get('incident_type'),
            'incident_date': context.user_data.get('incident_date'),
            'incident_location': context.user_data.get('incident_location'),
            'description': context.user_data.get('description'),
            'complainant_name': context.user_data.get('complainant_name'),
            'complainant_phone': context.user_data.get('complainant_phone'),
            'complainant_address': context.user_data.get('complainant_address'),
            'accused_details': context.user_data.get('accused_details', 'Not provided'),
            'witness_details': context.user_data.get('witness_details', 'Not provided'),
            'evidence_details': context.user_data.get('evidence_details', 'Not provided'),
            'police_station': context.user_data.get('police_station'),
            'status': 'submitted',
            'payment_status': False
        }
        
        # Save to database
        saved_fir = db.add_fir(fir_data)
        context.user_data['fir_number'] = saved_fir['fir_number']
        
        # Show payment
        amount = 500 if context.user_data.get('plan') == 'individual' else 1500
        
        keyboard = [
            [InlineKeyboardButton("💳 Pay Now (Simulate)", callback_data=f'payment_{saved_fir["fir_number"]}')],
            [InlineKeyboardButton("⏭️ Skip Payment (Test)", callback_data=f'payment_skip_{saved_fir["fir_number"]}')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            texts['payment_required'].format(
                amount=amount,
                plan=context.user_data.get('plan', 'individual')
            ),
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML
        )
        return PROCESS_PAYMENT
    else:
        await query.edit_message_text("❌ FIR cancelled.")
        return ConversationHandler.END

async def process_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle payment callback"""
    query = update.callback_query
    await query.answer()
    
    language = context.user_data.get('language', 'en')
    texts = TEXTS[language]
    
    # Get FIR number
    parts = query.data.split('_')
    fir_number = parts[1] if len(parts) > 1 else context.user_data.get('fir_number')
    
    # Check if skip payment
    if 'skip' in query.data:
        # Simulate payment success
        db.update_payment_status(fir_number, True)
        await query.edit_message_text("⏳ Processing...")
        await asyncio.sleep(1)
    else:
        # Simulate payment processing
        await query.edit_message_text("⏳ Processing payment...")
        await asyncio.sleep(2)
        # Simulate successful payment
        db.update_payment_status(fir_number, True)
    
    # Get updated FIR
    fir = db.get_fir_by_number(fir_number)
    
    if fir:
        await query.edit_message_text(
            texts['payment_success'].format(
                fir_number=fir_number,
                status='Paid & Processed'
            ),
            parse_mode=ParseMode.HTML
        )
        
        # Send success message
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=texts['filing_success'].format(
                fir_number=fir_number,
                status='Filed'
            ),
            parse_mode=ParseMode.HTML
        )
        
        # Try to generate and send PDF
        try:
            pdf_path = generate_pdf(fir, language)
            if pdf_path and os.path.exists(pdf_path):
                with open(pdf_path, 'rb') as pdf_file:
                    await context.bot.send_document(
                        chat_id=update.effective_chat.id,
                        document=InputFile(pdf_file, filename=f"FIR_{fir_number}.pdf"),
                        caption="📄 Your FIR Document"
                    )
                # Cleanup
                if os.path.exists(pdf_path):
                    os.remove(pdf_path)
        except Exception as e:
            logger.error(f"PDF error: {e}")
    
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=texts['feedback'],
        parse_mode=ParseMode.HTML
    )
    return PROVIDE_FEEDBACK

def generate_pdf(fir_data, language):
    """Generate PDF for FIR"""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib import colors
        from reportlab.lib.units import inch
        
        if not fir_data:
            return None
        
        filename = f"FIR_{fir_data['fir_number']}.pdf"
        doc = SimpleDocTemplate(filename, pagesize=A4)
        styles = getSampleStyleSheet()
        story = []
        
        # Title
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=16,
            textColor=colors.darkblue,
            alignment=1,
            spaceAfter=30
        )
        story.append(Paragraph("FIRST INFORMATION REPORT", title_style))
        story.append(Spacer(1, 12))
        
        # FIR Number
        story.append(Paragraph(f"<b>FIR Number:</b> {fir_data['fir_number']}", styles['Normal']))
        story.append(Spacer(1, 6))
        
        # Details table
        details = [
            ["Date", fir_data.get('incident_date', 'N/A')],
            ["Type", fir_data.get('incident_type', 'N/A')],
            ["Location", fir_data.get('incident_location', 'N/A')],
            ["Complainant", fir_data.get('complainant_name', 'N/A')],
            ["Phone", fir_data.get('complainant_phone', 'N/A')],
            ["Address", fir_data.get('complainant_address', 'N/A')],
            ["Police Station", fir_data.get('police_station', 'N/A')],
        ]
        
        table = Table(details, colWidths=[2*inch, 4*inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), colors.lightgrey),
            ('TEXTCOLOR', (0, 0), (0, -1), colors.black),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('PADDING', (0, 0), (-1, -1), 6),
        ]))
        story.append(table)
        story.append(Spacer(1, 12))
        
        # Description
        story.append(Paragraph("<b>Description:</b>", styles['Normal']))
        story.append(Spacer(1, 6))
        story.append(Paragraph(fir_data.get('description', 'N/A'), styles['Normal']))
        story.append(Spacer(1, 12))
        
        # Accused, Witnesses, Evidence
        for label, key in [("Accused:", "accused_details"), ("Witnesses:", "witness_details"), ("Evidence:", "evidence_details")]:
            story.append(Paragraph(f"<b>{label}</b>", styles['Normal']))
            story.append(Spacer(1, 6))
            story.append(Paragraph(fir_data.get(key, 'N/A'), styles['Normal']))
            story.append(Spacer(1, 6))
        
        # Footer
        story.append(Spacer(1, 20))
        story.append(Paragraph(f"Generated on: {datetime.now().strftime('%d/%m/%Y %H:%M')}", styles['Normal']))
        story.append(Paragraph("This is a system-generated document.", styles['Normal']))
        
        # Build PDF
        doc.build(story)
        return filename
    except Exception as e:
        logger.error(f"PDF generation error: {e}")
        return None

async def provide_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle feedback"""
    feedback = update.message.text
    user_id = str(update.effective_user.id)
    language = context.user_data.get('language', 'en')
    texts = TEXTS[language]
    
    # Save feedback
    db.add_feedback(user_id, feedback)
    
    await update.message.reply_text(
        texts['feedback_thanks'],
        parse_mode=ParseMode.HTML
    )
    return ConversationHandler.END

# ============================================================
# ADDITIONAL COMMANDS
# ============================================================

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check FIR status"""
    language = context.user_data.get('language', 'en')
    texts = TEXTS[language]
    
    await update.message.reply_text(
        texts['status_check'],
        parse_mode=ParseMode.HTML
    )
    return STATUS_CHECK

async def status_check_response(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle status check response"""
    fir_number = update.message.text.strip().upper()
    language = context.user_data.get('language', 'en')
    texts = TEXTS[language]
    
    fir = db.get_fir_by_number(fir_number)
    
    if fir:
        await update.message.reply_text(
            texts['status_response'].format(
                fir_number=fir_number,
                status=fir.get('status', 'Unknown'),
                date=fir.get('incident_date', 'N/A'),
                plan=fir.get('plan', 'N/A')
            ),
            parse_mode=ParseMode.HTML
        )
    else:
        await update.message.reply_text(
            texts['invalid_fir'],
            parse_mode=ParseMode.HTML
        )
    
    return ConversationHandler.END

async def list_firs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List user's FIRs"""
    user_id = str(update.effective_user.id)
    language = context.user_data.get('language', 'en')
    texts = TEXTS[language]
    
    firs = db.get_firs(user_id)
    
    if firs:
        message = ""
        for i, fir in enumerate(firs, 1):
            status_icon = "✅" if fir.get('payment_status') else "⏳"
            message += f"{i}. {status_icon} <code>{fir['fir_number']}</code>\n   Status: {fir.get('status', 'N/A')}\n   Date: {fir.get('incident_date', 'N/A')}\n\n"
        
        await update.message.reply_text(
            texts['list_response'].format(firs=message),
            parse_mode=ParseMode.HTML
        )
    else:
        await update.message.reply_text(
            texts['no_firs'],
            parse_mode=ParseMode.HTML
        )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Help command"""
    language = context.user_data.get('language', 'en')
    texts = TEXTS[language]
    await update.message.reply_text(
        texts['help'],
        parse_mode=ParseMode.HTML
    )

async def support_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Support command"""
    language = context.user_data.get('language', 'en')
    texts = TEXTS[language]
    await update.message.reply_text(
        texts['support'],
        parse_mode=ParseMode.HTML
    )

async def feedback_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Feedback command"""
    language = context.user_data.get('language', 'en')
    texts = TEXTS[language]
    await update.message.reply_text(
        texts['feedback'],
        parse_mode=ParseMode.HTML
    )
    return PROVIDE_FEEDBACK

async def new_fir_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start new FIR"""
    return await start(update, context)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel command"""
    language = context.user_data.get('language', 'en')
    texts = TEXTS[language]
    await update.message.reply_text(
        texts['cancel'],
        parse_mode=ParseMode.HTML
    )
    return ConversationHandler.END

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle errors"""
    logger.error(f"Update {update} caused error {context.error}")
    if update and update.message:
        language = context.user_data.get('language', 'en')
        texts = TEXTS[language]
        await update.message.reply_text(
            texts['error'],
            parse_mode=ParseMode.HTML
        )

# ============================================================
# ADMIN COMMANDS
# ============================================================

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin panel"""
    user_id = str(update.effective_user.id)
    
    # Check if user is admin (you can set this in .env)
    admin_id = os.getenv('ADMIN_USER_ID', '')
    if admin_id and user_id != admin_id:
        await update.message.reply_text("❌ You are not authorized to use admin commands.")
        return
    
    language = context.user_data.get('language', 'en')
    texts = TEXTS[language]
    
    keyboard = [
        [InlineKeyboardButton("📊 Statistics", callback_data='admin_stats')],
        [InlineKeyboardButton("📋 View All FIRs", callback_data='admin_list')],
        [InlineKeyboardButton("🔍 Search FIR", callback_data='admin_search')],
        [InlineKeyboardButton("📤 Export Data", callback_data='admin_export')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        texts['admin_welcome'],
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )
    return ADMIN_MENU

async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle admin callbacks"""
    query = update.callback_query
    await query.answer()
    
    action = query.data.split('_')[1] if '_' in query.data else query.data
    
    language = context.user_data.get('language', 'en')
    texts = TEXTS[language]
    
    if action == 'stats':
        stats = db.get_stats()
        await query.edit_message_text(
            texts['admin_stats'].format(
                total=stats['total'],
                paid=stats['paid'],
                pending=stats['pending']
            ),
            parse_mode=ParseMode.HTML
        )
        return ADMIN_MENU
    
    elif action == 'list':
        firs = db.get_all_firs()
        if firs:
            message = ""
            for fir in firs[-10:]:  # Show last 10
                status_icon = "✅" if fir.get('payment_status') else "⏳"
                message += f"{status_icon} <code>{fir['fir_number']}</code> - {fir.get('status', 'N/A')} - {fir.get('complainant_name', 'N/A')}\n"
            
            keyboard = [
                [InlineKeyboardButton("🔙 Back", callback_data='admin_back')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                texts['admin_list'].format(firs=message),
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML
            )
        else:
            await query.edit_message_text(texts['admin_no_firs'])
        return ADMIN_MENU
    
    elif action == 'back':
        # Return to admin menu
        keyboard = [
            [InlineKeyboardButton("📊 Statistics", callback_data='admin_stats')],
            [InlineKeyboardButton("📋 View All FIRs", callback_data='admin_list')],
            [InlineKeyboardButton("🔍 Search FIR", callback_data='admin_search')],
            [InlineKeyboardButton("📤 Export Data", callback_data='admin_export')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            texts['admin_welcome'],
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML
        )
        return ADMIN_MENU
    
    else:
        await query.edit_message_text("Unknown action.")
        return ADMIN_MENU

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show statistics"""
    stats = db.get_stats()
    await update.message.reply_text(
        f"📊 <b>Bot Statistics</b>\n\n"
        f"Total FIRs: {stats['total']}\n"
        f"Paid FIRs: {stats['paid']}\n"
        f"Pending FIRs: {stats['pending']}",
        parse_mode=ParseMode.HTML
    )

# ============================================================
# MAIN FUNCTION
# ============================================================

import asyncio

def main():
    """Run the bot"""
    print("=" * 60)
    print("🤖 COMPLETE FIR BOT")
    print("=" * 60)
    print(f"✅ Bot Token: {TELEGRAM_TOKEN[:15]}...")
    print(f"✅ Database: fir_data.json")
    print("=" * 60)
    print("📱 Commands:")
    print("  /start     - Start the bot")
    print("  /new_fir   - File a new FIR")
    print("  /status    - Check FIR status")
    print("  /list      - List your FIRs")
    print("  /help      - Show help")
    print("  /support   - Contact support")
    print("  /feedback  - Give feedback")
    print("  /admin     - Admin panel (if authorized)")
    print("=" * 60)
    print("✅ Bot is running... Press Ctrl+C to stop")
    print("=" * 60)
    
    # Create application
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Main conversation handler
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
            ADMIN_MENU: [CallbackQueryHandler(admin_callback)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
        per_message=False
    )
    
    application.add_handler(conv_handler)
    application.add_handler(CommandHandler('status', status_command))
    application.add_handler(CommandHandler('list', list_firs))
    application.add_handler(CommandHandler('help', help_command))
    application.add_handler(CommandHandler('support', support_command))
    application.add_handler(CommandHandler('feedback', feedback_command))
    application.add_handler(CommandHandler('new_fir', new_fir_command))
    application.add_handler(CommandHandler('admin', admin_command))
    application.add_handler(CommandHandler('stats', stats_command))
    
    # Error handler
    application.add_error_handler(error_handler)
    
    # Run the bot
    application.run_polling()

if __name__ == '__main__':
    main()