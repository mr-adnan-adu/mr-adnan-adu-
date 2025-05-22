#!/usr/bin/env python3
"""
Webhook handler for eBook Downloader Bot
This module handles the webhook setup and routing for Render deployment
"""
import os
import sys
import asyncio
import logging
from pathlib import Path

# Add the current directory to Python path
current_dir = Path(__file__).parent
sys.path.insert(0, str(current_dir))

# Configure logging for production
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('bot.log', mode='a')
    ]
)
logger = logging.getLogger(__name__)

async def start_bot():
    """Start the bot application"""
    try:
        # Import and run the main application
        from main import main
        logger.info("Starting eBook Downloader Bot...")
        await main()
    except Exception as e:
        logger.error(f"Failed to start bot: {e}")
        raise

def run_bot():
    """Run the bot with proper event loop handling"""
    try:
        # Use uvloop for better performance on Unix systems
        if sys.platform != 'win32':
            try:
                import uvloop
                asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
                logger.info("Using uvloop for better performance")
            except ImportError:
                logger.info("uvloop not available, using default event loop")
        
        # Run the bot
        asyncio.run(start_bot())
        
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Bot crashed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    # Environment validation
    required_env_vars = ['BOT_TOKEN', 'BASE_URL']
    missing_vars = [var for var in required_env_vars if not os.getenv(var)]
    
    if missing_vars:
        logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
        sys.exit(1)
    
    # Log startup information
    logger.info("="*50)
    logger.info("eBook Downloader Bot - Webhook Handler")
    logger.info("="*50)
    logger.info(f"Python version: {sys.version}")
    logger.info(f"Bot Token: {'*' * 20}{os.getenv('BOT_TOKEN', '')[-10:]}")
    logger.info(f"Base URL: {os.getenv('BASE_URL', 'Not set')}")
    logger.info(f"Port: {os.getenv('PORT', '8080')}")
    logger.info(f"Admin IDs: {len(os.getenv('ADMIN_IDS', '').split(','))} configured")
    logger.info("="*50)
    
    # Start the bot
    run_bot()
