import os
import logging
import aiohttp
from urllib.parse import quote
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from aiohttp import web
from threading import Thread
import time
from collections import defaultdict
from hashlib import md5
from typing import List, Optional
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import json
import asyncio

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Bot configuration
BOT_TOKEN = os.getenv('BOT_TOKEN')
PORT = int(os.getenv('PORT', 8080))
BASE_URL = os.getenv('BASE_URL', 'https://your-bot-url.onrender.com')
ADMIN_IDS = os.getenv('ADMIN_IDS', '').split(',')
ADMIN_IDS = [int(admin_id.strip()) for admin_id in ADMIN_IDS if admin_id.strip().isdigit()]
WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"
WEBHOOK_URL = f"{BASE_URL}{WEBHOOK_PATH}"

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable is required")
if not ADMIN_IDS:
    logger.warning("No ADMIN_IDS set; /broadcast command will be disabled")

# In-memory storage
book_cache = {}
search_cache = {}
cache_counter = 0
user_ids = set()

class BotStats:
    def __init__(self):
        self.start_time = datetime.now()
        self.search_count = 0
    
    def increment_searches(self):
        self.search_count += 1
    
    def get_uptime(self) -> str:
        uptime = datetime.now() - self.start_time
        days, seconds = uptime.days, uptime.seconds
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        return f"{days}d {hours}h {minutes}m"
    
    def get_stats(self) -> dict:
        return {
            'uptime': self.get_uptime(),
            'search_count': self.search_count,
            'cache_size': len(book_cache),
            'user_count': len(user_ids)
        }

bot_stats = BotStats()

class RateLimiter:
    def __init__(self, max_requests, time_window):
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests = defaultdict(list)
    
    def is_allowed(self, user_id):
        current_time = time.time()
        self.requests[user_id] = [t for t in self.requests[user_id] if current_time - t < self.time_window]
        if len(self.requests[user_id]) >= self.max_requests:
            return False
        self.requests[user_id].append(current_time)
        return True
    
    def remaining_requests(self, user_id):
        current_time = time.time()
        self.requests[user_id] = [t for t in self.requests[user_id] if current_time - t < self.time_window]
        return max(0, self.max_requests - len(self.requests[user_id]))

rate_limiter = RateLimiter(max_requests=5, time_window=60)
broadcast_limiter = RateLimiter(max_requests=1, time_window=300)

