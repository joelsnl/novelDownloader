"""
Parser for twkan.com (台灣小說網)
Based on WebToEpub TwkanParser.js
"""

import re
import time
from typing import List, Optional
from bs4 import BeautifulSoup

from core.parser import BaseParser, Chapter, NovelInfo, register_parser


@register_parser
class TwkanParser(BaseParser):
    """Parser for twkan.com Chinese novel site."""
    
    SITE_NAME = "twkan.com"
    SITE_DOMAINS = ["twkan.com"]
    
    def __init__(self):
        super().__init__()
        self.request_delay = 1.0  # 1 second between requests
    
    def _extract_book_id(self, url: str) -> Optional[str]:
        """Extract book ID from URL."""
        # Matches: /book/76222.html, /book/76222/index.html, /txt/76222/12345
        match = re.search(r'/(?:book|txt)/(\d+)', url)
        return match.group(1) if match else None
    
    def get_novel_info(self, url: str) -> NovelInfo:
        """Extract novel metadata from main page."""
        soup = self.fetch_page(url)
        
        # Try meta tags first (most reliable)
        title = ""
        author = "Unknown"
        description = ""
        cover_url = None
        tags = []
        
        # og:title
        meta_title = soup.select_one("meta[property='og:title']")
        if meta_title:
            title = meta_title.get('content', '')
        
        # Fallback: page title or h1
        if not title:
            h1 = soup.select_one(".booknav2 h1 a, .booknav2 h1, h1")
            if h1:
                title = h1.get_text(strip=True)
        
        # og:novel:author
        meta_author = soup.select_one("meta[property='og:novel:author']")
        if meta_author:
            author = meta_author.get('content', '')
        else:
            # Fallback: author link
            author_el = soup.select_one(".booknav2 p a[href*='/author/']")
            if author_el:
                author = author_el.get_text(strip=True)
        
        # og:description
        meta_desc = soup.select_one("meta[property='og:description']")
        if meta_desc:
            description = meta_desc.get('content', '')
        else:
            # Fallback: navtxt
            desc_el = soup.select_one(".navtxt p")
            if desc_el:
                description = desc_el.get_text(strip=True)
        
        # og:image (cover)
        meta_image = soup.select_one("meta[property='og:image']")
        if meta_image:
            cover_url = meta_image.get('content', '')
        else:
            # Fallback: book image
            cover_el = soup.select_one(".bookimg2 img, .bookimg img")
            if cover_el:
                cover_url = cover_el.get('src', '')
        
        # If still no cover, try to construct from book ID
        if not cover_url:
            book_id = self._extract_book_id(url)
            if book_id:
                prefix = book_id[:2] if len(book_id) >= 2 else book_id
                cover_url = f"https://twkan.com/files/article/image/{prefix}/{book_id}/{book_id}s.jpg"
        
        # Category/tags
        meta_category = soup.select_one("meta[property='og:novel:category']")
        if meta_category:
            tags.append(meta_category.get('content', ''))
        
        return NovelInfo(
            title=title,
            author=author,
            description=description,
            cover_url=cover_url,
            language="zh",
            tags=tags,
            source_url=url
        )
    
    def get_chapter_list(self, url: str) -> List[Chapter]:
        """
        Get full chapter list using AJAX endpoint.
        This bypasses the "Load More" button entirely.
        """
        book_id = self._extract_book_id(url)
        if not book_id:
            raise ValueError(f"Could not extract book ID from URL: {url}")
        
        # First visit the main page (sets cookies, passes any checks)
        print(f"  Visiting main page first...")
        self.fetch_page(url)
        
        # Fetch full chapter list from AJAX endpoint
        ajax_url = f"https://twkan.com/ajax_novels/chapterlist/{book_id}.html"
        print(f"  Fetching chapters from: {ajax_url}")
        
        # Use fetch_html which handles browser/session automatically
        html = self.fetch_html(ajax_url)
        
        # Parse the response - it's HTML with <ul><li><a>...</a></li>...</ul>
        soup = BeautifulSoup(html, 'lxml')
        
        chapters = []
        for idx, link in enumerate(soup.select("ul li a")):
            href = link.get('href', '')
            if '/txt/' not in href:
                continue
            
            # Make sure URL is absolute
            if not href.startswith('http'):
                href = f"https://twkan.com{href}"
            
            title = link.get_text(strip=True)
            
            chapters.append(Chapter(
                title=title,
                url=href,
                index=idx
            ))
        
        return chapters
    
    def get_chapter_content(self, chapter: Chapter) -> str:
        """Fetch and extract content for a single chapter."""
        soup = self.fetch_page(chapter.url)
        
        # Content selector: #txtcontent0
        content_el = soup.select_one("#txtcontent0")
        if not content_el:
            return f"<p>Failed to extract content from {chapter.url}</p>"
        
        # Get chapter title
        title_el = soup.select_one(".txtnav h1, #container .txtnav h1, h1")
        chapter_title = title_el.get_text(strip=True) if title_el else chapter.title
        
        # Remove unwanted elements
        for selector in ['script', '.ads', '.ad', '.txtad', '.txtcenter', 
                         'ins.adsbygoogle', '.advertisement']:
            for el in content_el.select(selector):
                el.decompose()
        
        # Build HTML content
        html = f"<h1>{chapter_title}</h1>\n"
        html += str(content_el)
        
        return html


# For testing
if __name__ == "__main__":
    parser = TwkanParser()
    
    test_url = "https://twkan.com/book/76222.html"
    
    print("Fetching novel info...")
    info = parser.get_novel_info(test_url)
    print(f"Title: {info.title}")
    print(f"Author: {info.author}")
    print(f"Description: {info.description[:100]}...")
    print(f"Cover: {info.cover_url}")
    
    print("\nFetching chapter list...")
    chapters = parser.get_chapter_list(test_url)
    print(f"Found {len(chapters)} chapters")
    
    if chapters:
        print(f"\nFirst chapter: {chapters[0]}")
        print(f"Last chapter: {chapters[-1]}")
        
        print("\nFetching first chapter content...")
        content = parser.get_chapter_content(chapters[0])
        print(f"Content length: {len(content)} chars")
        print(f"Preview: {content[:200]}...")
