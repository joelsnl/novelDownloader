"""
EPUB Builder - Create EPUB files from chapters
Uses ebooklib for EPUB creation
"""

import os
import io
import re
import requests
from typing import List, Optional, Callable
from pathlib import Path

from ebooklib import epub

from core.parser import Chapter, NovelInfo
from core.cleaner import ContentCleaner, is_chinese


class EPUBBuilder:
    """Build EPUB files from novel chapters."""
    
    def __init__(self, cleaner: Optional[ContentCleaner] = None):
        self.cleaner = cleaner or ContentCleaner()
    
    def build(
        self,
        novel_info: NovelInfo,
        chapters: List[Chapter],
        output_path: str,
        progress_callback: Optional[Callable[[int, int, str], None]] = None
    ) -> str:
        """
        Build an EPUB file from chapters.
        
        Args:
            novel_info: Novel metadata
            chapters: List of chapters with content loaded
            output_path: Where to save the EPUB
            progress_callback: Optional callback(current, total, status)
            
        Returns:
            Path to the created EPUB file
        """
        book = epub.EpubBook()
        
        # Set metadata
        book.set_identifier(f"novel-{hash(novel_info.title)}")
        book.set_title(novel_info.title)
        book.set_language(novel_info.language)
        book.add_author(novel_info.author)
        
        if novel_info.description:
            book.add_metadata('DC', 'description', novel_info.description)
        
        if novel_info.source_url:
            book.add_metadata('DC', 'source', novel_info.source_url)
        
        for tag in novel_info.tags:
            book.add_metadata('DC', 'subject', tag)
        
        # Add cover image if available
        if novel_info.cover_url:
            try:
                cover_data = self._download_image(novel_info.cover_url)
                if cover_data:
                    # Determine image type
                    ext = 'jpg'
                    if novel_info.cover_url.lower().endswith('.png'):
                        ext = 'png'
                    elif novel_info.cover_url.lower().endswith('.gif'):
                        ext = 'gif'
                    
                    book.set_cover(f"cover.{ext}", cover_data)
            except Exception as e:
                print(f"Warning: Could not download cover image: {e}")
        
        # Create chapter items
        epub_chapters = []
        spine = ['nav']
        
        total = len(chapters)
        for idx, chapter in enumerate(chapters):
            if progress_callback:
                progress_callback(idx + 1, total, f"Adding chapter: {chapter.title[:30]}...")
            
            # Clean content
            content = chapter.content
            if self.cleaner:
                content = self.cleaner.clean_html(content)
            
            # Create EPUB chapter
            chapter_filename = f"chapter_{idx:04d}.xhtml"
            epub_chapter = epub.EpubHtml(
                title=chapter.title,
                file_name=chapter_filename,
                lang=novel_info.language
            )
            
            # Wrap content in proper XHTML
            epub_chapter.content = self._wrap_xhtml(chapter.title, content)
            
            book.add_item(epub_chapter)
            epub_chapters.append(epub_chapter)
            spine.append(epub_chapter)
        
        # Add navigation
        book.toc = epub_chapters
        book.spine = spine
        
        # Add required NCX and Nav
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())
        
        # Add CSS
        css = self._get_default_css()
        nav_css = epub.EpubItem(
            uid="style_nav",
            file_name="style/nav.css",
            media_type="text/css",
            content=css.encode('utf-8')
        )
        book.add_item(nav_css)
        
        # Write EPUB
        if progress_callback:
            progress_callback(total, total, "Writing EPUB file...")
        
        epub.write_epub(output_path, book, {})
        
        return output_path
    
    def _download_image(self, url: str) -> Optional[bytes]:
        """Download an image and return bytes."""
        try:
            response = requests.get(url, timeout=30, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0'
            })
            response.raise_for_status()
            return response.content
        except Exception:
            return None
    
    def _wrap_xhtml(self, title: str, content: str) -> str:
        """Wrap content in proper XHTML structure."""
        # Escape title for XML
        title = title.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        
        return f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" lang="zh">
