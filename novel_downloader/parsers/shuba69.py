# Author: joelsnl and Anthropic Claude
"""
Parser for 69shuba.com / 69shu.com (六九书吧)
Based on WebToEpub 69shuParser.js

Note: This site uses GB18030 encoding for text.
"""

import re
import concurrent.futures
from typing import List, Optional, Tuple
from urllib.parse import urljoin
from bs4 import BeautifulSoup

from core.parser import BaseParser, Chapter, NovelInfo, register_parser


@register_parser
class Shuba69Parser(BaseParser):
    """Parser for 69shuba.com and related 69shu sites."""
    
    SITE_NAME = "69shuba.com"
    SITE_DOMAINS = ["69shuba.com", "69shu.com", "69shuba.cx", "69shu.pro", "69shuba.pro"]
    
    def __init__(self):
        super().__init__()
        # Minimum delay between requests (site can be sensitive)
        self.request_delay = 1.0
    
    def _extract_book_id(self, url: str) -> Optional[str]:
        """Extract book ID from URL."""
        # Matches: /book/12345.htm, /txt/12345/index.html, etc.
        match = re.search(r'/(?:book|txt)/(\d+)', url)
        return match.group(1) if match else None
    
    def _fetch_with_encoding(self, url: str, retries: int = 3) -> BeautifulSoup:
        """
        Fetch page with GB18030 encoding (site doesn't declare encoding properly).
        """
        last_error = None
        rate_limit_retry = 0
        
        for attempt in range(retries):
            try:
                response = self.session.get(url, timeout=30)
                
                if response.status_code == 429:
                    if rate_limit_retry < len(self.rate_limit_delays):
                        wait = self.rate_limit_delays[rate_limit_retry]
                        print(f"  Rate limited (429). Waiting {wait}s...")
                        import time
                        time.sleep(wait)
                        rate_limit_retry += 1
                        continue
                
                response.raise_for_status()
                
                # Decode with GB18030 encoding
                content = response.content.decode('gb18030', errors='replace')
                return BeautifulSoup(content, 'lxml')
                
            except Exception as e:
                last_error = e
                print(f"  Attempt {attempt + 1}/{retries} failed: {e}")
                if attempt < retries - 1:
                    import time
                    time.sleep(2 ** (attempt + 1))
        
        raise last_error
    
    def fetch_all_parallel(self, url: str) -> Tuple[NovelInfo, List[Chapter]]:
        """
        Fetch novel info and chapter list in parallel.
        """
        # First get the main page to find TOC URL
        print(f"  Fetching main page...")
        main_soup = self._fetch_with_encoding(url)
        
        # Find TOC URL (the "more" button)
        toc_link = main_soup.select_one("a.more-btn")
        if not toc_link:
            raise ValueError("Could not find chapter list link (a.more-btn)")
        
        toc_url = toc_link.get('href', '')
        if not toc_url.startswith('http'):
            toc_url = urljoin(url, toc_url)
        
        print(f"  Fetching TOC from: {toc_url}")
        toc_soup = self._fetch_with_encoding(toc_url)
        
        # Parse novel info from main page
        novel_info = self._parse_novel_info(main_soup, url)
        
        # Parse chapter list from TOC page
        chapters = self._parse_chapter_list(toc_soup, toc_url)
        
        return novel_info, chapters
    
    def _parse_novel_info(self, soup: BeautifulSoup, url: str) -> NovelInfo:
        """Parse novel info from main page."""
        title = ""
        author = "Unknown"
        description = ""
        cover_url = None
        tags = []
        
        # Title: div.booknav2 h1
        title_el = soup.select_one("div.booknav2 h1")
        if title_el:
            title = title_el.get_text(strip=True)
        
        # Author: second link in .booknav2
        author_links = soup.select(".booknav2 a")
        if len(author_links) >= 2:
            author = author_links[1].get_text(strip=True)
        
        # Cover image: first img in div.bookbox
        cover_el = soup.select_one("div.bookbox img")
        if cover_el:
            cover_url = cover_el.get('src', '')
            if cover_url and not cover_url.startswith('http'):
                cover_url = urljoin(url, cover_url)
        
        # Description: div.navtxt or similar
        desc_el = soup.select_one(".navtxt p, .bookintro")
        if desc_el:
            description = desc_el.get_text(strip=True)
        
        # Try to get category/tags
        category_el = soup.select_one(".booknav2 a[href*='sort']")
        if category_el:
            tags.append(category_el.get_text(strip=True))
        
        return NovelInfo(
            title=title,
            author=author,
            description=description,
            cover_url=cover_url,
            language="zh",
            tags=tags,
            source_url=url
        )
    
    def _parse_chapter_list(self, soup: BeautifulSoup, base_url: str) -> List[Chapter]:
        """Parse chapter list from TOC page."""
        chapters = []
        
        # Chapter links are in #catalog ul
        menu = soup.select_one("#catalog ul")
        if not menu:
            # Fallback: try other common selectors
            menu = soup.select_one(".catalog ul, .mulu ul, #list ul")
        
        if not menu:
            print("  Warning: Could not find chapter list container")
            return chapters
        
        for idx, link in enumerate(menu.select("a")):
            href = link.get('href', '')
            if not href:
                continue
            
            # Make URL absolute
            if not href.startswith('http'):
                href = urljoin(base_url, href)
            
            title = link.get_text(strip=True)
            if not title:
                continue
            
            chapters.append(Chapter(
                title=title,
                url=href,
                index=idx
            ))
        
        # 69shu lists chapters in reverse order (newest first), so reverse them
        chapters.reverse()
        
        # Re-index after reversing
        for idx, chapter in enumerate(chapters):
            chapter.index = idx
        
        print(f"  Found {len(chapters)} chapters")
        return chapters
    
    def get_novel_info(self, url: str) -> NovelInfo:
        """Extract novel metadata from main page."""
        soup = self._fetch_with_encoding(url)
        return self._parse_novel_info(soup, url)
    
    def get_chapter_list(self, url: str) -> List[Chapter]:
        """Get full chapter list."""
        # First get main page to find TOC link
        print(f"  Fetching main page...")
        main_soup = self._fetch_with_encoding(url)
        
        # Find TOC URL
        toc_link = main_soup.select_one("a.more-btn")
        if not toc_link:
            raise ValueError("Could not find chapter list link")
        
        toc_url = toc_link.get('href', '')
        if not toc_url.startswith('http'):
            toc_url = urljoin(url, toc_url)
        
        print(f"  Fetching TOC from: {toc_url}")
        toc_soup = self._fetch_with_encoding(toc_url)
        
        return self._parse_chapter_list(toc_soup, toc_url)
    
    def get_chapter_content(self, chapter: Chapter) -> str:
        """Fetch and extract content for a single chapter."""
        soup = self._fetch_with_encoding(chapter.url)
        
        # Content is in div.txtnav
        content_el = soup.select_one("div.txtnav")
        if not content_el:
            return f"<p>Failed to extract content from {chapter.url}</p>"
        
        # Remove unwanted elements
        for selector in ['.txtinfo', '#txtright', '.bottom-ad', 'script', 
                         '.ads', '.ad', 'ins.adsbygoogle']:
            for el in content_el.select(selector):
                el.decompose()
        
        # Get chapter title from page (might be more accurate than TOC title)
        title_el = soup.select_one("h1, .txtnav h1")
        chapter_title = title_el.get_text(strip=True) if title_el else chapter.title
        
        # Build HTML content
        html = f"<h1>{chapter_title}</h1>\n"
        html += str(content_el)
        
        return html


# For testing
if __name__ == "__main__":
    parser = Shuba69Parser()
    
    test_url = "https://www.69shuba.com/book/12345.htm"  # Replace with actual URL
    
    print("Fetching novel info...")
    try:
        info = parser.get_novel_info(test_url)
        print(f"Title: {info.title}")
        print(f"Author: {info.author}")
        print(f"Cover: {info.cover_url}")
        
        print("\nFetching chapter list...")
        chapters = parser.get_chapter_list(test_url)
        print(f"Found {len(chapters)} chapters")
        
        if chapters:
            print(f"\nFirst chapter: {chapters[0]}")
            print(f"Last chapter: {chapters[-1]}")
    except Exception as e:
        print(f"Error: {e}")
