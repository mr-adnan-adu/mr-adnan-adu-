from telegram.ext import ApplicationBuilder

application = ApplicationBuilder().token("YOUR_BOT_TOKEN").build()

# Your handlers here...

application.run_webhook(
    listen="0.0.0.0",
    port=8080,
    webhook_url="https://telegram-ebooks-bot.onrender.com"
)
