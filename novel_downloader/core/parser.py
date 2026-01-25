"""
Base Parser class and Chapter data structure
All site-specific parsers inherit from BaseParser
"""

import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from bs4 import BeautifulSoup

# Try curl_cffi first (best TLS fingerprinting, lightweight)
HTTP_CLIENT = None

try:
    from curl_cffi.requests import Session as CurlSession
    HTTP_CLIENT = "curl_cffi"
    print("Using curl_cffi (Chrome TLS fingerprinting)")
except ImportError:
    pass

# Fallback to requests
if not HTTP_CLIENT:
    import requests
    HTTP_CLIENT = "requests"
    print("Warning: curl_cffi not installed. Run: pip install curl_cffi")


@dataclass
class Chapter:
    """Represents a single chapter."""
    title: str
    url: str
    content: str = ""
    index: int = 0
    
    def __str__(self):
        return f"Chapter {self.index}: {self.title}"


@dataclass 
class NovelInfo:
    """Metadata about a novel."""
    title: str
    author: str = "Unknown"
    description: str = ""
    cover_url: Optional[str] = None
    language: str = "zh"
    tags: List[str] = field(default_factory=list)
    source_url: str = ""


class BaseParser(ABC):
    """
    Base class for all site parsers.
    Each site (twkan, royalroad, etc.) implements its own parser.
    """
    
    # Subclasses should set these
    SITE_NAME = "Unknown"
    SITE_DOMAINS = []  # e.g., ["twkan.com", "www.twkan.com"]
    
    def __init__(self):
        if HTTP_CLIENT == "curl_cffi":
            # curl_cffi with Chrome 120 impersonation
            self.session = CurlSession(impersonate="chrome120")
        else:
            import requests
            self.session = requests.Session()
            self.session.headers.update({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            })
        
        self.request_delay = 0.5
    
    @classmethod
    def can_handle(cls, url: str) -> bool:
        """Check if this parser can handle the given URL."""
        for domain in cls.SITE_DOMAINS:
            if domain in url.lower():
                return True
        return False
    
    @abstractmethod
    def get_novel_info(self, url: str) -> NovelInfo:
        pass
    
    @abstractmethod
    def get_chapter_list(self, url: str) -> List[Chapter]:
        pass
    
    @abstractmethod
    def get_chapter_content(self, chapter: Chapter) -> str:
        pass
    
    def fetch_page(self, url: str, retries: int = 3) -> BeautifulSoup:
        """
        Fetch a page and return BeautifulSoup object.
        """
        last_error = None
        
        for attempt in range(retries):
            try:
                response = self.session.get(url, timeout=30)
                response.raise_for_status()
                return BeautifulSoup(response.text, 'lxml')
                
            except Exception as e:
                last_error = e
                print(f"  Attempt {attempt + 1}/{retries} failed: {e}")
                if attempt < retries - 1:
                    wait = 2 ** (attempt + 1)
                    print(f"  Retrying in {wait}s...")
                    time.sleep(wait)
        
        raise last_error
    
    def fetch_html(self, url: str) -> str:
        """Fetch page and return raw HTML string."""
        response = self.session.get(url, timeout=30)
        response.raise_for_status()
        return response.text


# Registry of all parsers
_parser_registry: List[type] = []


def register_parser(parser_class: type):
    """Decorator to register a parser class."""
    _parser_registry.append(parser_class)
    return parser_class


def get_parser_for_url(url: str) -> Optional[BaseParser]:
    """Find and instantiate the appropriate parser for a URL."""
    for parser_class in _parser_registry:
        if parser_class.can_handle(url):
            return parser_class()
    return None


def get_supported_sites() -> List[str]:
    """Get list of all supported site names."""
    return [p.SITE_NAME for p in _parser_registry]


def cleanup_browser():
    """Placeholder for compatibility."""
    pass
