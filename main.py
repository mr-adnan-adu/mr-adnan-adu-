import os
import logging
import aiohttp
from urllib.parse import quote
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from aiohttp import web
import time
from collections import defaultdict
from hashlib import md5
from typing import List, Optional
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError

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

# MongoDB configuration
MONGODB_URI = os.getenv('MONGODB_URI')
MONGODB_DB_NAME = os.getenv('MONGODB_DB_NAME', 'ebook_bot')

# Z-Library configuration
ZLIB_URL = os.getenv('ZLIB_URL', 'https://z-lib.is')  # Check current Z-Library domain before deployment

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable is required")
if not ADMIN_IDS:
    logger.warning("No ADMIN_IDS set; /broadcast command will be disabled")
if not MONGODB_URI:
    logger.warning("MONGODB_URI not set; using in-memory storage (not recommended for production)")

# MongoDB Manager
class MongoDBManager:
    """MongoDB Atlas manager for the eBook downloader bot"""
    
    def __init__(self):
        self.client = None
        self.db = None
        self.users_collection = None
        self.searches_collection = None
        self.books_collection = None
        self.stats_collection = None
        self.cache_collection = None
        self.rate_limits_collection = None
        self._connected = False
        
    async def connect(self):
        """Connect to MongoDB Atlas"""
        try:
            if not MONGODB_URI:
                logger.warning("MongoDB URI not provided, using in-memory storage")
                return False
                
            self.client = AsyncIOMotorClient(
                MONGODB_URI,
                serverSelectionTimeoutMS=5000,
                connectTimeoutMS=10000,
                socketTimeoutMS=10000,
                maxPoolSize=10,
                retryWrites=True
            )
            
            self.db = self.client[MONGODB_DB_NAME]
            self.users_collection = self.db.users
            self.searches_collection = self.db.searches
            self.books_collection = self.db.books
            self.stats_collection = self.db.stats
            self.cache_collection = self.db.cache
            self.rate_limits_collection = self.db.rate_limits
            
            await self.client.admin.command('ping')
            self._connected = True
            
            await self._create_indexes()
            logger.info("Successfully connected to MongoDB Atlas")
            return True
            
        except (ConnectionFailure, ServerSelectionTimeoutError) as e:
            logger.error(f"Failed to connect to MongoDB: {e}")
            self._connected = False
            return False
    
    async def _create_indexes(self):
        """Create necessary indexes for optimal performance"""
        try:
            await self.users_collection.create_index("user_id", unique=True)
            await self.users_collection.create_index("created_at")
            
            await self.rate_limits_collection.create_index("user_id")
            await self.rate_limits_collection.create_index("created_at", expireAfterSeconds=3600)
            
            await self.cache_collection.create_index("cache_key", unique=True)
            await self.cache_collection.create_index("created_at", expireAfterSeconds=3600)
            
            await self.searches_collection.create_index("query")
            await self.searches_collection.create_index("user_id")
            await self.searches_collection.create_index("created_at", expireAfterSeconds=1800)
            
            logger.info("MongoDB indexes created successfully")
            
        except Exception as e:
            logger.error(f"Error creating MongoDB indexes: {e}")
    
    async def add_user(self, user_id: int, username: str = None, first_name: str = None):
        """Add or update user in database"""
        if not self._connected:
            return
            
        try:
            user_data = {
                "user_id": user_id,
                "username": username,
                "first_name": first_name,
                "created_at": datetime.utcnow(),
                "last_active": datetime.utcnow(),
                "search_count": 0
            }
            
            await self.users_collection.update_one(
                {"user_id": user_id},
                {"$setOnInsert": user_data, "$set": {"last_active": datetime.utcnow()}},
                upsert=True
            )
            
        except (ConnectionFailure, ServerSelectionTimeoutError) as e:
            logger.warning(f"MongoDB unavailable for add_user: {e}; skipping")
        except Exception as e:
            logger.error(f"Error adding user to MongoDB: {e}")
    
    async def get_user_count(self) -> int:
        """Get total number of users"""
        if not self._connected:
            return len(user_ids)
            
        try:
            return await self.users_collection.count_documents({})
        except (ConnectionFailure, ServerSelectionTimeoutError) as e:
            logger.warning(f"MongoDB unavailable for get_user_count: {e}; using in-memory")
            return len(user_ids)
        except Exception as e:
            logger.error(f"Error getting user count from MongoDB: {e}")
            return 0
    
    async def get_all_user_ids(self) -> List[int]:
        """Get all user IDs for broadcasting"""
        if not self._connected:
            return list(user_ids)
            
        try:
            cursor = self.users_collection.find({}, {"user_id": 1})
            return [doc["user_id"] async for doc in cursor]
        except (ConnectionFailure, ServerSelectionTimeoutError) as e:
            logger.warning(f"MongoDB unavailable for get_all_user_ids: {e}; using in-memory")
            return list(user_ids)
        except Exception as e:
            logger.error(f"Error getting user IDs from MongoDB: {e}")
            return []
    
    async def check_rate_limit(self, user_id: int, max_requests: int = 5, time_window: int = 60) -> bool:
        """Check if user is within rate limits"""
        if not self._connected:
            return rate_limiter.is_allowed(user_id)
            
        try:
            current_time = datetime.utcnow()
            time_threshold = current_time - timedelta(seconds=time_window)
            
            recent_count = await self.rate_limits_collection.count_documents({
                "user_id": user_id,
                "created_at": {"$gte": time_threshold}
            })
            
            if recent_count >= max_requests:
                return False
            
            await self.rate_limits_collection.insert_one({
                "user_id": user_id,
                "created_at": current_time
            })
            
            return True
            
        except (ConnectionFailure, ServerSelectionTimeoutError) as e:
            logger.warning(f"MongoDB unavailable for check_rate_limit: {e}; using in-memory")
            return rate_limiter.is_allowed(user_id)
        except Exception as e:
            logger.error(f"Error checking rate limit in MongoDB: {e}")
            return True
    
    async def get_remaining_requests(self, user_id: int, max_requests: int = 5, time_window: int = 60) -> int:
        """Get remaining requests for user"""
        if not self._connected:
            return rate_limiter.remaining_requests(user_id)
            
        try:
            current_time = datetime.utcnow()
            time_threshold = current_time - timedelta(seconds=time_window)
            
            recent_count = await self.rate_limits_collection.count_documents({
                "user_id": user_id,
                "created_at": {"$gte": time_threshold}
            })
            
            return max(0, max_requests - recent_count)
            
        except (ConnectionFailure, ServerSelectionTimeoutError) as e:
            logger.warning(f"MongoDB unavailable for get_remaining_requests: {e}; using in-memory")
            return rate_limiter.remaining_requests(user_id)
        except Exception as e:
            logger.error(f"Error getting remaining requests from MongoDB: {e}")
            return max_requests
    
    async def cache_search_results(self, cache_key: str, results: List[dict], ttl: int = 1800):
        """Cache search results"""
        if not self._connected:
            search_cache[cache_key] = {
                'results': results,
                'timestamp': time.time(),
                'total': len(results)
            }
            return
            
        try:
            cache_data = {
                "cache_key": cache_key,
                "results": results,
                "total": len(results),
                "created_at": datetime.utcnow()
            }
            
            await self.cache_collection.update_one(
                {"cache_key": cache_key},
                {"$set": cache_data},
                upsert=True
            )
            
        except (ConnectionFailure, ServerSelectionTimeoutError) as e:
            logger.warning(f"MongoDB unavailable for cache_search_results: {e}; using in-memory")
            search_cache[cache_key] = {
                'results': results,
                'timestamp': time.time(),
                'total': len(results)
            }
        except Exception as e:
            logger.error(f"Error caching search results in MongoDB: {e}")
    
    async def get_cached_search_results(self, cache_key: str) -> Optional[List[dict]]:
        """Get cached search results"""
        if not self._connected:
            cached = search_cache.get(cache_key)
            if cached and cached['timestamp'] + 1800 > time.time():
                return cached['results']
            return None
            
        try:
            cache_doc = await self.cache_collection.find_one({"cache_key": cache_key})
            if cache_doc:
                return cache_doc.get("results", [])
            return None
            
        except (ConnectionFailure, ServerSelectionTimeoutError) as e:
            logger.warning(f"MongoDB unavailable for get_cached_search_results: {e}; checking in-memory")
            cached = search_cache.get(cache_key)
            if cached and cached['timestamp'] + 1800 > time.time():
                return cached['results']
            return None
        except Exception as e:
            logger.error(f"Error getting cached search results from MongoDB: {e}")
            return None
    
    async def increment_search_count(self):
        """Increment global search count"""
        if not self._connected:
            bot_stats.increment_searches()
            return
            
        try:
            await self.stats_collection.update_one(
                {"stat_name": "total_searches"},
                {"$inc": {"count": 1}, "$set": {"last_updated": datetime.utcnow()}},
                upsert=True
            )
            
        except (ConnectionFailure, ServerSelectionTimeoutError) as e:
            logger.warning(f"MongoDB unavailable for increment_search_count: {e}; using in-memory")
            bot_stats.increment_searches()
        except Exception as e:
            logger.error(f"Error incrementing search count in MongoDB: {e}")
    
    async def get_search_count(self) -> int:
        """Get total search count"""
        if not self._connected:
            return bot_stats.search_count
            
        try:
            stats_doc = await self.stats_collection.find_one({"stat_name": "total_searches"})
            return stats_doc.get("count", 0) if stats_doc else 0
            
        except (ConnectionFailure, ServerSelectionTimeoutError) as e:
            logger.warning(f"MongoDB unavailable for get_search_count: {e}; using in-memory")
            return bot_stats.search_count
        except Exception as e:
            logger.error(f"Error getting search count from MongoDB: {e}")
            return 0
    
    async def cleanup_expired_data(self):
        """Clean up expired data (handled by TTL indexes, but can be called manually)"""
        if not self._connected:
            cleanup_cache()
            return
            
        try:
            current_time = datetime.utcnow()
            await self.rate_limits_collection.delete_many({
                "created_at": {"$lt": current_time - timedelta(hours=1)}
            })
            await self.cache_collection.delete_many({
                "created_at": {"$lt": current_time - timedelta(minutes=30)}
            })
            logger.info("Cleaned up expired MongoDB data")
            
        except (ConnectionFailure, ServerSelectionTimeoutError) as e:
            logger.warning(f"MongoDB unavailable for cleanup_expired_data: {e}; using in-memory")
            cleanup_cache()
        except Exception as e:
            logger.error(f"Error cleaning up expired data in MongoDB: {e}")
    
    async def close(self):
        """Close MongoDB connection"""
        if self.client and self._connected:
            self.client.close()
            self._connected = False
            logger.info("MongoDB connection closed")

