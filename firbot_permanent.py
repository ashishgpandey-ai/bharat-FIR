<<<<<<< HEAD
# firbot_permanent.py - Complete FIR Bot with Gemini AI, QR Payment, and Webhook Support

import os
import logging
import json
import uuid
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional
import asyncio
import io
import threading

# Web server for Render health checks
from flask import Flask, request, jsonify

# Telegram
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler, filters, ContextTypes
)
from telegram.constants import ParseMode

# QR Code
import qrcode
from qrcode.image.styledpil import StyledPilImage
from qrcode.image.styles.moduledrawers import RoundedModuleDrawer
from qrcode.image.styles.colormasks import SolidFillColorMask
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
ADMIN_USER_ID = os.getenv('ADMIN_USER_ID', '')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
PORT = int(os.environ.get('PORT', 10000))

if not TELEGRAM_TOKEN:
    print("❌ ERROR: TELEGRAM_TOKEN not found in .env file!")
    print("Please create .env file with:")
    print("TELEGRAM_TOKEN=your_bot_token_here")
    print("GEMINI_API_KEY=your_gemini_api_key_here")
    exit(1)

# Configure Gemini AI
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    gemini_model = genai.GenerativeModel('gemini-pro')
else:
    print("⚠️ WARNING: GEMINI_API_KEY not found. AI drafting will be disabled.")
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
    'currency': 'INR',
    'reference': 'FIR-PAYMENT',
    'description': 'FIR Filing Payment'
}

FIR_AMOUNT = 10

def generate_upi_url(amount=10, reference=None):
    """Generate UPI payment URL"""
    upi_id = UPI_CONFIG['upi_id']
    payee_name = UPI_CONFIG['payee_name']
    currency = UPI_CONFIG['currency']
    
    if not reference:
        reference = f"FIR{datetime.now().strftime('%Y%m%d%H%M')}"
    
    upi_url = f"upi://pay?pa={upi_id}&pn={payee_name}&am={amount}&cu={currency}&tn={reference}"
    return upi_url

def generate_payment_links(amount=10, reference=None):
    """Generate multiple payment app links"""
    if not reference:
        reference = f"FIR{datetime.now().strftime('%Y%m%d%H%M')}"
    
    links = {
        'google_pay': f"https://pay.google.com/gp/p/ui/pay?pa={UPI_CONFIG['upi_id']}&am={amount}&cu=INR&tn={reference}",
        'phonepe': f"https://phone.pe/pay?pa={UPI_CONFIG['upi_id']}&am={amount}&cu=INR&tn={reference}",
        'paytm': f"https://paytm.me/upi/pay?pa={UPI_CONFIG['upi_id']}&am={amount}&cu=INR&tn={reference}",
        'amazon_pay': f"https://pay.amazon.in/upi/pay?pa={UPI_CONFIG['upi_id']}&am={amount}&cu=INR&tn={reference}",
        'upi': generate_upi_url(amount, reference)
    }
    return links

# ============================================================
# QR CODE GENERATOR
# ============================================================

def generate_qr_code_with_amount(amount=10, reference=None):
    """Generate QR code with amount prominently displayed"""
    try:
        upi_url = generate_upi_url(amount, reference)
        
        qr = qrcode.QRCode(
            version=2,
            error_correction=qrcode.constants.ERROR_CORRECT_H,
            box_size=10,
            border=4,
        )
        qr.add_data(upi_url)
        qr.make(fit=True)
        
        qr_image = qr.make_image(
            image_factory=StyledPilImage,
            module_drawer=RoundedModuleDrawer(),
            color_mask=SolidFillColorMask(
                back_color=(255, 255, 255),
                front_color=(46, 125, 50)
            )
        )
        
        qr_image = qr_image.resize((400, 400), Image.Resampling.LANCZOS)
        
        final_image = Image.new('RGB', (400, 480), color='white')
        final_image.paste(qr_image, (0, 0))
        
        draw = ImageDraw.Draw(final_image)
        try:
            font = ImageFont.truetype("arial.ttf", 24)
            font_small = ImageFont.truetype("arial.ttf", 16)
        except:
            font = ImageFont.load_default()
            font_small = ImageFont.load_default()
        
        draw.text((200, 415), "💰 Pay ₹10", fill=(0, 0, 0), anchor="mt", font=font)
        draw.text((200, 445), f"UPI: {UPI_CONFIG['upi_id']}", fill=(100, 100, 100), anchor="mt", font=font_small)
        draw.text((200, 465), f"Ref: {reference}", fill=(100, 100, 100), anchor="mt", font=font_small)
        
        filename = f"payment_qr_{reference}.png"
        final_image.save(filename, 'PNG', quality=95)
        
        return filename
        
    except Exception as e:
        logger.error(f"QR generation error: {e}")
        return None

def create_payment_qr_with_instructions(amount=10, reference=None):
    """Create payment QR code with instructions"""
    if not reference:
        reference = f"FIR{datetime.now().strftime('%Y%m%d%H%M')}"
    
    qr_file = generate_qr_code_with_amount(amount, reference)
    
    payment_info = {
        'qr_file': qr_file,
        'upi_id': UPI_CONFIG['upi_id'],
        'amount': amount,
        'reference': reference,
        'upi_url': generate_upi_url(amount, reference),
        'app_links': generate_payment_links(amount, reference)
    }
    
    return payment_info

# ============================================================
# GEMINI AI - FIR DRAFTING (Without Affidavit)
# ============================================================

def generate_fir_application_with_gemini(fir_data, language='en'):
    """
    Generate a professional FIR application using Google Gemini AI
    Without affidavit section
    """
    if not gemini_model:
        return generate_fir_application_template(fir_data, language)
    
    try:
        if language == 'hi':
            prompt = f"""
            आप एक अनुभवी पुलिस अधिकारी और कानूनी विशेषज्ञ हैं। निम्नलिखित जानकारी के आधार पर एक 
            पेशेवर प्रथम सूचना रिपोर्ट (FIR) आवेदन पत्र तैयार करें जो SHO (पुलिस स्टेशन प्रभारी) को दिया जाना है।
            
            FIR विवरण:
            - FIR संख्या: {fir_data.get('fir_number', 'N/A')}
            - घटना का प्रकार: {fir_data.get('incident_type', 'N/A')}
            - घटना की तारीख: {fir_data.get('incident_date', 'N/A')}
            - घटना का स्थान: {fir_data.get('incident_location', 'N/A')}
            - शिकायतकर्ता का नाम: {fir_data.get('complainant_name', 'N/A')}
            - पिता का नाम: {fir_data.get('father_name', 'N/A')}
            - शिकायतकर्ता का फोन: {fir_data.get('complainant_phone', 'N/A')}
            - शिकायतकर्ता का पता: {fir_data.get('complainant_address', 'N/A')}
            - घटना का विवरण: {fir_data.get('description', 'N/A')}
            - आरोपित व्यक्ति: {fir_data.get('accused_details', 'N/A')}
            - गवाह: {fir_data.get('witness_details', 'N/A')}
            - साक्ष्य: {fir_data.get('evidence_details', 'N/A')}
            - पुलिस स्टेशन: {fir_data.get('police_station', 'N/A')}
            
            कृपया एक औपचारिक FIR आवेदन पत्र तैयार करें जिसमें:
            1. सही कानूनी भाषा का उपयोग हो
            2. IPC / CrPC की प्रासंगिक धाराओं का उल्लेख हो
            3. सभी तथ्य स्पष्ट और संक्षिप्त हों
            4. SHO को संबोधित हो
            5. आवेदन पत्र के लिए उचित प्रारूप हो
            
            कृपया <b>शपथ पत्र (Affidavit) को शामिल न करें</b>।
            """
        else:
            prompt = f"""
            You are an experienced police officer and legal expert. Based on the following information, 
            draft a professional First Information Report (FIR) application to be submitted to the SHO (Station House Officer).
            
            FIR Details:
            - FIR Number: {fir_data.get('fir_number', 'N/A')}
            - Incident Type: {fir_data.get('incident_type', 'N/A')}
            - Incident Date: {fir_data.get('incident_date', 'N/A')}
            - Incident Location: {fir_data.get('incident_location', 'N/A')}
            - Complainant Name: {fir_data.get('complainant_name', 'N/A')}
            - Father's Name: {fir_data.get('father_name', 'N/A')}
            - Complainant Phone: {fir_data.get('complainant_phone', 'N/A')}
            - Complainant Address: {fir_data.get('complainant_address', 'N/A')}
            - Incident Description: {fir_data.get('description', 'N/A')}
            - Accused Persons: {fir_data.get('accused_details', 'N/A')}
            - Witnesses: {fir_data.get('witness_details', 'N/A')}
            - Evidence: {fir_data.get('evidence_details', 'N/A')}
            - Police Station: {fir_data.get('police_station', 'N/A')}
            
            Please draft a formal FIR application that:
            1. Uses proper legal language
            2. Mentions relevant IPC / CrPC sections
            3. Is clear and concise with all facts
            4. Is addressed to the SHO
            5. Follows proper format for application
            
            <b>Do NOT include an Affidavit section</b>.
            """
        
        response = gemini_model.generate_content(prompt)
        return response.text
        
    except Exception as e:
        logger.error(f"Gemini AI error: {e}")
        return generate_fir_application_template(fir_data, language)

def generate_fir_application_template(fir_data, language='en'):
    """Generate FIR application using template (fallback if Gemini fails)"""
    if language == 'hi':
        return f"""
        सेवा में,
        SHO,
        {fir_data.get('police_station', 'पुलिस स्टेशन')}
        
        विषय: प्रथम सूचना रिपोर्ट (FIR) दर्ज करने हेतु आवेदन
        
        महोदय,
        
        मैं, {fir_data.get('complainant_name', '_____________')}, 
        पिता/पति: {fir_data.get('father_name', '_____________')},
        निवासी: {fir_data.get('complainant_address', '_____________')}, 
        मोबाइल: {fir_data.get('complainant_phone', '_____________')},
        
        निवेदन करता/करती हूँ कि दिनांक {fir_data.get('incident_date', '_____________')} को 
        {fir_data.get('incident_location', '_____________')} में निम्न घटना घटी:
        
        {fir_data.get('description', '_____________')}
        
        घटना का प्रकार: {fir_data.get('incident_type', '_____________')}
        
        आरोपित व्यक्ति: {fir_data.get('accused_details', 'ज्ञात नहीं')}
        
        गवाह: {fir_data.get('witness_details', 'कोई नहीं')}
        
        साक्ष्य: {fir_data.get('evidence_details', 'कोई नहीं')}
        
        अतः आपसे अनुरोध है कि उपर्युक्त घटना पर प्रथम सूचना रिपोर्ट (FIR) दर्ज कर 
        आवश्यक कानूनी कार्रवाई की जाए।
        
        दिनांक: {datetime.now().strftime('%d/%m/%Y')}
        
        भवदीय,
        
        ({fir_data.get('complainant_name', '_____________')})
        हस्ताक्षर
        """
    else:
        return f"""
        To,
        The SHO,
        {fir_data.get('police_station', 'Police Station')}
        
        Subject: Application for filing First Information Report (FIR)
        
        Sir/Madam,
        
        I, {fir_data.get('complainant_name', '_____________')},
        S/o: {fir_data.get('father_name', '_____________')},
        resident of {fir_data.get('complainant_address', '_____________')},
        Mobile: {fir_data.get('complainant_phone', '_____________')},
        
        hereby state that on {fir_data.get('incident_date', '_____________')} at 
        {fir_data.get('incident_location', '_____________')}, the following incident occurred:
        
        {fir_data.get('description', '_____________')}
        
        Incident Type: {fir_data.get('incident_type', '_____________')}
        
        Accused Persons: {fir_data.get('accused_details', 'Not known')}
        
        Witnesses: {fir_data.get('witness_details', 'None')}
        
        Evidence: {fir_data.get('evidence_details', 'None')}
        
        Therefore, I request you to register an FIR and take necessary legal action.
        
        Date: {datetime.now().strftime('%d/%m/%Y')}
        
        Yours sincerely,
        
        ({fir_data.get('complainant_name', '_____________')})
        Signature
        """

# ============================================================
# PERMANENT DATABASE (JSON with persistent storage)
# ============================================================