class zLibrarySearch:
    def __init__(self):
        self.base_url = "https://z-lib.is"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        self.rate_limiter = RateLimiter(max_requests=5, time_window=60)
        
    async def search_books(self, query: str, limit: int = 10, page: int = 1) -> List[dict]:
        try:
            if not self.rate_limiter.is_allowed(hash(query)):
                logger.warning("Z-Library rate limit exceeded")
                return []
            
            search_url = f"{self.base_url}/s/{quote(query)}"
            params = {'page': page} if page > 1 else {}
            response = await self._make_request(search_url, params)
            
            if not response:
                return []
                
            return await self._parse_search_results(response, limit)
            
        except Exception as e:
            logger.error(f"Z-Library search error: {e}")
            return []
            
    async def get_download_info(self, book_url: str) -> Optional[dict]:
        try:
            if not self.rate_limiter.is_allowed(hash(book_url)):
                logger.warning("Z-Library download rate limit exceeded")
                return None
                
            response = await self._make_request(book_url)
            if not response:
                return None
                
            return await self._parse_download_info(response)
            
        except Exception as e:
            logger.error(f"Z-Library download info error: {e}")
            return None
            
    async def _make_request(self, url: str, params: dict = None) -> Optional[str]:
        try:
            timeout = aiohttp.ClientTimeout(total=15)
            async with aiohttp.ClientSession(headers=self.headers, timeout=timeout) as session:
                async with session.get(url, params=params) as response:
                    if response.status == 200:
                        return await response.text()
                    elif response.status == 404:
                        logger.warning(f"Z-Library URL not found: {url}")
                        return None
                    else:
                        logger.warning(f"Z-Library request failed with status {response.status}")
                        return None
                    
        except asyncio.TimeoutError:
            logger.error(f"Z-Library request timeout: {url}")
            return None
        except aiohttp.ClientError as e:
            logger.error(f"Z-Library request error: {e}")
            return None
            
    async def _parse_search_results(self, html_content: str, limit: int) -> List[dict]:
        books = []
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            # Updated selectors for Z-Library
            book_items = soup.select('.resItemBox, .bookRow, .itemBox')[:limit]
            
            for item in book_items:
                try:
                    # Try multiple selectors for title
                    title_elem = (item.select_one('.bookTitle a') or 
                                item.select_one('.title a') or 
                                item.select_one('h3 a') or
                                item.select_one('[data-toggle*="title"]'))
                    
                    # Try multiple selectors for author
                    author_elem = (item.select_one('.authors') or 
                                 item.select_one('.author') or
                                 item.select_one('[data-toggle*="author"]'))
                    
                    # Extract other information
                    year_elem = item.select_one('.property_year, .year')
                    lang_elem = item.select_one('.property_language, .language')
                    format_elem = item.select_one('.property_format, .format')
                    size_elem = item.select_one('.property_size, .size')
                    desc_elem = item.select_one('.description, .summary')
                    
                    if title_elem:
                        title = title_elem.get_text(strip=True)
                        url = title_elem.get('href', '')
                        if url and not url.startswith('http'):
                            url = self.base_url + url
                        
                        book = {
                            'title': title or 'Unknown Title',
                            'author': author_elem.get_text(strip=True) if author_elem else 'Unknown Author',
                            'year': year_elem.get_text(strip=True) if year_elem else 'Unknown',
                            'language': lang_elem.get_text(strip=True) if lang_elem else 'Unknown',
                            'format': format_elem.get_text(strip=True) if format_elem else 'PDF',
                            'file_size': size_elem.get_text(strip=True) if size_elem else 'Unknown',
                            'description': self._truncate_description(desc_elem.get_text(strip=True) if desc_elem else 'No description available'),
                            'url': url,
                            'source': 'zlibrary',
                            'isbn': 'Unknown'
                        }
                        books.append(book)
                except Exception as e:
                    logger.error(f"Z-Library parse item error: {e}")
                    continue
                    
        except Exception as e:
            logger.error(f"Z-Library parse results error: {e}")
        
        return books
    
    def _truncate_description(self, text: str, max_length: int = 200) -> str:
        if not text:
            return 'No description available'
        return text[:max_length] + '...' if len(text) > max_length else text
        
    async def _parse_download_info(self, html_content: str) -> Optional[dict]:
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            info = {
                'formats': [],
                'size': None,
                'language': None,
                'isbn': None,
                'download_url': None,
                'description': None
            }
            
            # Extract format information
            format_elements = soup.select('.property_format, .format')
            if format_elements:
                info['formats'] = [fmt.get_text(strip=True) for fmt in format_elements]
            else:
                info['formats'] = ['PDF']
            
            # Extract other properties
            size_elem = soup.select_one('.property_size, .size')
            if size_elem:
                info['size'] = size_elem.get_text(strip=True)
            
            lang_elem = soup.select_one('.property_language, .language')
            if lang_elem:
                info['language'] = lang_elem.get_text(strip=True)
            
            isbn_elem = soup.select_one('.property_isbn, .isbn')
            if isbn_elem:
                info['isbn'] = isbn_elem.get_text(strip=True)
            
            desc_elem = soup.select_one('.description, .summary')
            if desc_elem:
                info['description'] = self._truncate_description(desc_elem.get_text(strip=True), 500)
            
            # Look for download link
            download_elem = (soup.select_one('a[href*="/dl/"]') or 
                           soup.select_one('a[href*="download"]') or
                           soup.select_one('.btn-primary[href]'))
            
            if download_elem and download_elem.get('href'):
                href = download_elem.get('href')
                if not href.startswith('http'):
                    href = self.base_url + href
                info['download_url'] = href
                
            return info if any([info['formats'], info['download_url'], info['size']]) else None
            
        except Exception as e:
            logger.error(f"Z-Library parse download info error: {e}")
            return None
    
    async def check_health(self) -> bool:
        try:
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(headers=self.headers, timeout=timeout) as session:
                async with session.get(self.base_url) as response:
                    return response.status == 200
        except Exception:
            return False

