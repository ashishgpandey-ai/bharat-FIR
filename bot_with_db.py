# bot_with_db.py - Complete working example

import os
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, 
    CallbackQueryHandler, ConversationHandler, filters, ContextTypes
)
from dotenv import load_dotenv
from sqlalchemy import create_engine, Column, String, Integer, DateTime, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# Load .env file
load_dotenv()

# Configuration
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///fir_bot.db')

# Setup database
engine = create_engine(DATABASE_URL)
Base = declarative_base()

class FIR(Base):
    __tablename__ = 'firs'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(String(100))
    name = Column(String(200))
    phone = Column(String(20))
    incident_type = Column(String(100))
    description = Column(Text)
    status = Column(String(50), default='pending')
    created_at = Column(DateTime, default=datetime.utcnow)

# Create tables
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Conversation states
NAME, PHONE, INCIDENT, DESCRIPTION, CONFIRM = range(5)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command"""
    await update.message.reply_text(
        "🌟 Welcome to FIR Bot!\n\n"
        "I'll help you file a complaint. Let's get started!\n"
        "Send /new to file a new complaint."
    )

async def new_complaint(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start new complaint filing"""
    await update.message.reply_text("📝 What is your full name?")
    return NAME

async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get user name"""
    context.user_data['name'] = update.message.text
    await update.message.reply_text("📱 What is your phone number?")
    return PHONE

async def get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get user phone"""
    context.user_data['phone'] = update.message.text
    
    keyboard = [
        [InlineKeyboardButton("🚨 Theft", callback_data="theft")],
        [InlineKeyboardButton("⚔️ Assault", callback_data="assault")],
        [InlineKeyboardButton("🚗 Accident", callback_data="accident")],
        [InlineKeyboardButton("📝 Other", callback_data="other")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "Select incident type:",
        reply_markup=reply_markup
    )
    return INCIDENT

async def get_incident_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get incident type"""
    query = update.callback_query
    await query.answer()
    
    context.user_data['incident_type'] = query.data
    await query.edit_message_text("📝 Please describe what happened in detail:")
    return DESCRIPTION

async def get_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get incident description"""
    context.user_data['description'] = update.message.text
    
    # Show summary
    summary = f"""
📋 Complaint Summary:
------------------------
Name: {context.user_data['name']}
Phone: {context.user_data['phone']}
Type: {context.user_data['incident_type']}
Description: {context.user_data['description'][:100]}...

Do you want to submit this complaint?
    """
    
    keyboard = [
        [InlineKeyboardButton("✅ Submit", callback_data="submit")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(summary, reply_markup=reply_markup)
    return CONFIRM

async def confirm_submit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle submission confirmation"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "submit":
        # Save to database
        session = Session()
        fir = FIR(
            user_id=str(update.effective_user.id),
            name=context.user_data['name'],
            phone=context.user_data['phone'],
            incident_type=context.user_data['incident_type'],
            description=context.user_data['description']
        )
        session.add(fir)
        session.commit()
        fir_id = fir.id
        session.close()
        
        await query.edit_message_text(
            f"✅ Complaint submitted successfully!\n\n"
            f"Complaint ID: #{fir_id}\n"
            f"Status: Pending Review\n\n"
            f"We'll update you on the status soon."
        )
    else:
        await query.edit_message_text("❌ Complaint cancelled.")
    
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel conversation"""
    await update.message.reply_text("❌ Operation cancelled.")
    return ConversationHandler.END

async def list_complaints(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List user's complaints"""
    session = Session()
    complaints = session.query(FIR).filter_by(
        user_id=str(update.effective_user.id)
    ).all()
    session.close()
    
    if not complaints:
        await update.message.reply_text("📭 You have no complaints filed.")
        return
    
    message = "📋 Your Complaints:\n\n"
    for c in complaints:
        message += f"#{c.id} - {c.incident_type} - {c.status} - {c.created_at.strftime('%d/%m/%Y')}\n"
    
    await update.message.reply_text(message)

def main():
    """Run the bot"""
    # Create application
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Conversation handler
    conv = ConversationHandler(
        entry_points=[CommandHandler('new', new_complaint)],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_phone)],
            INCIDENT: [CallbackQueryHandler(get_incident_type)],
            DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_description)],
            CONFIRM: [CallbackQueryHandler(confirm_submit)]
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    
    app.add_handler(CommandHandler('start', start))
    app.add_handler(conv)
    app.add_handler(CommandHandler('list', list_complaints))
    
    print("🤖 Bot is starting...")
    print(f"📁 Database file: {DATABASE_URL.replace('sqlite:///', '')}")
    print("✅ Bot is running! Send /start to your bot in Telegram")
    
    app.run_polling()

if __name__ == '__main__':
    main()