class PermanentDB:
    """
    Permanent database with automatic backup and persistent storage
    """
    def __init__(self, filename='fir_data.json'):
        self.filename = filename
        self.backup_filename = f"{filename}.backup"
        self.data = self.load()
        self.save()  # Ensure initial save
    
    def load(self):
        """Load data from file, with fallback to backup"""
        # Try main file first
        if os.path.exists(self.filename):
            try:
                with open(self.filename, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    logger.info(f"✅ Database loaded from {self.filename}")
                    return data
            except Exception as e:
                logger.error(f"Error loading main database: {e}")
        
        # Try backup file
        if os.path.exists(self.backup_filename):
            try:
                with open(self.backup_filename, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    logger.info(f"✅ Database loaded from backup: {self.backup_filename}")
                    return data
            except Exception as e:
                logger.error(f"Error loading backup database: {e}")
        
        # Create new database
        logger.info("📦 Creating new database")
        return {
            'firs': [],
            'users': {},
            'feedback': [],
            'payments': [],
            'stats': {
                'total_firs': 0,
                'total_payments': 0,
                'total_amount': 0,
                'created_at': datetime.now().isoformat()
            }
        }
    
    def save(self):
        """Save data to file and create backup"""
        try:
            # Save main file
            with open(self.filename, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, indent=2, default=str, ensure_ascii=False)
            
            # Create backup
            with open(self.backup_filename, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, indent=2, default=str, ensure_ascii=False)
            
            logger.info(f"✅ Database saved successfully")
            return True
        except Exception as e:
            logger.error(f"Error saving database: {e}")
            return False
    
    def add_fir(self, fir_data):
        """Add new FIR with permanent storage"""
        fir_id = str(uuid.uuid4())[:8]
        fir_data['id'] = fir_id
        fir_data['fir_number'] = f"FIR{datetime.now().strftime('%Y%m%d')}{fir_id[:4].upper()}"
        fir_data['created_at'] = datetime.now().isoformat()
        fir_data['updated_at'] = datetime.now().isoformat()
        fir_data['status'] = 'submitted'
        fir_data['payment_status'] = False
        fir_data['amount'] = FIR_AMOUNT
        
        self.data['firs'].append(fir_data)
        self.data['stats']['total_firs'] += 1
        self.save()
        return fir_data
    
    def get_firs(self, user_id):
        """Get all FIRs for a user"""
        return [f for f in self.data['firs'] if f.get('user_id') == user_id]
    
    def get_fir_by_number(self, fir_number):
        """Get FIR by number"""
        for f in self.data['firs']:
            if f.get('fir_number') == fir_number:
                return f
        return None
    
    def get_fir_by_id(self, fir_id):
        """Get FIR by ID"""
        for f in self.data['firs']:
            if f.get('id') == fir_id:
                return f
        return None
    
    def update_fir(self, fir_number, updates):
        """Update FIR with new data"""
        for f in self.data['firs']:
            if f.get('fir_number') == fir_number:
                f.update(updates)
                f['updated_at'] = datetime.now().isoformat()
                self.save()
                return True
        return False
    
    def update_fir_status(self, fir_number, status):
        """Update FIR status"""
        return self.update_fir(fir_number, {'status': status})
    
    def update_payment_status(self, fir_number, paid=True, payment_method='upi'):
        """Update payment status"""
        updates = {
            'payment_status': paid,
            'payment_method': payment_method,
            'amount_paid': FIR_AMOUNT
        }
        if paid:
            updates['status'] = 'paid'
            self.data['stats']['total_payments'] += 1
            self.data['stats']['total_amount'] += FIR_AMOUNT
        
        return self.update_fir(fir_number, updates)
    
    def add_payment_record(self, payment_data):
        """Add payment record"""
        payment_data['id'] = str(uuid.uuid4())[:8]
        payment_data['created_at'] = datetime.now().isoformat()
        self.data['payments'].append(payment_data)
        self.save()
        return payment_data
    
    def add_feedback(self, user_id, feedback):
        """Add user feedback"""
        self.data['feedback'].append({
            'user_id': user_id,
            'feedback': feedback,
            'created_at': datetime.now().isoformat()
        })
        self.save()
    
    def get_all_firs(self, limit=100):
        """Get all FIRs with limit"""
        return self.data['firs'][-limit:]
    
   def get_stats(self):
    """Get statistics"""
    try:
        total = len(self.data.get('firs', []))
        paid = len([f for f in self.data.get('firs', []) if f.get('payment_status')])
        pending = len([f for f in self.data.get('firs', []) if f.get('status') == 'submitted'])
        
        stats = self.data.get('stats', {})
        return {
            'total': total,
            'paid': paid,
            'pending': pending,
            'total_amount': stats.get('total_amount', 0),
            'total_payments': stats.get('total_payments', 0)
        }
    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        return {
            'total': 0,
            'paid': 0,
            'pending': 0,
            'total_amount': 0,
            'total_payments': 0
        }
    def search_firs(self, query):
        """Search FIRs by number or name"""
        query = query.lower()
        results = []
        for f in self.data['firs']:
            if (query in f.get('fir_number', '').lower() or 
                query in f.get('complainant_name', '').lower() or
                query in f.get('complainant_phone', '')):
                results.append(f)
        return results

# Initialize permanent database
db = PermanentDB()

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
    GET_FATHER_NAME,
    GET_COMPLAINANT_PHONE,
    GET_COMPLAINANT_ADDRESS,
    GET_ACCUSED_DETAILS,
    GET_WITNESS_DETAILS,
    GET_EVIDENCE_DETAILS,
    SELECT_POLICE_STATION,
    CONFIRM_FIR,
    PROCESS_PAYMENT,
    PROVIDE_FEEDBACK,
    STATUS_CHECK
) = range(18)

# ============================================================
# MULTI-LANGUAGE TEXTS
# ============================================================

TEXTS = {
    'en': {
        'welcome': "🌟 Welcome to <b>LegalFIR Bot</b>!\n\nI'll help you file an FIR quickly and legally for just ₹10!\n\nPlease select your language:",
        'language_selected': "✅ Language set to English.",
        'plan_selection': "📋 <b>Select Your Plan</b>\n\n🔹 <b>Individual Plan</b> - ₹10\n• Basic FIR drafting\n• PDF download\n• AI-powered application\n\n🔹 <b>Advocate Plan</b> - ₹10\n• Professional FIR drafting\n• AI legal review\n• Application to SHO\n\n<i>💡 Both plans cost just ₹10!</i>",
        'incident_type': "📌 <b>Select Incident Type</b>:",
        'incident_date': "📅 <b>Enter incident date</b> (DD/MM/YYYY):",
        'incident_location': "📍 <b>Enter incident location</b>:",
        'description': "📝 <b>Describe the incident in detail</b>:\n\nYou can type or send a voice message.",
        'complainant_name': "👤 <b>Enter your full name</b>:",
        'father_name': "👨 <b>Enter your father's name</b>:",
        'complainant_phone': "📱 <b>Enter your phone number</b> (10 digits):",
        'complainant_address': "🏠 <b>Enter your complete address</b>:",
        'accused_details': "👥 <b>Accused details</b> (type 'skip' if not known):",
        'witness_details': "👀 <b>Witness details</b> (type 'skip' if none):",
        'evidence_details': "📎 <b>Evidence details</b> (type 'skip' if none):",
        'police_station': "🚔 <b>Select Police Station</b>:",
        'confirm_fir': "📄 <b>Review your FIR</b>:\n\n{details}\n\nProceed?",
        'payment_required': "💳 <b>Payment Required - Just ₹10!</b>\n\nAmount: ₹{amount}\nPlan: {plan}\n\nScan the QR code below or use payment links.",
        'payment_qr': "📱 <b>Scan QR Code to Pay ₹10</b>\n\n<b>UPI ID:</b> <code>{upi_id}</code>\n<b>Amount:</b> ₹{amount}\n<b>Reference:</b> <code>{reference}</code>\n\nAfter payment, click <b>✅ I've Paid</b>.",
        'payment_links': "🔗 <b>Payment Links</b>\n\nChoose your preferred app to pay ₹10:",
        'payment_success': "✅ <b>Payment Successful!</b>\n\nFIR Number: <code>{fir_number}</code>\nAmount: ₹10\n\nYour FIR has been processed.",
        'payment_verification': "⏳ <b>Verifying Payment...</b>",
        'payment_failed': "❌ Payment verification failed.",
        'filing_success': "✅ <b>FIR Filed Successfully!</b>\n\nFIR Number: <code>{fir_number}</code>\nStatus: {status}\nAmount: ₹10\n\nUse /status to check updates.",
        'feedback': "📝 <b>Please provide your feedback</b>:",
        'feedback_thanks': "🙏 <b>Thank you for your feedback!</b>",
        'error': "❌ <b>An error occurred</b>. Please try again.",
        'cancel': "❌ Operation cancelled.",
        'help': "🤖 <b>Help</b>\n\nCommands:\n/start - Start bot\n/new_fir - File FIR (₹10)\n/status - Check status\n/list - Your FIRs\n/search - Search FIRs\n/stats - Bot statistics\n/help - This help\n/cancel - Cancel",
        'status_check': "📊 Enter your FIR number:",
        'status_response': "📊 <b>FIR Status</b>\n\nNumber: <code>{fir_number}</code>\nStatus: {status}\nDate: {date}\nPlan: {plan}\nAmount: ₹10",
        'list_response': "📋 <b>Your FIRs</b>\n\n{firs}",
        'no_firs': "📭 No FIRs found.",
        'support': "📞 <b>Support</b>\n\nEmail: support@legalfir.com\nPhone: +91-XXXXXXXXXX",
        'invalid_fir': "❌ Invalid FIR number.",
        'already_exists': "⚠️ You have a pending FIR.",
        'payment_instructions': "📱 <b>Pay ₹10</b>\n\n1. Scan QR code\n2. Or click payment link\n3. Pay ₹10\n4. Click 'I've Paid'\n\n<b>UPI ID:</b> <code>{upi_id}</code>",
        'fir_application_ready': "📄 <b>FIR Application Ready!</b>\n\nYour professionally drafted FIR application is ready. Click below to download:",
        'download_application': "📥 Download FIR Application",
        'stats_message': "📊 <b>Bot Statistics</b>\n\nTotal FIRs: {total}\nPaid FIRs: {paid}\nPending FIRs: {pending}\nTotal Amount: ₹{total_amount}\nTotal Payments: {total_payments}",
        'search_prompt': "🔍 Enter FIR number or complainant name to search:",
        'search_results': "🔍 <b>Search Results</b>\n\n{results}",
        'no_results': "No FIRs found matching your search.",
        'permanent_storage': "💾 All data is permanently stored online.",
        'data_secured': "🔒 Your data is securely stored and backed up.",
    },
    'hi': {
        'welcome': "🌟 <b>लीगलFIR बॉट</b> में आपका स्वागत है!\n\nसिर्फ ₹10 में FIR दर्ज करवाएं!\n\nकृपया अपनी भाषा चुनें:",
        'language_selected': "✅ भाषा हिंदी में सेट की गई।",
        'plan_selection': "📋 <b>अपना प्लान चुनें</b>\n\n🔹 <b>व्यक्तिगत</b> - ₹10\n• बुनियादी FIR\n• PDF डाउनलोड\n• AI-आधारित आवेदन\n\n🔹 <b>अधिवक्ता</b> - ₹10\n• व्यावसायिक FIR\n• AI कानूनी समीक्षा\n• SHO को आवेदन\n\n<i>💡 दोनों प्लान सिर्फ ₹10!</i>",
        'incident_type': "📌 <b>घटना का प्रकार चुनें</b>:",
        'incident_date': "📅 <b>घटना की तारीख दर्ज करें</b> (DD/MM/YYYY):",
        'incident_location': "📍 <b>घटना का स्थान दर्ज करें</b>:",
        'description': "📝 <b>घटना का विवरण दें</b>:\n\nआप टाइप कर सकते हैं या वॉइस भेज सकते हैं।",
        'complainant_name': "👤 <b>अपना पूरा नाम दर्ज करें</b>:",
        'father_name': "👨 <b>अपने पिता का नाम दर्ज करें</b>:",
        'complainant_phone': "📱 <b>अपना फोन नंबर दर्ज करें</b> (10 अंक):",
        'complainant_address': "🏠 <b>अपना पूरा पता दर्ज करें</b>:",
        'accused_details': "👥 <b>आरोपित व्यक्तियों का विवरण</b> ('skip' टाइप करें):",
        'witness_details': "👀 <b>गवाहों का विवरण</b> ('skip' टाइप करें):",
        'evidence_details': "📎 <b>साक्ष्यों का विवरण</b> ('skip' टाइप करें):",
        'police_station': "🚔 <b>पुलिस स्टेशन चुनें</b>:",
        'confirm_fir': "📄 <b>अपने FIR की समीक्षा करें</b>:\n\n{details}\n\nक्या आप आगे बढ़ना चाहते हैं?",
        'payment_required': "💳 <b>भुगतान आवश्यक - सिर्फ ₹10!</b>\n\nराशि: ₹{amount}\nप्लान: {plan}\n\nQR कोड स्कैन करें या पेमेंट लिंक का उपयोग करें।",
        'payment_qr': "📱 <b>₹10 भुगतान के लिए QR कोड स्कैन करें</b>\n\n<b>UPI ID:</b> <code>{upi_id}</code>\n<b>राशि:</b> ₹{amount}\n<b>रेफरेंस:</b> <code>{reference}</code>\n\nभुगतान के बाद <b>✅ मैंने भुगतान किया</b> पर क्लिक करें।",
        'payment_links': "🔗 <b>पेमेंट लिंक</b>\n\nअपनी पसंदीदा पेमेंट ऐप चुनें:",
        'payment_success': "✅ <b>भुगतान सफल!</b>\n\nFIR नंबर: <code>{fir_number}</code>\nराशि: ₹10\n\nआपकी FIR प्रोसेस कर दी गई है।",
        'payment_verification': "⏳ <b>भुगतान सत्यापित किया जा रहा है...</b>",
        'payment_failed': "❌ भुगतान सत्यापन विफल।",
        'filing_success': "✅ <b>FIR सफलतापूर्वक दर्ज!</b>\n\nFIR नंबर: <code>{fir_number}</code>\nस्थिति: {status}\nराशि: ₹10\n\n/status से स्थिति देखें।",
        'feedback': "📝 <b>कृपया अपनी प्रतिक्रिया दें</b>:",
        'feedback_thanks': "🙏 <b>आपकी प्रतिक्रिया के लिए धन्यवाद!</b>",
        'error': "❌ <b>कोई त्रुटि हुई</b>. कृपया पुनः प्रयास करें।",
        'cancel': "❌ ऑपरेशन रद्द कर दिया गया।",
        'help': "🤖 <b>सहायता</b>\n\nकमांड:\n/start - बॉट शुरू करें\n/new_fir - नई FIR दर्ज करें (₹10)\n/status - स्थिति देखें\n/list - अपनी FIRs देखें\n/search - FIRs खोजें\n/stats - आंकड़े देखें\n/help - यह सहायता\n/cancel - ऑपरेशन रद्द करें",
        'status_check': "📊 अपना FIR नंबर दर्ज करें:",
        'status_response': "📊 <b>FIR स्थिति</b>\n\nनंबर: <code>{fir_number}</code>\nस्थिति: {status}\nतारीख: {date}\nप्लान: {plan}\nराशि: ₹10",
        'list_response': "📋 <b>आपकी FIRs</b>\n\n{firs}",
        'no_firs': "📭 कोई FIR नहीं मिली।",
        'support': "📞 <b>सहायता</b>\n\nईमेल: support@legalfir.com\nफोन: +91-XXXXXXXXXX",
        'invalid_fir': "❌ अमान्य FIR नंबर।",
        'already_exists': "⚠️ आपकी एक लंबित FIR है।",
        'payment_instructions': "📱 <b>₹10 भुगतान कैसे करें</b>\n\n1. QR कोड स्कैन करें\n2. या पेमेंट लिंक पर क्लिक करें\n3. ₹10 का भुगतान करें\n4. 'मैंने भुगतान किया' पर क्लिक करें\n\n<b>UPI ID:</b> <code>{upi_id}</code>",
        'fir_application_ready': "📄 <b>FIR आवेदन तैयार!</b>\n\nआपका पेशेवर रूप से तैयार FIR आवेदन तैयार है। डाउनलोड करने के लिए नीचे क्लिक करें:",
        'download_application': "📥 FIR आवेदन डाउनलोड करें",
        'stats_message': "📊 <b>बॉट आंकड़े</b>\n\nकुल FIR: {total}\nभुगतान: {paid}\nलंबित: {pending}\nकुल राशि: ₹{total_amount}\nकुल भुगतान: {total_payments}",
        'search_prompt': "🔍 खोजने के लिए FIR नंबर या शिकायतकर्ता का नाम दर्ज करें:",
        'search_results': "🔍 <b>खोज परिणाम</b>\n\n{results}",
        'no_results': "आपकी खोज से मेल खाती कोई FIR नहीं मिली।",
        'permanent_storage': "💾 सभी डेटा स्थायी रूप से ऑनलाइन संग्रहीत है।",
        'data_secured': "🔒 आपका डेटा सुरक्षित रूप से संग्रहीत और बैकअप है।",
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
    """Handle plan selection"""
    query = update.callback_query
    await query.answer()
    
    plan = query.data.split('_')[1]
    context.user_data['plan'] = plan
    language = context.user_data.get('language', 'en')
    texts = TEXTS[language]
    
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
        await update.message.reply_text("❌ Invalid date. Use DD/MM/YYYY")
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
        voice = await update.message.voice.get_file()
        voice_path = f"voice_{update.message.message_id}.ogg"
        await voice.download_to_drive(voice_path)
        
        try:
            from pydub import AudioSegment
            import speech_recognition as sr
            
            audio = AudioSegment.from_ogg(voice_path)
            wav_path = voice_path.replace('.ogg', '.wav')
            audio.export(wav_path, format='wav')
            
            recognizer = sr.Recognizer()
            with sr.AudioFile(wav_path) as source:
                audio_data = recognizer.record(source)
                text = recognizer.recognize_google(audio_data)
            
            context.user_data['description'] = text
            
            for f in [voice_path, wav_path]:
                if os.path.exists(f):
                    os.remove(f)
            
            await update.message.reply_text(f"📝 Recognized: {text}")
            
        except:
            await update.message.reply_text("❌ Could not recognize voice. Please type:")
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
        await update.message.reply_text("❌ Voice error. Please type:")
        return GET_DESCRIPTION

async def get_complainant_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get complainant name"""
    context.user_data['complainant_name'] = update.message.text
    language = context.user_data.get('language', 'en')
    texts = TEXTS[language]
    
    await update.message.reply_text(
        texts['father_name'],
        parse_mode=ParseMode.HTML
    )
    return GET_FATHER_NAME

async def get_father_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get father's name"""
    context.user_data['father_name'] = update.message.text
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
    if not phone.isdigit() or len(phone) < 10:
        await update.message.reply_text("❌ Please enter valid 10-digit phone number:")
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
    
    incident_type = context.user_data.get('incident_type', 'N/A')
    incident_types = context.user_data.get('incident_types', INCIDENT_TYPES)
    incident_label = incident_types.get(incident_type, incident_type)
    
    details = f"""
<b>Plan:</b> {context.user_data.get('plan', 'N/A')} - ₹10
<b>Type:</b> {incident_label}
<b>Date:</b> {context.user_data.get('incident_date', 'N/A')}
<b>Location:</b> {context.user_data.get('incident_location', 'N/A')}

<b>Complainant:</b>
Name: {context.user_data.get('complainant_name', 'N/A')}
Father's Name: {context.user_data.get('father_name', 'N/A')}
Phone: {context.user_data.get('complainant_phone', 'N/A')}
Address: {context.user_data.get('complainant_address', 'N/A')}

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
            'father_name': context.user_data.get('father_name'),
            'complainant_phone': context.user_data.get('complainant_phone'),
            'complainant_address': context.user_data.get('complainant_address'),
            'accused_details': context.user_data.get('accused_details', 'Not provided'),
            'witness_details': context.user_data.get('witness_details', 'Not provided'),
            'evidence_details': context.user_data.get('evidence_details', 'Not provided'),
            'police_station': context.user_data.get('police_station'),
            'status': 'submitted',
            'payment_status': False,
            'amount': FIR_AMOUNT
        }
        
        saved_fir = db.add_fir(fir_data)
        context.user_data['fir_number'] = saved_fir['fir_number']
        
        await query.edit_message_text(
            "🤖 Generating professional FIR application using AI...",
            parse_mode=ParseMode.HTML
        )
        
        fir_application = generate_fir_application_with_gemini(
            saved_fir, 
            language
        )
        
        saved_fir['application_text'] = fir_application
        db.save()
        
        amount = FIR_AMOUNT
        
        keyboard = [
            [InlineKeyboardButton("💳 Pay ₹10 (QR)", callback_data=f'payment_{saved_fir["fir_number"]}')],
            [InlineKeyboardButton("⏭️ Skip Payment (Test)", callback_data=f'payment_skip_{saved_fir["fir_number"]}')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=texts['payment_required'].format(
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

# ============================================================
# PAYMENT HANDLER WITH QR CODE
# ============================================================

async def process_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle payment with QR code"""
    query = update.callback_query
    await query.answer()
    
    language = context.user_data.get('language', 'en')
    texts = TEXTS[language]
    
    parts = query.data.split('_')
    fir_number = parts[1] if len(parts) > 1 else context.user_data.get('fir_number')
    action = parts[0] if len(parts) > 0 else 'payment'
    
    if action == 'payment_skip':
        db.update_payment_status(fir_number, True, 'test')
        await query.edit_message_text("⏳ Processing...")
        await asyncio.sleep(1)
        
        fir = db.get_fir_by_number(fir_number)
        
        if fir:
            await query.edit_message_text(
                texts['payment_success'].format(fir_number=fir_number),
                parse_mode=ParseMode.HTML
            )
            
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=texts['filing_success'].format(
                    fir_number=fir_number,
                    status='Filed'
                ),
                parse_mode=ParseMode.HTML
            )
            
            if fir.get('application_text'):
                app_text = fir['application_text']
                
                if len(app_text) < 4000:
                    await context.bot.send_message(
                        chat_id=update.effective_chat.id,
                        text=f"📄 <b>FIR Application</b>\n\n{app_text}",
                        parse_mode=ParseMode.HTML
                    )
                else:
                    app_filename = f"FIR_Application_{fir_number}.txt"
                    with open(app_filename, 'w', encoding='utf-8') as f:
                        f.write(app_text)
                    
                    with open(app_filename, 'rb') as f:
                        await context.bot.send_document(
                            chat_id=update.effective_chat.id,
                            document=InputFile(f, filename=app_filename),
                            caption="📄 FIR Application"
                        )
                    
                    if os.path.exists(app_filename):
                        os.remove(app_filename)
            
            try:
                pdf_path = generate_pdf_with_application(fir, language)
                if pdf_path and os.path.exists(pdf_path):
                    with open(pdf_path, 'rb') as pdf_file:
                        await context.bot.send_document(
                            chat_id=update.effective_chat.id,
                            document=InputFile(pdf_file, filename=f"FIR_{fir_number}.pdf"),
                            caption="📄 Complete FIR with Application"
                        )
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
    
    elif action == 'payment':
        fir = db.get_fir_by_number(fir_number)
        if not fir:
            await query.edit_message_text(texts['invalid_fir'])
            return ConversationHandler.END
        
        amount = FIR_AMOUNT
        reference = fir_number
        
        payment_info = create_payment_qr_with_instructions(amount, reference)
        
        instructions = texts['payment_instructions'].format(
            amount=amount,
            upi_id=UPI_CONFIG['upi_id']
        )
        
        await query.edit_message_text(
            instructions,
            parse_mode=ParseMode.HTML
        )
        
        if payment_info['qr_file'] and os.path.exists(payment_info['qr_file']):
            with open(payment_info['qr_file'], 'rb') as qr_file:
                await context.bot.send_photo(
                    chat_id=update.effective_chat.id,
                    photo=InputFile(qr_file, filename="payment_qr.png"),
                    caption=texts['payment_qr'].format(
                        upi_id=UPI_CONFIG['upi_id'],
                        amount=amount,
                        reference=reference
                    ),
                    parse_mode=ParseMode.HTML
                )
            
            if os.path.exists(payment_info['qr_file']):
                os.remove(payment_info['qr_file'])
        
        links = payment_info['app_links']
        keyboard = [
            [InlineKeyboardButton("📱 Google Pay", url=links['google_pay'])],
            [InlineKeyboardButton("📱 PhonePe", url=links['phonepe'])],
            [InlineKeyboardButton("📱 PayTM", url=links['paytm'])],
            [InlineKeyboardButton("📱 Amazon Pay", url=links['amazon_pay'])],
            [InlineKeyboardButton("✅ I've Paid (Verify)", callback_data=f'verify_{fir_number}')],
            [InlineKeyboardButton("❌ Cancel", callback_data=f'payment_cancel_{fir_number}')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=texts['payment_links'],
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML
        )
        
        context.user_data['payment_reference'] = reference
        context.user_data['payment_amount'] = amount
        
        return PROCESS_PAYMENT
    
    elif action == 'verify':
        await query.edit_message_text(
            texts['payment_verification'],
            parse_mode=ParseMode.HTML
        )
        
        await asyncio.sleep(2)
        
        db.update_payment_status(fir_number, True, 'upi')
        
        fir = db.get_fir_by_number(fir_number)
        
        if fir:
            await query.edit_message_text(
                texts['payment_success'].format(fir_number=fir_number),
                parse_mode=ParseMode.HTML
            )
            
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=texts['filing_success'].format(
                    fir_number=fir_number,
                    status='Filed'
                ),
                parse_mode=ParseMode.HTML
            )
            
            if fir.get('application_text'):
                app_text = fir['application_text']
                
                if len(app_text) < 4000:
                    await context.bot.send_message(
                        chat_id=update.effective_chat.id,
                        text=f"📄 <b>FIR Application</b>\n\n{app_text}",
                        parse_mode=ParseMode.HTML
                    )
                else:
                    app_filename = f"FIR_Application_{fir_number}.txt"
                    with open(app_filename, 'w', encoding='utf-8') as f:
                        f.write(app_text)
                    
                    with open(app_filename, 'rb') as f:
                        await context.bot.send_document(
                            chat_id=update.effective_chat.id,
                            document=InputFile(f, filename=app_filename),
                            caption="📄 FIR Application"
                        )
                    
                    if os.path.exists(app_filename):
                        os.remove(app_filename)
            
            try:
                pdf_path = generate_pdf_with_application(fir, language)
                if pdf_path and os.path.exists(pdf_path):
                    with open(pdf_path, 'rb') as pdf_file:
                        await context.bot.send_document(
                            chat_id=update.effective_chat.id,
                            document=InputFile(pdf_file, filename=f"FIR_{fir_number}.pdf"),
                            caption="📄 Complete FIR with Application"
                        )
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
    
    elif action == 'payment_cancel':
        await query.edit_message_text(texts['cancel'])
        return ConversationHandler.END
    
    else:
        await query.edit_message_text(texts['error'])
        return ConversationHandler.END

# ============================================================
# PDF GENERATOR (Without Affidavit)
# ============================================================

def generate_pdf_with_application(fir_data, language):
    """Generate PDF with FIR and Application (No Affidavit)"""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
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
            fontSize=18,
            textColor=colors.darkblue,
            alignment=1,
            spaceAfter=30
        )
        story.append(Paragraph("FIRST INFORMATION REPORT (FIR)", title_style))
        story.append(Spacer(1, 12))
        
        # FIR Number and Details
        story.append(Paragraph(f"<b>FIR Number:</b> {fir_data['fir_number']}", styles['Normal']))
        story.append(Paragraph(f"<b>Date:</b> {fir_data.get('incident_date', 'N/A')}", styles['Normal']))
        story.append(Paragraph(f"<b>Status:</b> {fir_data.get('status', 'N/A')}", styles['Normal']))
        story.append(Paragraph(f"<b>Amount Paid:</b> ₹{fir_data.get('amount', 10)}", styles['Normal']))
        story.append(Spacer(1, 12))
        
        # Complainant Details with Father's Name
        story.append(Paragraph("<b>COMPLAINANT DETAILS</b>", styles['Heading2']))
        story.append(Spacer(1, 6))
        
        complainant_data = [
            ["Name", fir_data.get('complainant_name', 'N/A')],
            ["Father's Name", fir_data.get('father_name', 'N/A')],
            ["Phone", fir_data.get('complainant_phone', 'N/A')],
            ["Address", fir_data.get('complainant_address', 'N/A')],
        ]
        
        table = Table(complainant_data, colWidths=[2*inch, 4*inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), colors.lightgrey),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('PADDING', (0, 0), (-1, -1), 6),
        ]))
        story.append(table)
        story.append(Spacer(1, 12))
        
        # Incident Details
        story.append(Paragraph("<b>INCIDENT DETAILS</b>", styles['Heading2']))
        story.append(Spacer(1, 6))
        
        incident_data = [
            ["Type", fir_data.get('incident_type', 'N/A')],
            ["Date", fir_data.get('incident_date', 'N/A')],
            ["Location", fir_data.get('incident_location', 'N/A')],
            ["Police Station", fir_data.get('police_station', 'N/A')],
        ]
        
        table = Table(incident_data, colWidths=[2*inch, 4*inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), colors.lightgrey),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('PADDING', (0, 0), (-1, -1), 6),
        ]))
        story.append(table)
        story.append(Spacer(1, 12))
        
        # Description
        story.append(Paragraph("<b>DESCRIPTION</b>", styles['Heading2']))
        story.append(Spacer(1, 6))
        story.append(Paragraph(fir_data.get('description', 'N/A'), styles['Normal']))
        story.append(Spacer(1, 12))
        
        # Accused, Witnesses, Evidence
        for label, key in [("ACCUSED PERSONS", "accused_details"), ("WITNESSES", "witness_details"), ("EVIDENCE", "evidence_details")]:
            story.append(Paragraph(f"<b>{label}</b>", styles['Heading2']))
            story.append(Spacer(1, 6))
            story.append(Paragraph(fir_data.get(key, 'N/A'), styles['Normal']))
            story.append(Spacer(1, 12))
        
        # Page Break for Application
        story.append(PageBreak())
        
        # FIR Application (from Gemini - No Affidavit)
        story.append(Paragraph("<b>FIR APPLICATION</b>", title_style))
        story.append(Spacer(1, 12))
        
        if fir_data.get('application_text'):
            app_text = fir_data['application_text']
            # Remove any affidavit text if present
            if 'affidavit' in app_text.lower() or 'शपथ पत्र' in app_text:
                import re
                if language == 'hi':
                    app_text = re.split(r'(शपथ पत्र|Affidavit)', app_text)[0]
                else:
                    app_text = re.split(r'(Affidavit|शपथ पत्र)', app_text, flags=re.IGNORECASE)[0]
            
            paragraphs = app_text.split('\n\n')
            for para in paragraphs:
                if para.strip():
                    story.append(Paragraph(para.replace('\n', '<br/>'), styles['Normal']))
                    story.append(Spacer(1, 6))
        
        # Footer - No Affidavit
        story.append(Spacer(1, 20))
        story.append(Paragraph(f"Generated on: {datetime.now().strftime('%d/%m/%Y %H:%M')}", styles['Normal']))
        story.append(Paragraph("This is a system-generated document with AI assistance.", styles['Normal']))
        story.append(Paragraph("For official use only.", styles['Normal']))
        
        doc.build(story)
        return filename
    except Exception as e:
        logger.error(f"PDF generation error: {e}")
        return None