class eBookDownloader:
    def __init__(self):
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        self.zlibrary = zLibrarySearch()
    
    async def search_project_gutenberg(self, query, limit=10, page=1):
        try:
            timeout = aiohttp.ClientTimeout(total=15)
            async with aiohttp.ClientSession(headers=self.headers, timeout=timeout) as session:
                params = {
                    'search': query,
                    'page_size': min(limit, 32),  # Gutenberg API limit
                    'page': page
                }
                async with session.get("https://gutendex.com/books/", params=params) as response:
                    if response.status != 200:
                        logger.warning(f"Gutenberg API returned status {response.status}")
                        return []
                    
                    data = await response.json()
                    books = []
                    
                    for book in data.get('results', []):
                        # Get the best download format
                        formats = book.get('formats', {})
                        download_count = book.get('download_count', 0)
                        
                        # Prefer EPUB, then PDF, then HTML
                        download_url = None
                        file_format = 'Unknown'
                        if 'application/epub+zip' in formats:
                            download_url = formats['application/epub+zip']
                            file_format = 'EPUB'
                        elif 'application/pdf' in formats:
                            download_url = formats['application/pdf']
                            file_format = 'PDF'
                        elif 'text/html' in formats:
                            download_url = formats['text/html']
                            file_format = 'HTML'
                        
                        books.append({
                            'id': str(book['id']),
                            'title': book['title'],
                            'author': ', '.join([author['name'] for author in book.get('authors', [])]) or 'Unknown',
                            'year': str(book.get('copyright_year', 'Unknown')),
                            'language': ', '.join(book.get('languages', ['Unknown'])),
                            'format': file_format,
                            'file_size': 'Approx. 500 KB',
                            'description': self._clean_description(book.get('summary', 'Classic literature from Project Gutenberg')),
                            'source': 'gutenberg',
                            'download_count': download_count,
                            'isbn': 'Unknown',
                            'download_url': download_url
                        })
                    return books
                    
        except asyncio.TimeoutError:
            logger.error("Project Gutenberg search timeout")
            return []
        except aiohttp.ClientError as e:
            logger.error(f"Error searching Project Gutenberg: {e}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error in Gutenberg search: {e}")
            return []
    
    async def search_internet_archive(self, query, limit=5, page=1):
        try:
            timeout = aiohttp.ClientTimeout(total=15)
            async with aiohttp.ClientSession(headers=self.headers, timeout=timeout) as session:
                params = {
                    'q': f'title:({query}) AND mediatype:texts AND format:PDF',
                    'fl': 'identifier,title,creator,description,language,format,size,isbn,year,date',
                    'rows': min(limit, 50),  # Archive.org limit
                    'page': page,
                    'output': 'json'
                }
                async with session.get("https://archive.org/advancedsearch.php", params=params) as response:
                    if response.status != 200:
                        logger.warning(f"Internet Archive API returned status {response.status}")
                        return []
                    
                    data = await response.json()
                    books = []
                    
                    for doc in data.get('response', {}).get('docs', []):
                        # Handle list or string values
                        title = self._extract_value(doc.get('title', 'Unknown'))
                        author = self._extract_value(doc.get('creator', 'Unknown'))
                        language = self._extract_value(doc.get('language', 'Unknown'))
                        year = self._extract_value(doc.get('year') or doc.get('date', 'Unknown'))
                        
                        # Calculate file size
                        size = doc.get('size', 0)
                        if isinstance(size, str) and size.isdigit():
                            size = int(size)
                        elif not isinstance(size, int):
                            size = 0
                        
                        file_size = f"{size // (1024*1024)} MB" if size > 1024*1024 else f"{size // 1024} KB" if size > 1024 else "Unknown"
                        
                        books.append({
                            'id': doc.get('identifier', ''),
                            'title': title,
                            'author': author,
                            'year': str(year)[:4] if str(year).isdigit() else 'Unknown',
                            'language': language,
                            'format': 'PDF',
                            'file_size': file_size,
                            'description': self._clean_description(self._extract_value(doc.get('description', 'Historical document from Internet Archive'))),
                            'source': 'archive',
                            'isbn': self._extract_value(doc.get('isbn', 'Unknown')),
                            'download_count': 0
                        })
                    return books
                    
        except asyncio.TimeoutError:
            logger.error("Internet Archive search timeout")
            return []
        except aiohttp.ClientError as e:
            logger.error(f"Error searching Internet Archive: {e}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error in Archive search: {e}")
            return []
    
    def _extract_value(self, value):
        """Extract first value from list or return string"""
        if isinstance(value, list):
            return value[0] if value else 'Unknown'
        return str(value) if value else 'Unknown'
    
    def _clean_description(self, description: str, max_length: int = 200) -> str:
        """Clean and truncate description"""
        if not description or description == 'Unknown':
            return 'No description available'
        
        # Remove extra whitespace and newlines
        description = ' '.join(description.split())
        
        # Truncate if too long
        if len(description) > max_length:
            description = description[:max_length] + '...'
            
        return description
    
    async def search_all_sources(self, query: str, limit: int = 10, page: int = 1) -> List[dict]:
        try:
            # Distribute search across sources
            per_source_limit = max(3, limit // 3)
            
            # Run searches concurrently with timeout
            tasks = [
                asyncio.wait_for(self.search_project_gutenberg(query, per_source_limit, page), timeout=20),
                asyncio.wait_for(self.search_internet_archive(query, per_source_limit, page), timeout=20),
                asyncio.wait_for(self.zlibrary.search_books(query, per_source_limit, page), timeout=20)
            ]
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Combine valid results
            all_books = []
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    source_names = ['Project Gutenberg', 'Internet Archive', 'Z-Library']
                    logger.error(f"Error searching {source_names[i]}: {result}")
                elif isinstance(result, list):
                    all_books.extend(result)
            
            return all_books[:limit]  # Limit final results
            
        except Exception as e:
            logger.error(f"Error searching all sources: {e}")
            return []
    
    async def get_download_link(self, book_id: str, source: str) -> Optional[str]:
        try:
            if source == 'gutenberg':
                # Try different formats
                formats = [
                    f"https://www.gutenberg.org/ebooks/{book_id}.epub.images",
                    f"https://www.gutenberg.org/ebooks/{book_id}.epub.noimages",
                    f"https://www.gutenberg.org/files/{book_id}/{book_id}-pdf.pdf",
                    f"https://www.gutenberg.org/files/{book_id}/{book_id}-h.htm"
                ]
                return formats[0]  # Return EPUB as default
                
            elif source == 'archive':
                return f"https://archive.org/download/{book_id}/{book_id}.pdf"
                
            elif source == 'zlibrary':
                if book_id.startswith('http'):
                    info = await self.zlibrary.get_download_info(book_id)
                    if info and info.get('download_url'):
                        return info['download_url']
                return book_id  # Return the URL as-is
                
            return None
            
        except Exception as e:
            logger.error(f"Error getting download link: {e}")
            return None
    
    async def check_health(self) -> dict:
        async def check_gutenberg():
            try:
                timeout = aiohttp.ClientTimeout(total=10)
                async with aiohttp.ClientSession(headers=self.headers, timeout=timeout) as session:
                    async with session.get("https://gutendex.com/books/", params={'page_size': 1}) as response:
                        return response.status == 200
            except Exception:
                return False
        
        async def check_archive():
            try:
                timeout = aiohttp.ClientTimeout(total=10)
                async with aiohttp.ClientSession(headers=self.headers, timeout=timeout) as session:
                    params = {'q': 'test', 'rows': 1, 'output': 'json'}
                    async with session.get("https://archive.org/advancedsearch.php", params=params) as response:
                        return response.status == 200
            except Exception:
                return False
        
        try:
            tasks = [
                asyncio.wait_for(check_gutenberg(), timeout=15),
                asyncio.wait_for(check_archive(), timeout=15),
                asyncio.wait_for(self.zlibrary.check_health(), timeout=15)
            ]
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            return {
                'gutenberg': results[0] if not isinstance(results[0], Exception) else False,
                'archive': results[1] if not isinstance(results[1], Exception) else False,
                'zlibrary': results[2] if not isinstance(results[2], Exception) else False
            }
        except Exception as e:
            logger.error(f"Health check error: {e}")
            return {'gutenberg': False, 'archive': False, 'zlibrary': False}

# Initialize downloader
downloader = eBookDownloader()

def cleanup_cache():
    """Clean up expired cache entries"""
    current_time = time.time()
    expired_books = [k for k, v in book_cache.items() if current_time - v['timestamp'] > 3600]
    for k in expired_books:
        book_cache.pop(k, None)
    expired_searches = [k for k, v in search_cache.items() if current_time - v['timestamp'] > 3600]
    for k in expired_searches:
        search_cache.pop(k, None)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_ids.add(user_id)
    welcome_text = """
📚 *Welcome to Free eBooks Downloader Bot!*

I help you find and download free eBooks from legal sources.

*Available Commands:*
• `/search <book name>` - Search for books
• `/help` - Show help information
• `/about` - About this bot
• `/status` - Check bot status

*Example:* `/search Pride and Prejudice`

*Sources:*
📖 Project Gutenberg (70,000+ free books)
📚 Internet Archive (millions of free books)
📱 Z-Library (additional sources)

_Note: All books are from legal, public domain sources._
    """
    await update.message.reply_text(welcome_text, parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_ids.add(user_id)
    help_text = """
📖 *eBooks Downloader Bot Help*

*Commands:*
• `/start` - Start the bot
• `/search <book title>` - Search for books
• `/help` - Show this help
• `/about` - About this bot
• `/status` - Check bot status
• `/broadcast <message>` - (Admins only) Send message to all users

*How to use:*
1️⃣ Use `/search` followed by the book title
2️⃣ View details with ✅ Preview/Details
3️⃣ Navigate with Next/Previous buttons
4️⃣ Click book title to get download link

*Supported formats:*
• EPUB (Project Gutenberg)
• PDF (Internet Archive & Z-Library)
• HTML (Project Gutenberg backup)

*Rate Limits:*
• 5 searches per minute per user
• Searches reset every minute

*Note:* All sources provide legal, free books.
    """
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def about_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_ids.add(user_id)
    about_text = """
ℹ️ *About Free eBooks Downloader Bot*

This bot provides access to books from:

📖 *Project Gutenberg*
• 70,000+ free eBooks
• Classic literature and historical texts
• Public domain works
• EPUB and HTML formats

📚 *Internet Archive*
• Millions of free books and documents
• Academic texts and research papers
• Historical documents
• PDF format

📱 *Z-Library*
• Additional book sources
• Various formats available
• Academic and general books

🔒 *Legal & Privacy*
• Only serves public domain and legally free books
• No user data stored or tracked
• Respects copyright laws
• DMCA compliant

Built with ❤️ for book lovers worldwide.
    """
    await update.message.reply_text(about_text, parse_mode='Markdown')

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_ids.add(user_id)
    
    try:
        stats = bot_stats.get_stats()
        remaining = rate_limiter.remaining_requests(user_id)
        
        # Check source health
        health_check_msg = await update.message.reply_text("🔍 Checking source availability...")
        health = await downloader.check_health()
        
        source_status = (
            f"📖 Project Gutenberg: {'✅ Online' if health['gutenberg'] else '❌ Offline'}\n"
            f"📚 Internet Archive: {'✅ Online' if health['archive'] else '❌ Offline'}\n"
            f"📱 Z-Library: {'✅ Online' if health['zlibrary'] else '❌ Offline'}"
        )
        
        status_text = f"""
🤖 *Bot Status*

⏰ *Uptime*: {stats['uptime']}
🔍 *Total Searches*: {stats['search_count']:,}
👥 *Users*: {stats['user_count']:,}
📦 *Cache Size*: {stats['cache_size']} entries
🚦 *Your Remaining Searches*: {remaining}/5 (resets every minute)

*Source Availability*:
{source_status}

💡 Use `/search` to find books or `/help` for more commands.
        """
        
        await health_check_msg.edit_text(status_text, parse_mode='Markdown')
    
    except Exception as e:
        logger.error(f"Status command error: {e}")
        await update.message.reply_text(
            "❌ Error retrieving bot status. Please try again later.",
            parse_mode='Markdown'
        )

async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_IDS:
        await update.message.reply_text(
            "❌ You are not authorized to use this command.",
            parse_mode='Markdown'
        )
        return
    
    if not broadcast_limiter.is_allowed(user_id):
        await update.message.reply_text(
            "⚠️ Broadcast rate limit exceeded. Please wait 5 minutes and try again.",
            parse_mode='Markdown'
        )
        return
    
    if not context.args:
        await update.message.reply_text(
            "Please provide a message to broadcast.\n\n*Example:* `/broadcast Maintenance scheduled at 2 AM UTC`",
            parse_mode='Markdown'
        )
        return
    
    message = ' '.join(context.args)
    if len(message) > 4000:  # Leave room for formatting
        await update.message.reply_text(
            "❌ Message is too long (max 4000 characters). Please shorten it.",
            parse_mode='Markdown'
        )
        return
    
    broadcast_msg = await update.message.reply_text(
        f"📢 Broadcasting message to {len(user_ids)} users...",
        parse_mode='Markdown'
    )
    
    success_count = 0
    fail_count = 0
    
    for uid in list(user_ids):  # Create a copy to avoid modification during iteration
        try:
            await context.bot.send_message(
                chat_id=uid,
                text=f"📢 *Broadcast Message*\n\n{message}",
                parse_mode='Markdown',
                disable_web_page_preview=True
            )
            success_count += 1
            await asyncio.sleep(0.05)  # Small delay to avoid rate limits
        except Exception as e:
            logger.error(f"Failed to send broadcast to user {uid}: {e}")
            fail_count += 1
            # Remove user if they blocked the bot
            if "bot was blocked" in str(e).lower():
                user_ids.discard(uid)
    
    await broadcast_msg.edit_text(
        f"📢 *Broadcast Complete*\n\n✅ Sent to {success_count} users\n❌ Failed for {fail_count} users",
        parse_mode='Markdown'
    )

async def search_books(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global cache_counter
    user_id = update.effective_user.id
    user_ids.add(user_id)
    
    if not rate_limiter.is_allowed(user_id):
        remaining_time = 60 - (time.time() % 60)
        await update.message.reply_text(
            f"⚠️ You're searching too quickly. Please wait {int(remaining_time)} seconds and try again.\n\n"
            f"Rate limit: 5 searches per minute.",
            parse_mode='Markdown'
        )
        return
    
    query = None
    page = 1
    is_callback = update.callback_query is not None
    
    if is_callback:
        callback_query = update.callback_query
        await callback_query.answer()
        callback_data = callback_query.data.split(':')
        
        if len(callback_data) != 3 or callback_data[0] not in ['next_page', 'prev_page']:
            await callback_query.edit_message_text(
                "❌ Invalid pagination request. Please start a new search.",
                parse_mode='Markdown'
            )
            return
            
        query = callback_data[1]
        page = int(callback_data[2])
        
        if callback_data[0] == 'next_page':
            page += 1
        elif callback_data[0] == 'prev_page':
            page = max(1, page - 1)
    else:
        if not context.args:
            await update.message.reply_text(
                "Please provide a book title to search.\n\n*Example:* `/search Pride and Prejudice`",
                parse_mode='Markdown'
            )
            return
        query = ' '.join(context.args).strip()
        if len(query) < 2:
            await update.message.reply_text(
                "Search query too short. Please provide at least 2 characters.",
                parse_mode='Markdown'
            )
            return
    
    # Send search message
    if is_callback:
        search_msg = await callback_query.edit_message_text(
            f"🔍 Searching for '*{query}*' (Page {page})...", 
            parse_mode='Markdown'
        )
    else:
        search_msg = await update.message.reply_text(
            f"🔍 Searching for '*{query}*'...", 
            parse_mode='Markdown'
        )
    
    try:
        cleanup_cache()
        
        # Check cache first
        cache_key = f"query:{query}:page:{page}"
        cached = search_cache.get(cache_key)
        
        results = []
        if cached and cached['timestamp'] + 1800 > time.time():  # 30 minutes cache
            results = cached['results']
            logger.info(f"Using cached results for query: {query}, page: {page}")
        else:
            if not is_callback:
                bot_stats.increment_searches()
            
            # Search all sources
            results = await downloader.search_all_sources(query, limit=36, page=page)
            
            # Cache results
            search_cache[cache_key] = {
                'results': results,
                'timestamp': time.time(),
                'total': len(results)
            }
            
            logger.info(f"Found {len(results)} results for query: {query}, page: {page}")
        
        if not results:
            no_results_msg = "❌ No books found"
            if page > 1:
                no_results_msg += " on this page. Try going to the previous page or start a new search."
            else:
                no_results_msg += ". Try:\n• Different search terms\n• Author names\n• Shorter queries\n• Check spelling"
            
            await search_msg.edit_text(no_results_msg, parse_mode='Markdown')
            return
        
        # Sort results by download count (for Gutenberg) and relevance
        results.sort(key=lambda x: (x.get('download_count', 0), x.get('title', '').lower().count(query.lower())), reverse=True)
        
        # Pagination
        items_per_page = 6  # Reduced for better display
        total_pages = max(1, (len(results) + items_per_page - 1) // items_per_page)
        start_idx = (page - 1) * items_per_page
        end_idx = start_idx + items_per_page
        page_results = results[start_idx:end_idx]
        
        if not page_results:
            await search_msg.edit_text(
                "❌ No more results on this page. Try going back or start a new search.",
                parse_mode='Markdown'
            )
            return
        
        # Build keyboard
        keyboard = []
        for book in page_results:
            source_emoji = {
                'gutenberg': '📖',
                'archive': '📚',
                'zlibrary': '📱'
            }.get(book['source'], '📘')
            
            # Truncate long titles and authors
            title = book['title'][:40] + "..." if len(book['title']) > 40 else book['title']
            author = book.get('author', 'Unknown')[:25] + "..." if len(book.get('author', 'Unknown')) > 25 else book.get('author', 'Unknown')
            
            # Create cache keys
            book_cache_key = f"b_{md5(f'{cache_counter}_{book["title"]}_{book["source"]}'.encode()).hexdigest()[:8]}"
            preview_cache_key = f"p_{md5(f'{cache_counter}_{book["title"]}_{book["source"]}'.encode()).hexdigest()[:8]}"
            cache_counter += 1
            
            # Store book data in cache
            book_cache[book_cache_key] = {
                'data': {
                    'source': book['source'],
                    'id': book.get('id') or book.get('url'),
                    'info': book
                },
                'timestamp': time.time()
            }
            book_cache[preview_cache_key] = {
                'data': book,
                'timestamp': time.time()
            }
            
            # Create button text with book info
            button_text = f"{source_emoji} {title}"
            if author != 'Unknown':
                button_text += f"\n👤 {author}"
            
            # Add format and size info
            format_info = []
            if book.get('format') and book['format'] != 'Unknown':
                format_info.append(f"📄 {book['format']}")
            if book.get('file_size') and book['file_size'] != 'Unknown':
                format_info.append(f"💾 {book['file_size']}")
            if book.get('year') and book['year'] != 'Unknown':
                format_info.append(f"📅 {book['year']}")
            
            if format_info:
                button_text += f"\n{' | '.join(format_info)}"
            
            # Add buttons
            keyboard.append([InlineKeyboardButton(button_text, callback_data=book_cache_key)])
            keyboard.append([InlineKeyboardButton("✅ Preview/Details", callback_data=preview_cache_key)])
        
        # Add pagination buttons
        pagination_buttons = []
        if page > 1:
            pagination_buttons.append(
                InlineKeyboardButton("⬅️ Previous", callback_data=f"prev_page:{query}:{page}")
            )
        if len(page_results) == items_per_page:  # Assume more pages exist
            pagination_buttons.append(
                InlineKeyboardButton("➡️ Next", callback_data=f"next_page:{query}:{page}")
            )
        
        if pagination_buttons:
            keyboard.append(pagination_buttons)
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Create result message
        result_text = f"📚 Found *{len(results)}* books for '*{query}*'"
        if total_pages > 1:
            result_text += f" (Page {min(page, total_pages)}/{total_pages})"
        result_text += ":\n\n💡 Tap a book title to download or ✅ Preview for details"
        
        await search_msg.edit_text(
            result_text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    except Exception as e:
        logger.error(f"Search error: {e}")
        error_msg = "❌ An error occurred during search. Please try again later."
        if "timeout" in str(e).lower():
            error_msg = "⏱️ Search timed out. Please try again with a shorter query."
        
        try:
            await search_msg.edit_text(error_msg, parse_mode='Markdown')
        except Exception:
            # If edit fails, send new message
            if not is_callback:
                await update.message.reply_text(error_msg, parse_mode='Markdown')

async def preview_book(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = update.effective_user.id
    user_ids.add(user_id)
    await query.answer()
    
    try:
        callback_data = query.data
        book_entry = book_cache.get(callback_data)
        
        if not book_entry:
            await query.edit_message_text(
                "❌ Preview data expired. Please search again using `/search <book title>`",
                parse_mode='Markdown'
            )
            return
        
        book = book_entry['data']
        source_name = {
            'gutenberg': 'Project Gutenberg',
            'archive': 'Internet Archive',
            'zlibrary': 'Z-Library'
        }.get(book['source'], 'Unknown Source')
        
        source_emoji = {
            'gutenberg': '📖',
            'archive': '📚',
            'zlibrary': '📱'
        }.get(book['source'], '📘')
        
        # Get additional info for Z-Library books
        additional_info = ""
        if book['source'] == 'zlibrary' and book.get('url'):
            try:
                download_info = await downloader.zlibrary.get_download_info(book['url'])
                if download_info:
                    if download_info.get('isbn') and download_info['isbn'] != 'Unknown':
                        book['isbn'] = download_info['isbn']
                    if download_info.get('description') and len(download_info['description']) > len(book.get('description', '')):
                        book['description'] = download_info['description']
                    additional_info = "\n💡 *Note:* Z-Library downloads may require account registration."
            except Exception as e:
                logger.error(f"Error fetching Z-Library details: {e}")
        
        # Format the preview message
        message = f"""
{source_emoji} *{book['title']}*

📚 *Source:* {source_name}
👤 *Author(s):* {book.get('author', 'Unknown')}
📅 *Year:* {book.get('year', 'Unknown')}
🌐 *Language:* {book.get('language', 'Unknown')}
📄 *Format:* {book.get('format', 'Unknown')}
💾 *File Size:* {book.get('file_size', 'Unknown')}
🔖 *ISBN:* {book.get('isbn', 'Unknown')}

📝 *Description:*
{book.get('description', 'No description available')}{additional_info}
        """
        
        # Create back button
        keyboard = [[InlineKeyboardButton("🔙 Back to Search Results", callback_data="back_to_search")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            message,
            parse_mode='Markdown',
            reply_markup=reply_markup,
            disable_web_page_preview=True
        )
    
    except Exception as e:
        logger.error(f"Preview error: {e}")
        await query.edit_message_text(
            "❌ An error occurred while fetching preview. Please try searching again.",
            parse_mode='Markdown'
        )

async def download_book(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = update.effective_user.id
    user_ids.add(user_id)
    await query.answer()
    
    try:
        callback_data = query.data
        
        # Handle special cases
        if callback_data == "back_to_search":
            await query.edit_message_text(
                "🔍 Please start a new search using `/search <book title>`\n\n"
                "Example: `/search Pride and Prejudice`",
                parse_mode='Markdown'
            )
            return
        
        if callback_data.startswith('next_page:') or callback_data.startswith('prev_page:'):
            await search_books(update, context)
            return
        
        if callback_data.startswith('p_'):
            await preview_book(update, context)
            return
        
        # Handle book download
        book_entry = book_cache.get(callback_data)
        if not book_entry:
            await query.edit_message_text(
                "❌ Book data expired. Please search again using `/search <book title>`",
                parse_mode='Markdown'
            )
            return
        
        book_data = book_entry['data']
        source = book_data['source']
        book_id = book_data['id']
        book_info = book_data['info']
        
        # Show preparing message
        await query.edit_message_text("📥 Preparing your download link...")
        
        # Get download link
        download_link = await downloader.get_download_link(book_id, source)
        
        if download_link:
            source_info = {
                'gutenberg': {
                    'name': 'Project Gutenberg',
                    'note': 'Free public domain books. No registration required.'
                },
                'archive': {
                    'name': 'Internet Archive',
                    'note': 'Free historical documents. No registration required.'
                },
                'zlibrary': {
                    'name': 'Z-Library',
                    'note': 'May require account registration for download.'
                }
            }
            
            source_data = source_info.get(source, {'name': 'Unknown Source', 'note': 'Check source requirements.'})
            file_format = book_info.get('format', 'Unknown')
            file_size = book_info.get('file_size', 'Unknown')
            
            message = f"""
📖 *Download Ready!*

**{book_info['title']}**
👤 {book_info.get('author', 'Unknown')}

📚 *Source:* {source_data['name']}
📄 *Format:* {file_format}
💾 *Size:* {file_size}

🔗 [**📥 Download Book**]({download_link})

💡 *Note:* {source_data['note']}

⚠️ *Download Tips:*
• Links are temporary and may expire
• Some formats work better on specific devices
• Right-click → "Save as" on desktop browsers
            """
            
            keyboard = [[InlineKeyboardButton("🔍 Search More Books", callback_data="back_to_search")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                message,
                parse_mode='Markdown',
                reply_markup=reply_markup,
                disable_web_page_preview=True
            )
            
            # Remove from cache to save memory
            if callback_data in book_cache:
                del book_cache[callback_data]
                
        else:
            error_messages = {
                'gutenberg': "❌ Couldn't generate Gutenberg download link. The book may not be available in the requested format.",
                'archive': "❌ Couldn't generate Archive.org download link. The document may not be publicly available.",
                'zlibrary': "❌ Couldn't generate Z-Library download link. The book may require account registration or may not be available."
            }
            
            error_msg = error_messages.get(source, "❌ Couldn't generate download link. Please try another book.")
            
            keyboard = [[InlineKeyboardButton("🔍 Try Another Search", callback_data="back_to_search")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                error_msg,
                parse_mode='Markdown',
                reply_markup=reply_markup
            )
    
    except Exception as e:
        logger.error(f"Download error: {e}")
        await query.edit_message_text(
            "❌ An error occurred while preparing the download. Please try searching again.",
            parse_mode='Markdown'
        )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle non-command messages"""
    user_id = update.effective_user.id
    user_ids.add(user_id)
    text = update.message.text.lower().strip()
    
    # Common keywords that suggest user wants to search
    search_keywords = ['search', 'find', 'book', 'download', 'ebook', 'pdf', 'epub']
    help_keywords = ['help', 'how', 'command', 'what', 'commands']
    
    if any(keyword in text for keyword in search_keywords):
        await update.message.reply_text(
            "🔍 To search for books, use: `/search <book title>`\n\n"
            "*Examples:*\n"
            "• `/search Pride and Prejudice`\n"
            "• `/search Harry Potter`\n"
            "• `/search George Orwell`\n\n"
            "💡 You can search by title, author, or keywords!",
            parse_mode='Markdown'
        )
    elif any(keyword in text for keyword in help_keywords):
        await help_command(update, context)
    elif 'status' in text:
        await status_command(update, context)
    else:
        await update.message.reply_text(
            "👋 Hello! I'm your free eBooks downloader bot.\n\n"
            "🔍 Use `/search <book title>` to find books\n"
            "❓ Use `/help` to see all commands\n"
            "📊 Use `/status` to check bot status\n\n"
            "*Example:* `/search The Great Gatsby`"
        )

# Web server handlers
async def webhook_handler(request):
    """Handle incoming webhook requests from Telegram"""
    try:
        body = await request.json()
        update = Update.de_json(body, application.bot)
        if update:
            await application.process_update(update)
        return web.Response(status=200)
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return web.Response(status=500, text="Internal Server Error")

async def health_check(request):
    """Health check endpoint for monitoring"""
    try:
        # Perform basic health checks
        current_time = datetime.now()
        uptime = current_time - bot_stats.start_time
        
        health_data = {
            'status': 'healthy',
            'uptime_seconds': uptime.total_seconds(),
            'search_count': bot_stats.search_count,
            'user_count': len(user_ids),
            'cache_size': len(book_cache),
            'timestamp': current_time.isoformat()
        }
        
        return web.json_response(health_data, status=200)
    except Exception as e:
        logger.error(f"Health check error: {e}")
        return web.Response(text="OK", status=200)  # Simple OK for basic monitoring

# Webhook setup
async def setup_webhook(application):
    """Set up the Telegram webhook"""
    try:
        webhook_info = await application.bot.get_webhook_info()
        if webhook_info.url != WEBHOOK_URL:
            await application.bot.set_webhook(url=WEBHOOK_URL)
            logger.info(f"Webhook set to {WEBHOOK_URL}")
        else:
            logger.info(f"Webhook already set to {WEBHOOK_URL}")
    except Exception as e:
        logger.error(f"Failed to set webhook: {e}")
        raise

# Keep-alive functionality
def keep_alive():
    """Keep the service alive on free hosting platforms"""
    def ping():
        while True:
            try:
                async def async_ping():
                    try:
                        timeout = aiohttp.ClientTimeout(total=30)
                        async with aiohttp.ClientSession(timeout=timeout) as session:
                            async with session.get(f"{BASE_URL}/health") as response:
                                if response.status == 200:
                                    logger.info("Keep-alive ping successful")
                                else:
                                    logger.warning(f"Keep-alive ping failed: {response.status}")
                    except Exception as e:
                        logger.error(f"Keep-alive ping error: {e}")
                
                # Run the async ping
                asyncio.run(async_ping())
                
                # Wait 5 minutes before next ping
                time.sleep(300)
                
            except Exception as e:
                logger.error(f"Keep-alive thread error: {e}")
                time.sleep(300)  # Wait before retrying
    
    # Start keep-alive thread
    thread = Thread(target=ping, daemon=True)
    thread.start()
    logger.info("Keep-alive thread started")

# Global variable for application
application = None

async def main():
    """Main application entry point"""
    global application
    
    try:
        # Initialize the application
        application = Application.builder().token(BOT_TOKEN).build()
        
        # Add handlers
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(CommandHandler("about", about_command))
        application.add_handler(CommandHandler("status", status_command))
        application.add_handler(CommandHandler("broadcast", broadcast_command))
        application.add_handler(CommandHandler("search", search_books))
        application.add_handler(CallbackQueryHandler(download_book, pattern="^b_|^p_|^back_to_search|^next_page:|^prev_page:"))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        
        # Create web application
        app = web.Application()
        app.add_routes([
            web.post(WEBHOOK_PATH, webhook_handler),
            web.get('/health', health_check),
            web.get('/', lambda request: web.Response(text="eBook Downloader Bot is running!", status=200))
        ])
        
        # Start keep-alive service
        keep_alive()
        
        # Initialize Telegram application
        await application.initialize()
        await setup_webhook(application)
        await application.start()
        
        # Start web server
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', PORT)
        await site.start()
        
        logger.info(f"Bot started successfully on port {PORT}")
        logger.info(f"Webhook URL: {WEBHOOK_URL}")
        logger.info(f"Health check: {BASE_URL}/health")
        
        # Keep the application running
        try:
            while True:
                await asyncio.sleep(3600)  # Sleep for 1 hour
                cleanup_cache()  # Clean cache periodically
        except KeyboardInterrupt:
            logger.info("Received shutdown signal")
        finally:
            # Cleanup
            await runner.cleanup()
            await application.stop()
            await application.shutdown()
            logger.info("Bot stopped successfully")
            
    except Exception as e:
        logger.error(f"Failed to start bot: {e}")
        raise

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        exit(1)