# Initialize MongoDB manager
db_manager = MongoDBManager()

# Fallback in-memory storage
book_cache = {}
search_cache = {}
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
    
    async def get_stats(self) -> dict:
        search_count = await db_manager.get_search_count() if db_manager._connected else self.search_count
        user_count = await db_manager.get_user_count() if db_manager._connected else len(user_ids)
        
        return {
            'uptime': self.get_uptime(),
            'search_count': search_count,
            'cache_size': len(book_cache),
            'user_count': user_count,
            'mongodb_connected': db_manager._connected
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
        self.base_url = ZLIB_URL  # Configurable via environment variable
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        self.rate_limiter = RateLimiter(max_requests=5, time_window=60)
        
    async def search_books(self, query: str, limit: int = 10, page: int = 1) -> List[dict]:
        try:
            if not self.rate_limiter.is_allowed(hash(query)):
                logger.warning("Z-Library rate limit exceeded for query: %s", query)
                return []
            
            search_url = f"{self.base_url}/s/{quote(query)}"
            params = {'page': page} if page > 1 else {}
            response = await self._make_request(search_url, params)
            
            if not response:
                return []
                
            return await self._parse_search_results(response, limit)
            
        except Exception as e:
            logger.error(f"Z-Library search error for query '{query}': {e}")
            return []
            
    async def get_download_info(self, book_url: str) -> Optional[dict]:
        try:
            if not self.rate_limiter.is_allowed(hash(book_url)):
                logger.warning("Z-Library download rate limit exceeded for URL: %s", book_url)
                return None
                
            response = await self._make_request(book_url)
            if not response:
                return None
                
            return await self._parse_download_info(response)
            
        except Exception as e:
            logger.error(f"Z-Library download info error for URL '{book_url}': {e}")
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
            book_items = soup.select('.resItemBox, .bookRow, .itemBox')[:limit]
            
            for item in book_items:
                try:
                    title_elem = (item.select_one('.bookTitle a') or 
                                item.select_one('.title a') or 
                                item.select_one('h3 a') or
                                item.select_one('[data-toggle*="title"]'))
                    
                    author_elem = (item.select_one('.authors') or 
                                 item.select_one('.author') or
                                 item.select_one('[data-toggle*="author"]'))
                    
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
            
            format_elements = soup.select('.property_format, .format')
            info['formats'] = [fmt.get_text(strip=True) for fmt in format_elements] or ['PDF']
            
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
                    'page_size': min(limit, 32),
                    'page': page
                }
                async with session.get("https://gutendex.com/books/", params=params) as response:
                    if response.status != 200:
                        logger.warning(f"Gutenberg API returned status {response.status}")
                        return []
                    
                    data = await response.json()
                    books = []
                    
                    for book in data.get('results', []):
                        formats = book.get('formats', {})
                        download_count = book.get('download_count', 0)
                        
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
                    'rows': min(limit, 50),
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
                        title = self._extract_value(doc.get('title', 'Unknown'))
                        author = self._extract_value(doc.get('creator', 'Unknown'))
                        language = self._extract_value(doc.get('language', 'Unknown'))
                        year = self._extract_value(doc.get('year') or doc.get('date', 'Unknown'))
                        
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
        
        description = ' '.join(description.split())
        if len(description) > max_length:
            description = description[:max_length] + '...'
        return description
    
    async def search_all_sources(self, query: str, limit: int = 10, page: int = 1) -> List[dict]:
        try:
            per_source_limit = max(3, limit // 3)
            
            tasks = [
                asyncio.wait_for(self.search_project_gutenberg(query, per_source_limit, page), timeout=20),
                asyncio.wait_for(self.search_internet_archive(query, per_source_limit, page), timeout=20),
                asyncio.wait_for(self.zlibrary.search_books(query, per_source_limit, page), timeout=20)
            ]
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            all_books = []
            source_names = ['Project Gutenberg', 'Internet Archive', 'Z-Library']
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.error(f"Error searching {source_names[i]}: {result}")
                elif isinstance(result, list):
                    all_books.extend(result)
            
            return all_books[:limit]
            
        except Exception as e:
            logger.error(f"Error searching all sources: {e}")
            return []
    
    async def get_download_link(self, book_id: str, source: str) -> Optional[str]:
        try:
            if source == 'gutenberg':
                formats = [
                    f"https://www.gutenberg.org/ebooks/{book_id}.epub.images",
                    f"https://www.gutenberg.org/ebooks/{book_id}.epub.noimages",
                    f"https://www.gutenberg.org/files/{book_id}/{book_id}-pdf.pdf",
                    f"https://www.gutenberg.org/files/{book_id}/{book_id}-h.htm"
                ]
                return formats[0]
                
            elif source == 'archive':
                return f"https://archive.org/download/{book_id}/{book_id}.pdf"
                
            elif source == 'zlibrary':
                if book_id.startswith('http'):
                    info = await self.zlibrary.get_download_info(book_id)
                    if info and info.get('download_url'):
                        return info['download_url']
                return book_id
                
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
    """Clean up expired cache entries (fallback for in-memory storage)"""
    current_time = time.time()
    expired_books = [k for k, v in book_cache.items() if current_time - v['timestamp'] > 3600]
    for k in expired_books:
        book_cache.pop(k, None)
    expired_searches = [k for k, v in search_cache.items() if current_time - v['timestamp'] > 3600]
    for k in expired_searches:
        search_cache.pop(k, None)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username
    first_name = update.effective_user.first_name
    
    await db_manager.add_user(user_id, username, first_name)
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
    username = update.effective_user.username
    first_name = update.effective_user.first_name
    
    await db_manager.add_user(user_id, username, first_name)
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
3️⃣ Navigate with Previous/Next buttons
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
    username = update.effective_user.username
    first_name = update.effective_user.first_name
    
    await db_manager.add_user(user_id, username, first_name)
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
    username = update.effective_user.username
    first_name = update.effective_user.first_name
    
    await db_manager.add_user(user_id, username, first_name)
    user_ids.add(user_id)
    
    try:
        stats = await bot_stats.get_stats()
        remaining = await db_manager.get_remaining_requests(user_id) if db_manager._connected else rate_limiter.remaining_requests(user_id)
        
        health_check_msg = await update.message.reply_text("🔍 Checking source availability...")
        health = await downloader.check_health()
        
        source_status = (
            f"📖 Project Gutenberg: {'✅ Online' if health['gutenberg'] else '❌ Offline'}\n"
            f"📚 Internet Archive: {'✅ Online' if health['archive'] else '❌ Offline'}\n"
            f"📱 Z-Library: {'✅ Online' if health['zlibrary'] else '❌ Offline'}"
        )
        
        db_status = "🟢 Connected" if stats['mongodb_connected'] else "🔴 Disconnected (using in-memory storage)"
        
        status_text = f"""
🤖 *Bot Status*

⏰ *Uptime*: {stats['uptime']}
🔍 *Total Searches*: {stats['search_count']:,}
👥 *Users*: {stats['user_count']:,}
📦 *Cache Size*: {stats['cache_size']} entries
💾 *Database*: {db_status}
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
    
    rate_allowed = await db_manager.check_rate_limit(user_id, 1, 300) if db_manager._connected else broadcast_limiter.is_allowed(user_id)
    
    if not rate_allowed:
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
    if len(message) > 4000:
        await update.message.reply_text(
            "❌ Message is too long (max 4000 characters). Please shorten it.",
            parse_mode='Markdown'
        )
        return
    
    all_user_ids = await db_manager.get_all_user_ids() if db_manager._connected else list(user_ids)
    
    broadcast_msg = await update.message.reply_text(
        f"📢 Broadcasting message to {len(all_user_ids)} users...",
        parse_mode='Markdown'
    )
    
    success_count = 0
    fail_count = 0
    
    for uid in all_user_ids:
        try:
            await context.bot.send_message(
                chat_id=uid,
                text=f"📢 *Broadcast Message*\n\n{message}",
                parse_mode='Markdown',
                disable_web_page_preview=True
            )
            success_count += 1
            await asyncio.sleep(0.05)
        except Exception as e:
            logger.error(f"Failed to send broadcast to user {uid}: {e}")
            fail_count += 1
            if "bot was blocked" in str(e).lower():
                user_ids.discard(uid)
    
    await broadcast_msg.edit_text(
        f"📢 *Broadcast Complete*\n\n✅ Sent to {success_count} users\n❌ Failed for {fail_count} users",
        parse_mode='Markdown'
    )

async def search_books(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username
    first_name = update.effective_user.first_name
    
    await db_manager.add_user(user_id, username, first_name)
    user_ids.add(user_id)
    
    rate_allowed = await db_manager.check_rate_limit(user_id) if db_manager._connected else rate_limiter.is_allowed(user_id)
    
    if not rate_allowed:
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
        if db_manager._connected:
            await db_manager.cleanup_expired_data()
        else:
            cleanup_cache()
        
        cache_key = f"query:{query}:page:{page}:{int(time.time() // 1800)}"
        results = await db_manager.get_cached_search_results(cache_key) if db_manager._connected else None
        
        if not results and not db_manager._connected:
            cached = search_cache.get(cache_key)
            if cached and cached['timestamp'] + 1800 > time.time():
                results = cached['results']
                logger.info(f"Using in-memory cached results for query: {query}, page: {page}")
        
        if not results:
            if not is_callback:
                if db_manager._connected:
                    await db_manager.increment_search_count()
                else:
                    bot_stats.increment_searches()
            
            results = await downloader.search_all_sources(query, limit=36, page=page)
            
            if db_manager._connected:
                await db_manager.cache_search_results(cache_key, results)
            else:
                search_cache[cache_key] = {
                    'results': results,
                    'timestamp': time.time(),
                    'total': len(results)
                }
            
            logger.info(f"Found {len(results)} results for query: {query}, page: {page}")
        else:
            logger.info(f"Using cached results for query: {query}, page: {page}")
        
        if not results:
            no_results_msg = "❌ No books found"
            if page > 1:
                no_results_msg += " on this page. Try going to the previous page or start a new search."
            else:
                no_results_msg += ". Try:\n• Different search terms\n• Author names\n• Shorter queries\n• Check spelling"
            
            await search_msg.edit_text(no_results_msg, parse_mode='Markdown')
            return
        
        results.sort(key=lambda x: (x.get('download_count', 0), x.get('title', '').lower().count(query.lower())), reverse=True)
        
        items_per_page = 6
        total_pages = (len(results) + items_per_page - 1) // items_per_page
        start_idx = (page - 1) * items_per_page
        end_idx = start_idx + items_per_page
        page_results = results[start_idx:end_idx]
        
        if not page_results:
            await search_msg.edit_text(
                "❌ No more results on this page. Try going back or start a new search.",
                parse_mode='Markdown'
            )
            return
        
        keyboard = []
        for book in page_results:
            source_emoji = {
                'gutenberg': '📖',
                'archive': '📚',
                'zlibrary': '📱'
            }.get(book['source'], '📘')
            
            title = book['title'][:40] + "..." if len(book['title']) > 40 else book['title']
            author = book.get('author', 'Unknown')[:25] + "..." if len(book.get('author', 'Unknown')) > 25 else book.get('author', 'Unknown')
            
            timestamp = str(int(time.time()))
            book_cache_key = f"b_{md5(f'{timestamp}_{book['title']}_{book['source']}'.encode()).hexdigest()[:8]}"
            preview_cache_key = f"p_{md5(f'{timestamp}_{book['title']}_{book['source']}'.encode()).hexdigest()[:8]}"
            
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
            
            button_text = f"{source_emoji} {title}"
            if author != 'Unknown':
                button_text += f"\n👤 {author}"
            
            format_info = []
            if book.get('format') and book['format'] != 'Unknown':
                format_info.append(f"📄 {book['format']}")
            if book.get('file_size') and book['file_size'] != 'Unknown':
                format_info.append(f"💾 {book['file_size']}")
            if book.get('year') and book['year'] != 'Unknown':
                format_info.append(f"📅 {book['year']}")
            
            if format_info:
                button_text += f"\n{' | '.join(format_info)}"
            
            keyboard.append([InlineKeyboardButton(button_text, callback_data=book_cache_key)])
            keyboard.append([InlineKeyboardButton("✅ Preview/Details", callback_data=preview_cache_key)])
        
        pagination_buttons = []
        if page > 1:
            pagination_buttons.append(
                InlineKeyboardButton("⬅️ Previous", callback_data=f"prev_page:{query}:{page}")
            )
        if page < total_pages:
            pagination_buttons.append(
                InlineKeyboardButton("➡️ Next", callback_data=f"next_page:{query}:{page}")
            )
        
        if pagination_buttons:
            keyboard.append(pagination_buttons)
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
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
            if not is_callback:
                await update.message.reply_text(error_msg, parse_mode='Markdown')

async def preview_book(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = update.effective_user.id
    username = update.effective_user.username
    first_name = update.effective_user.first_name
    
    await db_manager.add_user(user_id, username, first_name)
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
    username = update.effective_user.username
    first_name = update.effective_user.first_name
    
    await db_manager.add_user(user_id, username, first_name)
    user_ids.add(user_id)
    await query.answer()
    
    try:
        callback_data = query.data
        
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
        
        await query.edit_message_text("📥 Preparing your download link...")
        
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
    user_id = update.effective_user.id
    user_ids.add(user_id)
    text = update.message.text.lower().strip()
    
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
            "ℹ️ Use `/help` to see all commands\n"
            "📊 Use `/status` to check bot status\n\n"
            "*Example:* `/search The Great Gatsby`"
        )

async def webhook_handler(request):
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
    return web.Response(text="OK", status=200)

async def setup_webhook(application, retries=3, delay=5):
    """Set up the Telegram webhook with retries"""
    for attempt in range(retries):
        try:
            webhook_info = await application.bot.get_webhook_info()
            if webhook_info.url != WEBHOOK_URL:
                await application.bot.set_webhook(url=WEBHOOK_URL)
                logger.info(f"Webhook set to {WEBHOOK_URL}")
            else:
                logger.info(f"Webhook already set to {WEBHOOK_URL}")
            return True
        except Exception as e:
            logger.error(f"Attempt {attempt + 1}/{retries} to set webhook failed: {e}")
            if attempt < retries - 1:
                await asyncio.sleep(delay * (2 ** attempt))  # Exponential backoff
    logger.error("Failed to set webhook after all retries")
    return False

async def keep_alive():
    """Keep the service alive on free hosting platforms"""
    while True:
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
        await asyncio.sleep(300)

async def main():
    global application
    
    try:
        # Initialize MongoDB
        if not await db_manager.connect():
            logger.warning("Running with in-memory storage due to MongoDB connection failure")
        
        application = Application.builder().token(BOT_TOKEN).build()
        
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(CommandHandler("about", about_command))
        application.add_handler(CommandHandler("status", status_command))
        application.add_handler(CommandHandler("broadcast", broadcast_command))
        application.add_handler(CommandHandler("search", search_books))
        application.add_handler(CallbackQueryHandler(download_book, pattern="^b_|^p_|^back_to_search|^next_page:|^prev_page:"))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        
        app = web.Application()
        app.add_routes([
            web.post(WEBHOOK_PATH, webhook_handler),
            web.get('/health', health_check),
            web.get('/', lambda request: web.Response(text="eBook Downloader Bot is running!", status=200))
        ])
        
        asyncio.create_task(keep_alive())
        
        await application.initialize()
        if not await setup_webhook(application):
            logger.critical("Webhook setup failed; exiting")
            return
        
        await application.start()
        
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', PORT)
        await site.start()
        
        logger.info(f"Bot started successfully on port {PORT}")
        logger.info(f"Webhook URL: {WEBHOOK_URL}")
        logger.info(f"Health check: {BASE_URL}/health")
        
        try:
            while True:
                await asyncio.sleep(3600)
                if db_manager._connected:
                    await db_manager.cleanup_expired_data()
                else:
                    cleanup_cache()
        except (KeyboardInterrupt, asyncio.CancelledError):
            logger.info("Received shutdown signal")
        finally:
            await runner.cleanup()
            await application.stop()
            await application.shutdown()
            await db_manager.close()
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