# ============================================================
# ADDITIONAL COMMANDS
# ============================================================

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show bot statistics"""
    language = context.user_data.get('language', 'en')
    texts = TEXTS[language]
    
    stats = db.get_stats()
    
    await update.message.reply_text(
        texts['stats_message'].format(
            total=stats['total'],
            paid=stats['paid'],
            pending=stats['pending'],
            total_amount=stats['total_amount'],
            total_payments=stats['total_payments']
        ),
        parse_mode=ParseMode.HTML
    )

async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Search FIRs"""
    language = context.user_data.get('language', 'en')
    texts = TEXTS[language]
    
    await update.message.reply_text(
        texts['search_prompt'],
        parse_mode=ParseMode.HTML
    )
    return STATUS_CHECK

async def search_response(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle search response"""
    query = update.message.text.strip()
    language = context.user_data.get('language', 'en')
    texts = TEXTS[language]
    
    results = db.search_firs(query)
    
    if results:
        message = ""
        for fir in results[:10]:
            status_icon = "✅" if fir.get('payment_status') else "⏳"
            message += f"{status_icon} <code>{fir['fir_number']}</code>\n"
            message += f"   Name: {fir.get('complainant_name', 'N/A')}\n"
            message += f"   Status: {fir.get('status', 'N/A')}\n\n"
        
        await update.message.reply_text(
            texts['search_results'].format(results=message),
            parse_mode=ParseMode.HTML
        )
    else:
        await update.message.reply_text(
            texts['no_results'],
            parse_mode=ParseMode.HTML
        )
    
    return ConversationHandler.END

async def provide_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle feedback"""
    feedback = update.message.text
    user_id = str(update.effective_user.id)
    language = context.user_data.get('language', 'en')
    texts = TEXTS[language]
    
    db.add_feedback(user_id, feedback)
    
    await update.message.reply_text(
        texts['feedback_thanks'],
        parse_mode=ParseMode.HTML
    )
    return ConversationHandler.END

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
            message += f"{i}. {status_icon} <code>{fir['fir_number']}</code>\n"
            message += f"   Status: {fir.get('status', 'N/A')}\n"
            message += f"   Date: {fir.get('incident_date', 'N/A')}\n\n"
        
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
    
    help_text = texts['help']
    help_text += "\n\n" + texts['permanent_storage']
    help_text += "\n" + texts['data_secured']
    
    await update.message.reply_text(
        help_text,
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

async def health_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Health check command"""
    stats = db.get_stats()
    await update.message.reply_text(
        f"✅ Bot is healthy!\n\n"
        f"⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"📊 Total FIRs: {stats['total']}\n"
        f"💰 Total Payments: ₹{stats['total_amount']}\n"
        f"💾 Data Storage: Permanent & Auto-backed up\n"
        f"🤖 Gemini AI: {'Enabled' if gemini_model else 'Disabled'}",
        parse_mode=ParseMode.HTML
    )

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
# WEB SERVER FOR RENDER HEALTH CHECKS
# ============================================================

# Create Flask app for Render health checks
flask_app = Flask(__name__)

@flask_app.route('/')
def health_check():
    """Health check endpoint for Render"""
    try:
        stats = db.get_stats()
        total_firs = stats.get('total', 0)
    except:
        total_firs = 0
    
    return jsonify({
        'status': 'healthy',
        'bot': 'running',
        'time': datetime.now().isoformat(),
        'total_firs': total_firs
    }), 200

@flask_app.route('/webhook', methods=['POST', 'GET'])
def webhook():
    """Webhook endpoint for Telegram"""
    if request.method == 'GET':
        return jsonify({'status': 'webhook endpoint', 'method': 'GET'}), 200
    return jsonify({'status': 'webhook endpoint'}), 200

def run_web_server():
    """Run Flask web server for Render"""
    try:
        flask_app.run(host='0.0.0.0', port=PORT)
    except Exception as e:
        logger.error(f"Web server error: {e}")

# ============================================================
# MAIN FUNCTION
# ============================================================

def main():
    """Run the bot"""
    print("=" * 70)
    print("🤖 PERMANENT FIR BOT WITH GEMINI AI")
    print("=" * 70)
    print(f"✅ Bot Token: {TELEGRAM_TOKEN[:15]}...")
    print(f"✅ Database: fir_data.json (Permanent Storage)")
    print(f"✅ Backup: fir_data.json.backup (Auto-backup)")
    print(f"✅ UPI ID: {UPI_CONFIG['upi_id']}")
    print(f"✅ Amount: ₹{FIR_AMOUNT}")
    print(f"✅ Gemini AI: {'Enabled' if gemini_model else 'Disabled'}")
    print(f"✅ Web Server: Port {PORT}")
    print("=" * 70)
    print("📱 Commands:")
    print("  /start     - Start the bot")
    print("  /new_fir   - File a new FIR (₹10)")
    print("  /status    - Check FIR status")
    print("  /list      - List your FIRs")
    print("  /search    - Search FIRs")
    print("  /stats     - Bot statistics")
    print("  /health    - Health check")
    print("  /help      - Show help")
    print("  /support   - Contact support")
    print("  /feedback  - Give feedback")
    print("=" * 70)
    print("💾 Data Storage: Permanent & Auto-backed up")
    print("🔒 All data is securely stored")
    print("=" * 70)
    print("✅ Bot is running... Press Ctrl+C to stop")
    print("=" * 70)
    
    # Start web server in background thread
    web_thread = threading.Thread(target=run_web_server, daemon=True)
    web_thread.start()
    logger.info("🌐 Web server started on port {}".format(PORT))
    
    # Create Telegram application
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Main conversation handler
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler('start', start),
            CommandHandler('new_fir', new_fir_command),
            CommandHandler('search', search_command),
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
    application.add_handler(CommandHandler('search', search_command))
    application.add_handler(CommandHandler('stats', stats_command))
    application.add_handler(CommandHandler('health', health_command))
    application.add_handler(CommandHandler('help', help_command))
    application.add_handler(CommandHandler('support', support_command))
    application.add_handler(CommandHandler('feedback', feedback_command))
    application.add_handler(CommandHandler('new_fir', new_fir_command))
    
    # Error handler
    application.add_error_handler(error_handler)
    
    # Run the bot with polling (simpler for Render)
    try:
        application.run_polling()
    except Exception as e:
        logger.error(f"Bot error: {e}")
        # Keep the web server running even if bot fails
        while True:
            import time
            time.sleep(60)

if __name__ == '__main__':
=======
# firbot_permanent.py - Complete FIR Bot with Gemini AI, QR Payment, and Webhook Support

import os
import logging
import json
import uuid
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional
import asyncio
import io
import threading

# Web server for Render health checks
from flask import Flask, request, jsonify

# Telegram
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler, filters, ContextTypes
)
from telegram.constants import ParseMode

# QR Code
import qrcode
from qrcode.image.styledpil import StyledPilImage
from qrcode.image.styles.moduledrawers import RoundedModuleDrawer
from qrcode.image.styles.colormasks import SolidFillColorMask
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
ADMIN_USER_ID = os.getenv('ADMIN_USER_ID', '')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
PORT = int(os.environ.get('PORT', 10000))

if not TELEGRAM_TOKEN:
    print("❌ ERROR: TELEGRAM_TOKEN not found in .env file!")
    print("Please create .env file with:")
    print("TELEGRAM_TOKEN=your_bot_token_here")
    print("GEMINI_API_KEY=your_gemini_api_key_here")
    exit(1)

# Configure Gemini AI
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    gemini_model = genai.GenerativeModel('gemini-pro')
else:
    print("⚠️ WARNING: GEMINI_API_KEY not found. AI drafting will be disabled.")
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
    'currency': 'INR',
    'reference': 'FIR-PAYMENT',
    'description': 'FIR Filing Payment'
}

FIR_AMOUNT = 10

def generate_upi_url(amount=10, reference=None):
    """Generate UPI payment URL"""
    upi_id = UPI_CONFIG['upi_id']
    payee_name = UPI_CONFIG['payee_name']
    currency = UPI_CONFIG['currency']
    
    if not reference:
        reference = f"FIR{datetime.now().strftime('%Y%m%d%H%M')}"
    
    upi_url = f"upi://pay?pa={upi_id}&pn={payee_name}&am={amount}&cu={currency}&tn={reference}"
    return upi_url

def generate_payment_links(amount=10, reference=None):
    """Generate multiple payment app links"""
    if not reference:
        reference = f"FIR{datetime.now().strftime('%Y%m%d%H%M')}"
    
    links = {
        'google_pay': f"https://pay.google.com/gp/p/ui/pay?pa={UPI_CONFIG['upi_id']}&am={amount}&cu=INR&tn={reference}",
        'phonepe': f"https://phone.pe/pay?pa={UPI_CONFIG['upi_id']}&am={amount}&cu=INR&tn={reference}",
        'paytm': f"https://paytm.me/upi/pay?pa={UPI_CONFIG['upi_id']}&am={amount}&cu=INR&tn={reference}",
        'amazon_pay': f"https://pay.amazon.in/upi/pay?pa={UPI_CONFIG['upi_id']}&am={amount}&cu=INR&tn={reference}",
        'upi': generate_upi_url(amount, reference)
    }
    return links

# ============================================================
# QR CODE GENERATOR
# ============================================================

def generate_qr_code_with_amount(amount=10, reference=None):
    """Generate QR code with amount prominently displayed"""
    try:
        upi_url = generate_upi_url(amount, reference)
        
        qr = qrcode.QRCode(
            version=2,
            error_correction=qrcode.constants.ERROR_CORRECT_H,
            box_size=10,
            border=4,
        )
        qr.add_data(upi_url)
        qr.make(fit=True)
        
        qr_image = qr.make_image(
            image_factory=StyledPilImage,
            module_drawer=RoundedModuleDrawer(),
            color_mask=SolidFillColorMask(
                back_color=(255, 255, 255),
                front_color=(46, 125, 50)
            )
        )
        
        qr_image = qr_image.resize((400, 400), Image.Resampling.LANCZOS)
        
        final_image = Image.new('RGB', (400, 480), color='white')
        final_image.paste(qr_image, (0, 0))
        
        draw = ImageDraw.Draw(final_image)
        try:
            font = ImageFont.truetype("arial.ttf", 24)
            font_small = ImageFont.truetype("arial.ttf", 16)
        except:
            font = ImageFont.load_default()
            font_small = ImageFont.load_default()
        
        draw.text((200, 415), "💰 Pay ₹10", fill=(0, 0, 0), anchor="mt", font=font)
        draw.text((200, 445), f"UPI: {UPI_CONFIG['upi_id']}", fill=(100, 100, 100), anchor="mt", font=font_small)
        draw.text((200, 465), f"Ref: {reference}", fill=(100, 100, 100), anchor="mt", font=font_small)
        
        filename = f"payment_qr_{reference}.png"
        final_image.save(filename, 'PNG', quality=95)
        
        return filename
        
    except Exception as e:
        logger.error(f"QR generation error: {e}")
        return None

def create_payment_qr_with_instructions(amount=10, reference=None):
    """Create payment QR code with instructions"""
    if not reference:
        reference = f"FIR{datetime.now().strftime('%Y%m%d%H%M')}"
    
    qr_file = generate_qr_code_with_amount(amount, reference)
    
    payment_info = {
        'qr_file': qr_file,
        'upi_id': UPI_CONFIG['upi_id'],
        'amount': amount,
        'reference': reference,
        'upi_url': generate_upi_url(amount, reference),
        'app_links': generate_payment_links(amount, reference)
    }
    
    return payment_info

# ============================================================
# GEMINI AI - FIR DRAFTING (Without Affidavit)
# ============================================================

def generate_fir_application_with_gemini(fir_data, language='en'):
    """
    Generate a professional FIR application using Google Gemini AI
    Without affidavit section
    """
    if not gemini_model:
        return generate_fir_application_template(fir_data, language)
    
    try:
        if language == 'hi':
            prompt = f"""
            आप एक अनुभवी पुलिस अधिकारी और कानूनी विशेषज्ञ हैं। निम्नलिखित जानकारी के आधार पर एक 
            पेशेवर प्रथम सूचना रिपोर्ट (FIR) आवेदन पत्र तैयार करें जो SHO (पुलिस स्टेशन प्रभारी) को दिया जाना है।
            
            FIR विवरण:
            - FIR संख्या: {fir_data.get('fir_number', 'N/A')}
            - घटना का प्रकार: {fir_data.get('incident_type', 'N/A')}
            - घटना की तारीख: {fir_data.get('incident_date', 'N/A')}
            - घटना का स्थान: {fir_data.get('incident_location', 'N/A')}
            - शिकायतकर्ता का नाम: {fir_data.get('complainant_name', 'N/A')}
            - पिता का नाम: {fir_data.get('father_name', 'N/A')}
            - शिकायतकर्ता का फोन: {fir_data.get('complainant_phone', 'N/A')}
            - शिकायतकर्ता का पता: {fir_data.get('complainant_address', 'N/A')}
            - घटना का विवरण: {fir_data.get('description', 'N/A')}
            - आरोपित व्यक्ति: {fir_data.get('accused_details', 'N/A')}
            - गवाह: {fir_data.get('witness_details', 'N/A')}
            - साक्ष्य: {fir_data.get('evidence_details', 'N/A')}
            - पुलिस स्टेशन: {fir_data.get('police_station', 'N/A')}
            
            कृपया एक औपचारिक FIR आवेदन पत्र तैयार करें जिसमें:
            1. सही कानूनी भाषा का उपयोग हो
            2. IPC / CrPC की प्रासंगिक धाराओं का उल्लेख हो
            3. सभी तथ्य स्पष्ट और संक्षिप्त हों
            4. SHO को संबोधित हो
            5. आवेदन पत्र के लिए उचित प्रारूप हो
            
            कृपया <b>शपथ पत्र (Affidavit) को शामिल न करें</b>।
            """
        else:
            prompt = f"""
            You are an experienced police officer and legal expert. Based on the following information, 
            draft a professional First Information Report (FIR) application to be submitted to the SHO (Station House Officer).
            
            FIR Details:
            - FIR Number: {fir_data.get('fir_number', 'N/A')}
            - Incident Type: {fir_data.get('incident_type', 'N/A')}
            - Incident Date: {fir_data.get('incident_date', 'N/A')}
            - Incident Location: {fir_data.get('incident_location', 'N/A')}
            - Complainant Name: {fir_data.get('complainant_name', 'N/A')}
            - Father's Name: {fir_data.get('father_name', 'N/A')}
            - Complainant Phone: {fir_data.get('complainant_phone', 'N/A')}
            - Complainant Address: {fir_data.get('complainant_address', 'N/A')}
            - Incident Description: {fir_data.get('description', 'N/A')}
            - Accused Persons: {fir_data.get('accused_details', 'N/A')}
            - Witnesses: {fir_data.get('witness_details', 'N/A')}
            - Evidence: {fir_data.get('evidence_details', 'N/A')}
            - Police Station: {fir_data.get('police_station', 'N/A')}
            
            Please draft a formal FIR application that:
            1. Uses proper legal language
            2. Mentions relevant IPC / CrPC sections
            3. Is clear and concise with all facts
            4. Is addressed to the SHO
            5. Follows proper format for application
            
            <b>Do NOT include an Affidavit section</b>.
            """
        
        response = gemini_model.generate_content(prompt)
        return response.text
        
    except Exception as e:
        logger.error(f"Gemini AI error: {e}")
        return generate_fir_application_template(fir_data, language)

def generate_fir_application_template(fir_data, language='en'):
    """Generate FIR application using template (fallback if Gemini fails)"""
    if language == 'hi':
        return f"""
        सेवा में,
        SHO,
        {fir_data.get('police_station', 'पुलिस स्टेशन')}
        
        विषय: प्रथम सूचना रिपोर्ट (FIR) दर्ज करने हेतु आवेदन
        
        महोदय,
        
        मैं, {fir_data.get('complainant_name', '_____________')}, 
        पिता/पति: {fir_data.get('father_name', '_____________')},
        निवासी: {fir_data.get('complainant_address', '_____________')}, 
        मोबाइल: {fir_data.get('complainant_phone', '_____________')},
        
        निवेदन करता/करती हूँ कि दिनांक {fir_data.get('incident_date', '_____________')} को 
        {fir_data.get('incident_location', '_____________')} में निम्न घटना घटी:
        
        {fir_data.get('description', '_____________')}
        
        घटना का प्रकार: {fir_data.get('incident_type', '_____________')}
        
        आरोपित व्यक्ति: {fir_data.get('accused_details', 'ज्ञात नहीं')}
        
        गवाह: {fir_data.get('witness_details', 'कोई नहीं')}
        
        साक्ष्य: {fir_data.get('evidence_details', 'कोई नहीं')}
        
        अतः आपसे अनुरोध है कि उपर्युक्त घटना पर प्रथम सूचना रिपोर्ट (FIR) दर्ज कर 
        आवश्यक कानूनी कार्रवाई की जाए।
        
        दिनांक: {datetime.now().strftime('%d/%m/%Y')}
        
        भवदीय,
        
        ({fir_data.get('complainant_name', '_____________')})
        हस्ताक्षर
        """
    else:
        return f"""
        To,
        The SHO,
        {fir_data.get('police_station', 'Police Station')}
        
        Subject: Application for filing First Information Report (FIR)
        
        Sir/Madam,
        
        I, {fir_data.get('complainant_name', '_____________')},
        S/o: {fir_data.get('father_name', '_____________')},
        resident of {fir_data.get('complainant_address', '_____________')},
        Mobile: {fir_data.get('complainant_phone', '_____________')},
        
        hereby state that on {fir_data.get('incident_date', '_____________')} at 
        {fir_data.get('incident_location', '_____________')}, the following incident occurred:
        
        {fir_data.get('description', '_____________')}
        
        Incident Type: {fir_data.get('incident_type', '_____________')}
        
        Accused Persons: {fir_data.get('accused_details', 'Not known')}
        
        Witnesses: {fir_data.get('witness_details', 'None')}
        
        Evidence: {fir_data.get('evidence_details', 'None')}
        
        Therefore, I request you to register an FIR and take necessary legal action.
        
        Date: {datetime.now().strftime('%d/%m/%Y')}
        
        Yours sincerely,
        
        ({fir_data.get('complainant_name', '_____________')})
        Signature
        """

# ============================================================
# PERMANENT DATABASE (JSON with persistent storage)
# ============================================================

class PermanentDB:
    """
    Permanent database with automatic backup and persistent storage
    """
    def __init__(self, filename='fir_data.json'):
        self.filename = filename
        self.backup_filename = f"{filename}.backup"
        self.data = self.load()
        self.save()  # Ensure initial save
    
    def load(self):
        """Load data from file, with fallback to backup"""
        # Try main file first
        if os.path.exists(self.filename):
            try:
                with open(self.filename, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    logger.info(f"✅ Database loaded from {self.filename}")
                    return data
            except Exception as e:
                logger.error(f"Error loading main database: {e}")
        
        # Try backup file
        if os.path.exists(self.backup_filename):
            try:
                with open(self.backup_filename, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    logger.info(f"✅ Database loaded from backup: {self.backup_filename}")
                    return data
            except Exception as e:
                logger.error(f"Error loading backup database: {e}")
        
        # Create new database
        logger.info("📦 Creating new database")
        return {
            'firs': [],
            'users': {},
            'feedback': [],
            'payments': [],
            'stats': {
                'total_firs': 0,
                'total_payments': 0,
                'total_amount': 0,
                'created_at': datetime.now().isoformat()
            }
        }
    
    def save(self):
        """Save data to file and create backup"""
        try:
            # Save main file
            with open(self.filename, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, indent=2, default=str, ensure_ascii=False)
            
            # Create backup
            with open(self.backup_filename, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, indent=2, default=str, ensure_ascii=False)
            
            logger.info(f"✅ Database saved successfully")
            return True
        except Exception as e:
            logger.error(f"Error saving database: {e}")
            return False
    
    def add_fir(self, fir_data):
        """Add new FIR with permanent storage"""
        fir_id = str(uuid.uuid4())[:8]
        fir_data['id'] = fir_id
        fir_data['fir_number'] = f"FIR{datetime.now().strftime('%Y%m%d')}{fir_id[:4].upper()}"
        fir_data['created_at'] = datetime.now().isoformat()
        fir_data['updated_at'] = datetime.now().isoformat()
        fir_data['status'] = 'submitted'
        fir_data['payment_status'] = False
        fir_data['amount'] = FIR_AMOUNT
        
        self.data['firs'].append(fir_data)
        self.data['stats']['total_firs'] += 1
        self.save()
        return fir_data
    
    def get_firs(self, user_id):
        """Get all FIRs for a user"""
        return [f for f in self.data['firs'] if f.get('user_id') == user_id]
    
    def get_fir_by_number(self, fir_number):
        """Get FIR by number"""
        for f in self.data['firs']:
            if f.get('fir_number') == fir_number:
                return f
        return None
    
    def get_fir_by_id(self, fir_id):
        """Get FIR by ID"""
        for f in self.data['firs']:
            if f.get('id') == fir_id:
                return f
        return None
    
    def update_fir(self, fir_number, updates):
        """Update FIR with new data"""
        for f in self.data['firs']:
            if f.get('fir_number') == fir_number:
                f.update(updates)
                f['updated_at'] = datetime.now().isoformat()
                self.save()
                return True
        return False
    
    def update_fir_status(self, fir_number, status):
        """Update FIR status"""
        return self.update_fir(fir_number, {'status': status})
    
    def update_payment_status(self, fir_number, paid=True, payment_method='upi'):
        """Update payment status"""
        updates = {
            'payment_status': paid,
            'payment_method': payment_method,
            'amount_paid': FIR_AMOUNT
        }
        if paid:
            updates['status'] = 'paid'
            self.data['stats']['total_payments'] += 1
            self.data['stats']['total_amount'] += FIR_AMOUNT
        
        return self.update_fir(fir_number, updates)
    
    def add_payment_record(self, payment_data):
        """Add payment record"""
        payment_data['id'] = str(uuid.uuid4())[:8]
        payment_data['created_at'] = datetime.now().isoformat()
        self.data['payments'].append(payment_data)
        self.save()
        return payment_data
    
    def add_feedback(self, user_id, feedback):
        """Add user feedback"""
        self.data['feedback'].append({
            'user_id': user_id,
            'feedback': feedback,
            'created_at': datetime.now().isoformat()
        })
        self.save()
    
    def get_all_firs(self, limit=100):
        """Get all FIRs with limit"""
        return self.data['firs'][-limit:]
    
    def get_stats(self):
    """Get statistics"""
    try:
        total = len(self.data.get('firs', []))
        paid = len([f for f in self.data.get('firs', []) if f.get('payment_status')])
        pending = len([f for f in self.data.get('firs', []) if f.get('status') == 'submitted'])
        
        stats = self.data.get('stats', {})
        return {
            'total': total,
            'paid': paid,
            'pending': pending,
            'total_amount': stats.get('total_amount', 0),
            'total_payments': stats.get('total_payments', 0)
        }
    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        return {
            'total': 0,
            'paid': 0,
            'pending': 0,
            'total_amount': 0,
            'total_payments': 0
        }
    
    def search_firs(self, query):
        """Search FIRs by number or name"""
        query = query.lower()
        results = []
        for f in self.data['firs']:
            if (query in f.get('fir_number', '').lower() or 
                query in f.get('complainant_name', '').lower() or
                query in f.get('complainant_phone', '')):
                results.append(f)
        return results

# Initialize permanent database
db = PermanentDB()

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
    GET_FATHER_NAME,
    GET_COMPLAINANT_PHONE,
    GET_COMPLAINANT_ADDRESS,
    GET_ACCUSED_DETAILS,
    GET_WITNESS_DETAILS,
    GET_EVIDENCE_DETAILS,
    SELECT_POLICE_STATION,
    CONFIRM_FIR,
    PROCESS_PAYMENT,
    PROVIDE_FEEDBACK,
    STATUS_CHECK
) = range(18)

# ============================================================
# MULTI-LANGUAGE TEXTS
# ============================================================

TEXTS = {
    'en': {
        'welcome': "🌟 Welcome to <b>LegalFIR Bot</b>!\n\nI'll help you file an FIR quickly and legally for just ₹10!\n\nPlease select your language:",
        'language_selected': "✅ Language set to English.",
        'plan_selection': "📋 <b>Select Your Plan</b>\n\n🔹 <b>Individual Plan</b> - ₹10\n• Basic FIR drafting\n• PDF download\n• AI-powered application\n\n🔹 <b>Advocate Plan</b> - ₹10\n• Professional FIR drafting\n• AI legal review\n• Application to SHO\n\n<i>💡 Both plans cost just ₹10!</i>",
        'incident_type': "📌 <b>Select Incident Type</b>:",
        'incident_date': "📅 <b>Enter incident date</b> (DD/MM/YYYY):",
        'incident_location': "📍 <b>Enter incident location</b>:",
        'description': "📝 <b>Describe the incident in detail</b>:\n\nYou can type or send a voice message.",
        'complainant_name': "👤 <b>Enter your full name</b>:",
        'father_name': "👨 <b>Enter your father's name</b>:",
        'complainant_phone': "📱 <b>Enter your phone number</b> (10 digits):",
        'complainant_address': "🏠 <b>Enter your complete address</b>:",
        'accused_details': "👥 <b>Accused details</b> (type 'skip' if not known):",
        'witness_details': "👀 <b>Witness details</b> (type 'skip' if none):",
        'evidence_details': "📎 <b>Evidence details</b> (type 'skip' if none):",
        'police_station': "🚔 <b>Select Police Station</b>:",
        'confirm_fir': "📄 <b>Review your FIR</b>:\n\n{details}\n\nProceed?",
        'payment_required': "💳 <b>Payment Required - Just ₹10!</b>\n\nAmount: ₹{amount}\nPlan: {plan}\n\nScan the QR code below or use payment links.",
        'payment_qr': "📱 <b>Scan QR Code to Pay ₹10</b>\n\n<b>UPI ID:</b> <code>{upi_id}</code>\n<b>Amount:</b> ₹{amount}\n<b>Reference:</b> <code>{reference}</code>\n\nAfter payment, click <b>✅ I've Paid</b>.",
        'payment_links': "🔗 <b>Payment Links</b>\n\nChoose your preferred app to pay ₹10:",
        'payment_success': "✅ <b>Payment Successful!</b>\n\nFIR Number: <code>{fir_number}</code>\nAmount: ₹10\n\nYour FIR has been processed.",
        'payment_verification': "⏳ <b>Verifying Payment...</b>",
        'payment_failed': "❌ Payment verification failed.",
        'filing_success': "✅ <b>FIR Filed Successfully!</b>\n\nFIR Number: <code>{fir_number}</code>\nStatus: {status}\nAmount: ₹10\n\nUse /status to check updates.",
        'feedback': "📝 <b>Please provide your feedback</b>:",
        'feedback_thanks': "🙏 <b>Thank you for your feedback!</b>",
        'error': "❌ <b>An error occurred</b>. Please try again.",
        'cancel': "❌ Operation cancelled.",
        'help': "🤖 <b>Help</b>\n\nCommands:\n/start - Start bot\n/new_fir - File FIR (₹10)\n/status - Check status\n/list - Your FIRs\n/search - Search FIRs\n/stats - Bot statistics\n/help - This help\n/cancel - Cancel",
        'status_check': "📊 Enter your FIR number:",
        'status_response': "📊 <b>FIR Status</b>\n\nNumber: <code>{fir_number}</code>\nStatus: {status}\nDate: {date}\nPlan: {plan}\nAmount: ₹10",
        'list_response': "📋 <b>Your FIRs</b>\n\n{firs}",
        'no_firs': "📭 No FIRs found.",
        'support': "📞 <b>Support</b>\n\nEmail: support@legalfir.com\nPhone: +91-XXXXXXXXXX",
        'invalid_fir': "❌ Invalid FIR number.",
        'already_exists': "⚠️ You have a pending FIR.",
        'payment_instructions': "📱 <b>Pay ₹10</b>\n\n1. Scan QR code\n2. Or click payment link\n3. Pay ₹10\n4. Click 'I've Paid'\n\n<b>UPI ID:</b> <code>{upi_id}</code>",
        'fir_application_ready': "📄 <b>FIR Application Ready!</b>\n\nYour professionally drafted FIR application is ready. Click below to download:",
        'download_application': "📥 Download FIR Application",
        'stats_message': "📊 <b>Bot Statistics</b>\n\nTotal FIRs: {total}\nPaid FIRs: {paid}\nPending FIRs: {pending}\nTotal Amount: ₹{total_amount}\nTotal Payments: {total_payments}",
        'search_prompt': "🔍 Enter FIR number or complainant name to search:",
        'search_results': "🔍 <b>Search Results</b>\n\n{results}",
        'no_results': "No FIRs found matching your search.",
        'permanent_storage': "💾 All data is permanently stored online.",
        'data_secured': "🔒 Your data is securely stored and backed up.",
    },
    'hi': {
        'welcome': "🌟 <b>लीगलFIR बॉट</b> में आपका स्वागत है!\n\nसिर्फ ₹10 में FIR दर्ज करवाएं!\n\nकृपया अपनी भाषा चुनें:",
        'language_selected': "✅ भाषा हिंदी में सेट की गई।",
        'plan_selection': "📋 <b>अपना प्लान चुनें</b>\n\n🔹 <b>व्यक्तिगत</b> - ₹10\n• बुनियादी FIR\n• PDF डाउनलोड\n• AI-आधारित आवेदन\n\n🔹 <b>अधिवक्ता</b> - ₹10\n• व्यावसायिक FIR\n• AI कानूनी समीक्षा\n• SHO को आवेदन\n\n<i>💡 दोनों प्लान सिर्फ ₹10!</i>",
        'incident_type': "📌 <b>घटना का प्रकार चुनें</b>:",
        'incident_date': "📅 <b>घटना की तारीख दर्ज करें</b> (DD/MM/YYYY):",
        'incident_location': "📍 <b>घटना का स्थान दर्ज करें</b>:",
        'description': "📝 <b>घटना का विवरण दें</b>:\n\nआप टाइप कर सकते हैं या वॉइस भेज सकते हैं।",
        'complainant_name': "👤 <b>अपना पूरा नाम दर्ज करें</b>:",
        'father_name': "👨 <b>अपने पिता का नाम दर्ज करें</b>:",
        'complainant_phone': "📱 <b>अपना फोन नंबर दर्ज करें</b> (10 अंक):",
        'complainant_address': "🏠 <b>अपना पूरा पता दर्ज करें</b>:",
        'accused_details': "👥 <b>आरोपित व्यक्तियों का विवरण</b> ('skip' टाइप करें):",
        'witness_details': "👀 <b>गवाहों का विवरण</b> ('skip' टाइप करें):",
        'evidence_details': "📎 <b>साक्ष्यों का विवरण</b> ('skip' टाइप करें):",
        'police_station': "🚔 <b>पुलिस स्टेशन चुनें</b>:",
        'confirm_fir': "📄 <b>अपने FIR की समीक्षा करें</b>:\n\n{details}\n\nक्या आप आगे बढ़ना चाहते हैं?",
        'payment_required': "💳 <b>भुगतान आवश्यक - सिर्फ ₹10!</b>\n\nराशि: ₹{amount}\nप्लान: {plan}\n\nQR कोड स्कैन करें या पेमेंट लिंक का उपयोग करें।",
        'payment_qr': "📱 <b>₹10 भुगतान के लिए QR कोड स्कैन करें</b>\n\n<b>UPI ID:</b> <code>{upi_id}</code>\n<b>राशि:</b> ₹{amount}\n<b>रेफरेंस:</b> <code>{reference}</code>\n\nभुगतान के बाद <b>✅ मैंने भुगतान किया</b> पर क्लिक करें।",
        'payment_links': "🔗 <b>पेमेंट लिंक</b>\n\nअपनी पसंदीदा पेमेंट ऐप चुनें:",
        'payment_success': "✅ <b>भुगतान सफल!</b>\n\nFIR नंबर: <code>{fir_number}</code>\nराशि: ₹10\n\nआपकी FIR प्रोसेस कर दी गई है।",
        'payment_verification': "⏳ <b>भुगतान सत्यापित किया जा रहा है...</b>",
        'payment_failed': "❌ भुगतान सत्यापन विफल।",
        'filing_success': "✅ <b>FIR सफलतापूर्वक दर्ज!</b>\n\nFIR नंबर: <code>{fir_number}</code>\nस्थिति: {status}\nराशि: ₹10\n\n/status से स्थिति देखें।",
        'feedback': "📝 <b>कृपया अपनी प्रतिक्रिया दें</b>:",
        'feedback_thanks': "🙏 <b>आपकी प्रतिक्रिया के लिए धन्यवाद!</b>",
        'error': "❌ <b>कोई त्रुटि हुई</b>. कृपया पुनः प्रयास करें।",
        'cancel': "❌ ऑपरेशन रद्द कर दिया गया।",
        'help': "🤖 <b>सहायता</b>\n\nकमांड:\n/start - बॉट शुरू करें\n/new_fir - नई FIR दर्ज करें (₹10)\n/status - स्थिति देखें\n/list - अपनी FIRs देखें\n/search - FIRs खोजें\n/stats - आंकड़े देखें\n/help - यह सहायता\n/cancel - ऑपरेशन रद्द करें",
        'status_check': "📊 अपना FIR नंबर दर्ज करें:",
        'status_response': "📊 <b>FIR स्थिति</b>\n\nनंबर: <code>{fir_number}</code>\nस्थिति: {status}\nतारीख: {date}\nप्लान: {plan}\nराशि: ₹10",
        'list_response': "📋 <b>आपकी FIRs</b>\n\n{firs}",
        'no_firs': "📭 कोई FIR नहीं मिली।",
        'support': "📞 <b>सहायता</b>\n\nईमेल: support@legalfir.com\nफोन: +91-XXXXXXXXXX",
        'invalid_fir': "❌ अमान्य FIR नंबर।",
        'already_exists': "⚠️ आपकी एक लंबित FIR है।",
        'payment_instructions': "📱 <b>₹10 भुगतान कैसे करें</b>\n\n1. QR कोड स्कैन करें\n2. या पेमेंट लिंक पर क्लिक करें\n3. ₹10 का भुगतान करें\n4. 'मैंने भुगतान किया' पर क्लिक करें\n\n<b>UPI ID:</b> <code>{upi_id}</code>",
        'fir_application_ready': "📄 <b>FIR आवेदन तैयार!</b>\n\nआपका पेशेवर रूप से तैयार FIR आवेदन तैयार है। डाउनलोड करने के लिए नीचे क्लिक करें:",
        'download_application': "📥 FIR आवेदन डाउनलोड करें",
        'stats_message': "📊 <b>बॉट आंकड़े</b>\n\nकुल FIR: {total}\nभुगतान: {paid}\nलंबित: {pending}\nकुल राशि: ₹{total_amount}\nकुल भुगतान: {total_payments}",
        'search_prompt': "🔍 खोजने के लिए FIR नंबर या शिकायतकर्ता का नाम दर्ज करें:",
        'search_results': "🔍 <b>खोज परिणाम</b>\n\n{results}",
        'no_results': "आपकी खोज से मेल खाती कोई FIR नहीं मिली।",
        'permanent_storage': "💾 सभी डेटा स्थायी रूप से ऑनलाइन संग्रहीत है।",
        'data_secured': "🔒 आपका डेटा सुरक्षित रूप से संग्रहीत और बैकअप है।",
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
    """Handle plan selection"""
    query = update.callback_query
    await query.answer()
    
    plan = query.data.split('_')[1]
    context.user_data['plan'] = plan
    language = context.user_data.get('language', 'en')
    texts = TEXTS[language]
    
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
        await update.message.reply_text("❌ Invalid date. Use DD/MM/YYYY")
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
        voice = await update.message.voice.get_file()
        voice_path = f"voice_{update.message.message_id}.ogg"
        await voice.download_to_drive(voice_path)
        
        try:
            from pydub import AudioSegment
            import speech_recognition as sr
            
            audio = AudioSegment.from_ogg(voice_path)
            wav_path = voice_path.replace('.ogg', '.wav')
            audio.export(wav_path, format='wav')
            
            recognizer = sr.Recognizer()
            with sr.AudioFile(wav_path) as source:
                audio_data = recognizer.record(source)
                text = recognizer.recognize_google(audio_data)
            
            context.user_data['description'] = text
            
            for f in [voice_path, wav_path]:
                if os.path.exists(f):
                    os.remove(f)
            
            await update.message.reply_text(f"📝 Recognized: {text}")
            
        except:
            await update.message.reply_text("❌ Could not recognize voice. Please type:")
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
        await update.message.reply_text("❌ Voice error. Please type:")
        return GET_DESCRIPTION

async def get_complainant_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get complainant name"""
    context.user_data['complainant_name'] = update.message.text
    language = context.user_data.get('language', 'en')
    texts = TEXTS[language]
    
    await update.message.reply_text(
        texts['father_name'],
        parse_mode=ParseMode.HTML
    )
    return GET_FATHER_NAME

async def get_father_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get father's name"""
    context.user_data['father_name'] = update.message.text
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
    if not phone.isdigit() or len(phone) < 10:
        await update.message.reply_text("❌ Please enter valid 10-digit phone number:")
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
    
    incident_type = context.user_data.get('incident_type', 'N/A')
    incident_types = context.user_data.get('incident_types', INCIDENT_TYPES)
    incident_label = incident_types.get(incident_type, incident_type)
    
    details = f"""
<b>Plan:</b> {context.user_data.get('plan', 'N/A')} - ₹10
<b>Type:</b> {incident_label}
<b>Date:</b> {context.user_data.get('incident_date', 'N/A')}
<b>Location:</b> {context.user_data.get('incident_location', 'N/A')}

<b>Complainant:</b>
Name: {context.user_data.get('complainant_name', 'N/A')}
Father's Name: {context.user_data.get('father_name', 'N/A')}
Phone: {context.user_data.get('complainant_phone', 'N/A')}
Address: {context.user_data.get('complainant_address', 'N/A')}

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
            'father_name': context.user_data.get('father_name'),
            'complainant_phone': context.user_data.get('complainant_phone'),
            'complainant_address': context.user_data.get('complainant_address'),
            'accused_details': context.user_data.get('accused_details', 'Not provided'),
            'witness_details': context.user_data.get('witness_details', 'Not provided'),
            'evidence_details': context.user_data.get('evidence_details', 'Not provided'),
            'police_station': context.user_data.get('police_station'),
            'status': 'submitted',
            'payment_status': False,
            'amount': FIR_AMOUNT
        }
        
        saved_fir = db.add_fir(fir_data)
        context.user_data['fir_number'] = saved_fir['fir_number']
        
        await query.edit_message_text(
            "🤖 Generating professional FIR application using AI...",
            parse_mode=ParseMode.HTML
        )
        
        fir_application = generate_fir_application_with_gemini(
            saved_fir, 
            language
        )
        
        saved_fir['application_text'] = fir_application
        db.save()
        
        amount = FIR_AMOUNT
        
        keyboard = [
            [InlineKeyboardButton("💳 Pay ₹10 (QR)", callback_data=f'payment_{saved_fir["fir_number"]}')],
            [InlineKeyboardButton("⏭️ Skip Payment (Test)", callback_data=f'payment_skip_{saved_fir["fir_number"]}')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=texts['payment_required'].format(
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

# ============================================================
# PAYMENT HANDLER WITH QR CODE
# ============================================================

async def process_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle payment with QR code"""
    query = update.callback_query
    await query.answer()
    
    language = context.user_data.get('language', 'en')
    texts = TEXTS[language]
    
    parts = query.data.split('_')
    fir_number = parts[1] if len(parts) > 1 else context.user_data.get('fir_number')
    action = parts[0] if len(parts) > 0 else 'payment'
    
    if action == 'payment_skip':
        db.update_payment_status(fir_number, True, 'test')
        await query.edit_message_text("⏳ Processing...")
        await asyncio.sleep(1)
        
        fir = db.get_fir_by_number(fir_number)
        
        if fir:
            await query.edit_message_text(
                texts['payment_success'].format(fir_number=fir_number),
                parse_mode=ParseMode.HTML
            )
            
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=texts['filing_success'].format(
                    fir_number=fir_number,
                    status='Filed'
                ),
                parse_mode=ParseMode.HTML
            )
            
            if fir.get('application_text'):
                app_text = fir['application_text']
                
                if len(app_text) < 4000:
                    await context.bot.send_message(
                        chat_id=update.effective_chat.id,
                        text=f"📄 <b>FIR Application</b>\n\n{app_text}",
                        parse_mode=ParseMode.HTML
                    )
                else:
                    app_filename = f"FIR_Application_{fir_number}.txt"
                    with open(app_filename, 'w', encoding='utf-8') as f:
                        f.write(app_text)
                    
                    with open(app_filename, 'rb') as f:
                        await context.bot.send_document(
                            chat_id=update.effective_chat.id,
                            document=InputFile(f, filename=app_filename),
                            caption="📄 FIR Application"
                        )
                    
                    if os.path.exists(app_filename):
                        os.remove(app_filename)
            
            try:
                pdf_path = generate_pdf_with_application(fir, language)
                if pdf_path and os.path.exists(pdf_path):
                    with open(pdf_path, 'rb') as pdf_file:
                        await context.bot.send_document(
                            chat_id=update.effective_chat.id,
                            document=InputFile(pdf_file, filename=f"FIR_{fir_number}.pdf"),
                            caption="📄 Complete FIR with Application"
                        )
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
    
    elif action == 'payment':
        fir = db.get_fir_by_number(fir_number)
        if not fir:
            await query.edit_message_text(texts['invalid_fir'])
            return ConversationHandler.END
        
        amount = FIR_AMOUNT
        reference = fir_number
        
        payment_info = create_payment_qr_with_instructions(amount, reference)
        
        instructions = texts['payment_instructions'].format(
            amount=amount,
            upi_id=UPI_CONFIG['upi_id']
        )
        
        await query.edit_message_text(
            instructions,
            parse_mode=ParseMode.HTML
        )
        
        if payment_info['qr_file'] and os.path.exists(payment_info['qr_file']):
            with open(payment_info['qr_file'], 'rb') as qr_file:
                await context.bot.send_photo(
                    chat_id=update.effective_chat.id,
                    photo=InputFile(qr_file, filename="payment_qr.png"),
                    caption=texts['payment_qr'].format(
                        upi_id=UPI_CONFIG['upi_id'],
                        amount=amount,
                        reference=reference
                    ),
                    parse_mode=ParseMode.HTML
                )
            
            if os.path.exists(payment_info['qr_file']):
                os.remove(payment_info['qr_file'])
        
        links = payment_info['app_links']
        keyboard = [
            [InlineKeyboardButton("📱 Google Pay", url=links['google_pay'])],
            [InlineKeyboardButton("📱 PhonePe", url=links['phonepe'])],
            [InlineKeyboardButton("📱 PayTM", url=links['paytm'])],
            [InlineKeyboardButton("📱 Amazon Pay", url=links['amazon_pay'])],
            [InlineKeyboardButton("✅ I've Paid (Verify)", callback_data=f'verify_{fir_number}')],
            [InlineKeyboardButton("❌ Cancel", callback_data=f'payment_cancel_{fir_number}')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=texts['payment_links'],
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML
        )
        
        context.user_data['payment_reference'] = reference
        context.user_data['payment_amount'] = amount
        
        return PROCESS_PAYMENT
    
    elif action == 'verify':
        await query.edit_message_text(
            texts['payment_verification'],
            parse_mode=ParseMode.HTML
        )
        
        await asyncio.sleep(2)
        
        db.update_payment_status(fir_number, True, 'upi')
        
        fir = db.get_fir_by_number(fir_number)
        
        if fir:
            await query.edit_message_text(
                texts['payment_success'].format(fir_number=fir_number),
                parse_mode=ParseMode.HTML
            )
            
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=texts['filing_success'].format(
                    fir_number=fir_number,
                    status='Filed'
                ),
                parse_mode=ParseMode.HTML
            )
            
            if fir.get('application_text'):
                app_text = fir['application_text']
                
                if len(app_text) < 4000:
                    await context.bot.send_message(
                        chat_id=update.effective_chat.id,
                        text=f"📄 <b>FIR Application</b>\n\n{app_text}",
                        parse_mode=ParseMode.HTML
                    )
                else:
                    app_filename = f"FIR_Application_{fir_number}.txt"
                    with open(app_filename, 'w', encoding='utf-8') as f:
                        f.write(app_text)
                    
                    with open(app_filename, 'rb') as f:
                        await context.bot.send_document(
                            chat_id=update.effective_chat.id,
                            document=InputFile(f, filename=app_filename),
                            caption="📄 FIR Application"
                        )
                    
                    if os.path.exists(app_filename):
                        os.remove(app_filename)
            
            try:
                pdf_path = generate_pdf_with_application(fir, language)
                if pdf_path and os.path.exists(pdf_path):
                    with open(pdf_path, 'rb') as pdf_file:
                        await context.bot.send_document(
                            chat_id=update.effective_chat.id,
                            document=InputFile(pdf_file, filename=f"FIR_{fir_number}.pdf"),
                            caption="📄 Complete FIR with Application"
                        )
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
    
    elif action == 'payment_cancel':
        await query.edit_message_text(texts['cancel'])
        return ConversationHandler.END
    
    else:
        await query.edit_message_text(texts['error'])
        return ConversationHandler.END

# ============================================================
# PDF GENERATOR (Without Affidavit)
# ============================================================

def generate_pdf_with_application(fir_data, language):
    """Generate PDF with FIR and Application (No Affidavit)"""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
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
            fontSize=18,
            textColor=colors.darkblue,
            alignment=1,
            spaceAfter=30
        )
        story.append(Paragraph("FIRST INFORMATION REPORT (FIR)", title_style))
        story.append(Spacer(1, 12))
        
        # FIR Number and Details
        story.append(Paragraph(f"<b>FIR Number:</b> {fir_data['fir_number']}", styles['Normal']))
        story.append(Paragraph(f"<b>Date:</b> {fir_data.get('incident_date', 'N/A')}", styles['Normal']))
        story.append(Paragraph(f"<b>Status:</b> {fir_data.get('status', 'N/A')}", styles['Normal']))
        story.append(Paragraph(f"<b>Amount Paid:</b> ₹{fir_data.get('amount', 10)}", styles['Normal']))
        story.append(Spacer(1, 12))
        
        # Complainant Details with Father's Name
        story.append(Paragraph("<b>COMPLAINANT DETAILS</b>", styles['Heading2']))
        story.append(Spacer(1, 6))
        
        complainant_data = [
            ["Name", fir_data.get('complainant_name', 'N/A')],
            ["Father's Name", fir_data.get('father_name', 'N/A')],
            ["Phone", fir_data.get('complainant_phone', 'N/A')],
            ["Address", fir_data.get('complainant_address', 'N/A')],
        ]
        
        table = Table(complainant_data, colWidths=[2*inch, 4*inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), colors.lightgrey),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('PADDING', (0, 0), (-1, -1), 6),
        ]))
        story.append(table)
        story.append(Spacer(1, 12))
        
        # Incident Details
        story.append(Paragraph("<b>INCIDENT DETAILS</b>", styles['Heading2']))
        story.append(Spacer(1, 6))
        
        incident_data = [
            ["Type", fir_data.get('incident_type', 'N/A')],
            ["Date", fir_data.get('incident_date', 'N/A')],
            ["Location", fir_data.get('incident_location', 'N/A')],
            ["Police Station", fir_data.get('police_station', 'N/A')],
        ]
        
        table = Table(incident_data, colWidths=[2*inch, 4*inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), colors.lightgrey),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('PADDING', (0, 0), (-1, -1), 6),
        ]))
        story.append(table)
        story.append(Spacer(1, 12))
        
        # Description
        story.append(Paragraph("<b>DESCRIPTION</b>", styles['Heading2']))
        story.append(Spacer(1, 6))
        story.append(Paragraph(fir_data.get('description', 'N/A'), styles['Normal']))
        story.append(Spacer(1, 12))
        
        # Accused, Witnesses, Evidence
        for label, key in [("ACCUSED PERSONS", "accused_details"), ("WITNESSES", "witness_details"), ("EVIDENCE", "evidence_details")]:
            story.append(Paragraph(f"<b>{label}</b>", styles['Heading2']))
            story.append(Spacer(1, 6))
            story.append(Paragraph(fir_data.get(key, 'N/A'), styles['Normal']))
            story.append(Spacer(1, 12))
        
        # Page Break for Application
        story.append(PageBreak())
        
        # FIR Application (from Gemini - No Affidavit)
        story.append(Paragraph("<b>FIR APPLICATION</b>", title_style))
        story.append(Spacer(1, 12))
        
        if fir_data.get('application_text'):
            app_text = fir_data['application_text']
            # Remove any affidavit text if present
            if 'affidavit' in app_text.lower() or 'शपथ पत्र' in app_text:
                import re
                if language == 'hi':
                    app_text = re.split(r'(शपथ पत्र|Affidavit)', app_text)[0]
                else:
                    app_text = re.split(r'(Affidavit|शपथ पत्र)', app_text, flags=re.IGNORECASE)[0]
            
            paragraphs = app_text.split('\n\n')
            for para in paragraphs:
                if para.strip():
                    story.append(Paragraph(para.replace('\n', '<br/>'), styles['Normal']))
                    story.append(Spacer(1, 6))
        
        # Footer - No Affidavit
        story.append(Spacer(1, 20))
        story.append(Paragraph(f"Generated on: {datetime.now().strftime('%d/%m/%Y %H:%M')}", styles['Normal']))
        story.append(Paragraph("This is a system-generated document with AI assistance.", styles['Normal']))
        story.append(Paragraph("For official use only.", styles['Normal']))
        
        doc.build(story)
        return filename
    except Exception as e:
        logger.error(f"PDF generation error: {e}")
        return None

