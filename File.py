import os
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# Constants
BOT_TOKEN = "5681235797:AAG1aNjC-FgDE5Zws1Z-t_4pGGkBN0yh6yM"
CHANNEL_USERNAME = "@AiTechWave"
WEBHOOK_URL = "https://telegram-ebook-bot.onrender.com"  # Replace with your real URL

# Check channel membership
async def is_channel_member(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    try:
        member = await context.bot.get_chat_member(CHANNEL_USERNAME, user_id)
        return member.status in ['member', 'administrator', 'creator']
    except:
        return False

# /start command handler
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if await is_channel_member(user.id, context):
        await update.message.reply_text(f"Hello {user.first_name}, you are a channel member!")
    else:
        await update.message.reply_text(
            "Sorry, please join our channel first to use this bot:\n"
            f"{CHANNEL_USERNAME}"
        )

# /help command handler
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Use /start to begin. You must be a channel member.")

# Main function
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))

    app.run_webhook(
        listen="0.0.0.0",
        port=int(os.environ.get("PORT", 8080)),
        webhook_url=WEBHOOK_URL
    )

if __name__ == "__main__":
    main()