<head>
    <meta charset="UTF-8"/>
    <title>{title}</title>
    <link rel="stylesheet" type="text/css" href="style/nav.css"/>
</head>
<body>
{content}
</body>
</html>'''
    
    def _get_default_css(self) -> str:
        """Get default CSS for the EPUB."""
        return '''
body {
    font-family: Georgia, "Times New Roman", serif;
    font-size: 1em;
    line-height: 1.6;
    margin: 1em;
    padding: 0;
}

h1 {
    font-size: 1.5em;
    margin-bottom: 1em;
    text-align: center;
}

h2 {
    font-size: 1.3em;
    margin-top: 1.5em;
    margin-bottom: 0.5em;
}

p {
    margin: 0.5em 0;
    text-indent: 2em;
}

.chapter-title {
    text-align: center;
    font-weight: bold;
    margin-bottom: 1em;
}
'''


class TranslatedEPUBBuilder(EPUBBuilder):
    """
    EPUB Builder with translation support.
    Integrates with the translator to translate content as it's added.
    """
    
    def __init__(
        self, 
        cleaner: Optional[ContentCleaner] = None,
        translator = None
    ):
        super().__init__(cleaner)
        self.translator = translator
    
    def build_with_translation(
        self,
        novel_info: NovelInfo,
        chapters: List[Chapter],
        output_path: str,
        progress_callback: Optional[Callable[[int, int, str], None]] = None
    ) -> str:
        """
        Build EPUB with translation.
        First collects all Chinese text, translates in batch, then builds EPUB.
        """
        if not self.translator:
            # No translator, just build normally
            return self.build(novel_info, chapters, output_path, progress_callback)
        
        total_steps = len(chapters) * 2  # Clean + Translate phases
        current_step = 0
        
        # Phase 1: Clean all chapters and collect Chinese text
        if progress_callback:
            progress_callback(0, total_steps, "Cleaning chapters...")
        
        all_texts = []  # List of (chapter_idx, text)
        
        for idx, chapter in enumerate(chapters):
            current_step += 1
            if progress_callback:
                progress_callback(current_step, total_steps, f"Cleaning: {chapter.title[:30]}...")
            
            # Clean content
            if self.cleaner:
                chapter.content = self.cleaner.clean_html(chapter.content)
            
            # Extract Chinese text segments for translation
            # Simple approach: find all text between tags
            texts = self._extract_text_segments(chapter.content)
            for text in texts:
                if is_chinese(text) and len(text.strip()) > 0:
                    all_texts.append((idx, text))
        
        # Phase 2: Translate all texts
        if all_texts and progress_callback:
            progress_callback(current_step, total_steps, f"Translating {len(all_texts)} segments...")
        
        if all_texts:
            texts_to_translate = [t[1] for t in all_texts]
            
            def translate_progress(completed, total):
                nonlocal current_step
                if progress_callback:
                    pct = (completed / total) * len(chapters)
                    progress_callback(
                        int(len(chapters) + pct), 
                        total_steps, 
                        f"Translating: {completed}/{total}"
                    )
            
            translated = self.translator.translate_texts(texts_to_translate, translate_progress)
            
            # Apply translations back to chapters
            for i, (chapter_idx, original) in enumerate(all_texts):
                if translated[i] and translated[i] != original:
                    chapters[chapter_idx].content = chapters[chapter_idx].content.replace(
                        original, translated[i], 1
                    )
        
        # Phase 3: Build EPUB
        return self.build(novel_info, chapters, output_path, progress_callback)
    
    def _extract_text_segments(self, html: str) -> List[str]:
        """Extract text segments from HTML for translation."""
        from bs4 import BeautifulSoup
        
        soup = BeautifulSoup(html, 'lxml')
        texts = []
        
        # Get all text nodes
        for element in soup.find_all(text=True):
            text = str(element).strip()
            if text and len(text) > 1:
                # Skip if it's just whitespace or punctuation
                if re.search(r'[\u4e00-\u9fff]', text):
                    texts.append(text)
        
        return texts