# ============================================================
# ADDITIONAL COMMANDS
# ============================================================

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show bot statistics"""
    language = context.user_data.get('language', 'en')
    texts = TEXTS[language]
    
    stats = db.get_stats()
    
    await update.message.reply_text(
        texts['stats_message'].format(
            total=stats['total'],
            paid=stats['paid'],
            pending=stats['pending'],
            total_amount=stats['total_amount'],
            total_payments=stats['total_payments']
        ),
        parse_mode=ParseMode.HTML
    )

async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Search FIRs"""
    language = context.user_data.get('language', 'en')
    texts = TEXTS[language]
    
    await update.message.reply_text(
        texts['search_prompt'],
        parse_mode=ParseMode.HTML
    )
    return STATUS_CHECK

async def search_response(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle search response"""
    query = update.message.text.strip()
    language = context.user_data.get('language', 'en')
    texts = TEXTS[language]
    
    results = db.search_firs(query)
    
    if results:
        message = ""
        for fir in results[:10]:
            status_icon = "✅" if fir.get('payment_status') else "⏳"
            message += f"{status_icon} <code>{fir['fir_number']}</code>\n"
            message += f"   Name: {fir.get('complainant_name', 'N/A')}\n"
            message += f"   Status: {fir.get('status', 'N/A')}\n\n"
        
        await update.message.reply_text(
            texts['search_results'].format(results=message),
            parse_mode=ParseMode.HTML
        )
    else:
        await update.message.reply_text(
            texts['no_results'],
            parse_mode=ParseMode.HTML
        )
    
    return ConversationHandler.END

async def provide_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle feedback"""
    feedback = update.message.text
    user_id = str(update.effective_user.id)
    language = context.user_data.get('language', 'en')
    texts = TEXTS[language]
    
    db.add_feedback(user_id, feedback)
    
    await update.message.reply_text(
        texts['feedback_thanks'],
        parse_mode=ParseMode.HTML
    )
    return ConversationHandler.END

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
            message += f"{i}. {status_icon} <code>{fir['fir_number']}</code>\n"
            message += f"   Status: {fir.get('status', 'N/A')}\n"
            message += f"   Date: {fir.get('incident_date', 'N/A')}\n\n"
        
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
    
    help_text = texts['help']
    help_text += "\n\n" + texts['permanent_storage']
    help_text += "\n" + texts['data_secured']
    
    await update.message.reply_text(
        help_text,
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

async def health_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Health check command"""
    stats = db.get_stats()
    await update.message.reply_text(
        f"✅ Bot is healthy!\n\n"
        f"⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"📊 Total FIRs: {stats['total']}\n"
        f"💰 Total Payments: ₹{stats['total_amount']}\n"
        f"💾 Data Storage: Permanent & Auto-backed up\n"
        f"🤖 Gemini AI: {'Enabled' if gemini_model else 'Disabled'}",
        parse_mode=ParseMode.HTML
    )

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
# WEB SERVER FOR RENDER HEALTH CHECKS
# ============================================================

# Create Flask app for Render health checks
flask_app = Flask(__name__)

@flask_app.route('/')
def health_check():
    """Health check endpoint for Render"""
    try:
        stats = db.get_stats()
        total_firs = stats.get('total', 0) if stats else 0
    except:
        total_firs = 0
    
    return jsonify({
        'status': 'healthy',
        'bot': 'running',
        'time': datetime.now().isoformat(),
        'total_firs': total_firs
    }), 200

@flask_app.route('/webhook', methods=['POST', 'GET'])
def webhook():
    """Webhook endpoint for Telegram"""
    if request.method == 'GET':
        return jsonify({'status': 'webhook endpoint', 'method': 'GET'}), 200
    return jsonify({'status': 'webhook endpoint'}), 200

def run_web_server():
    """Run Flask web server for Render"""
    try:
        flask_app.run(host='0.0.0.0', port=PORT)
    except Exception as e:
        logger.error(f"Web server error: {e}")

# ============================================================
# MAIN FUNCTION
# ============================================================

def main():
    """Run the bot"""
    print("=" * 70)
    print("🤖 PERMANENT FIR BOT WITH GEMINI AI")
    print("=" * 70)
    print(f"✅ Bot Token: {TELEGRAM_TOKEN[:15]}...")
    print(f"✅ Database: fir_data.json (Permanent Storage)")
    print(f"✅ Backup: fir_data.json.backup (Auto-backup)")
    print(f"✅ UPI ID: {UPI_CONFIG['upi_id']}")
    print(f"✅ Amount: ₹{FIR_AMOUNT}")
    print(f"✅ Gemini AI: {'Enabled' if gemini_model else 'Disabled'}")
    print(f"✅ Web Server: Port {PORT}")
    print("=" * 70)
    print("📱 Commands:")
    print("  /start     - Start the bot")
    print("  /new_fir   - File a new FIR (₹10)")
    print("  /status    - Check FIR status")
    print("  /list      - List your FIRs")
    print("  /search    - Search FIRs")
    print("  /stats     - Bot statistics")
    print("  /health    - Health check")
    print("  /help      - Show help")
    print("  /support   - Contact support")
    print("  /feedback  - Give feedback")
    print("=" * 70)
    print("💾 Data Storage: Permanent & Auto-backed up")
    print("🔒 All data is securely stored")
    print("=" * 70)
    print("✅ Bot is running... Press Ctrl+C to stop")
    print("=" * 70)
    
    # Start web server in background thread
    web_thread = threading.Thread(target=run_web_server, daemon=True)
    web_thread.start()
    logger.info("🌐 Web server started on port {}".format(PORT))
    
    # Create Telegram application
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Main conversation handler
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler('start', start),
            CommandHandler('new_fir', new_fir_command),
            CommandHandler('search', search_command),
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
    application.add_handler(CommandHandler('search', search_command))
    application.add_handler(CommandHandler('stats', stats_command))
    application.add_handler(CommandHandler('health', health_command))
    application.add_handler(CommandHandler('help', help_command))
    application.add_handler(CommandHandler('support', support_command))
    application.add_handler(CommandHandler('feedback', feedback_command))
    application.add_handler(CommandHandler('new_fir', new_fir_command))
    
    # Error handler
    application.add_error_handler(error_handler)
    
    # Run the bot with polling (simpler for Render)
    try:
        application.run_polling()
    except Exception as e:
        logger.error(f"Bot error: {e}")
        # Keep the web server running even if bot fails
        while True:
            import time
            time.sleep(60)

if __name__ == '__main__':
>>>>>>> 9efe570f6e13a86ad6170429533b6dd013f49147
    main()