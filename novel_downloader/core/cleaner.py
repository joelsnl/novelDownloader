"""
XHTML/Content Cleaner - Remove watermarks, ads, and fix structure
Based on fixTranslate.py XHTMLProcessor
"""

import re
from typing import List, Optional, Set
from lxml import etree
from lxml import html as lxml_html


# ============================================================================
# CONSTANTS
# ============================================================================
XHTML_NS = 'http://www.w3.org/1999/xhtml'
XHTML = lambda name: f'{{{XHTML_NS}}}{name}'

# Tags that should NOT be self-closing in EPUB output
SELF_CLOSING_BAD_TAGS = {
    'a', 'abbr', 'address', 'article', 'aside', 'audio', 'b',
    'bdo', 'blockquote', 'body', 'button', 'cite', 'code', 'dd', 'del', 'details',
    'dfn', 'div', 'dl', 'dt', 'em', 'fieldset', 'figcaption', 'figure', 'footer',
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'header', 'hgroup', 'i', 'iframe', 'ins', 'kbd',
    'label', 'legend', 'li', 'map', 'mark', 'meter', 'nav', 'ol', 'output', 'p',
    'pre', 'progress', 'q', 'rp', 'rt', 'samp', 'section', 'select', 'small',
    'span', 'strong', 'sub', 'summary', 'sup', 'textarea', 'time', 'ul', 'var',
    'video', 'title', 'script', 'style'
}

# Elements to remove entirely
REMOVE_ELEMENTS = {'script', 'embed', 'object', 'form', 'input', 'button', 'textarea'}

# Invisible characters to remove
INVISIBLE_CHARS = '\u200b\u200c\u200d\ufeff\u00ad\u2060\u180e\u200e\u200f\u202a\u202b\u202c\u202d\u202e'

# Ad div classes to remove
REMOVE_DIV_CLASSES = {'txtad', 'ad', 'advertisement', 'ads', 'adsbygoogle'}

# Default watermark patterns
DEFAULT_WATERMARKS = [
    # Standard Chinese watermarks
    r'本書由.{0,30}首發', r'本文由.{0,30}首發', r'正版請.{0,30}閱讀',
    r'請到.{0,30}閱讀', r'最新章節.{0,30}閱讀', r'手機閱讀.{0,50}',
    r'訪問下載.{0,50}', r'更多精彩.{0,50}', r'歡迎廣大書友.{0,50}',
    r'喜歡請收藏.{0,50}', r'請記住本書.{0,50}', r'百度搜索.{0,50}',
    r'最快更新.{0,50}', r'無彈窗.{0,30}',
    r'關注公眾號.{0,50}', r'微信公眾號.{0,50}', r'掃碼關注.{0,50}',
    r'點擊下載.{0,50}', r'APP下載.{0,50}',
    r'本書首發.{0,80}',
    r'提供給你無錯章節.{0,50}',
    r'台灣小說網.{0,30}',
    r'twkan\.com',
    
    # Fullwidth alphanumeric URLs (ａｂｃ style)
    r'[ａ-ｚＡ-Ｚ０-９]+\.[ａ-ｚＡ-Ｚ]+',
    
    # Double-struck/mathematical alphanumeric URLs
    r'[𝕒-𝕫𝔸-𝕫𝟘-𝟡]+\.[𝕒-𝕫𝔸-𝕫]+',
    
    # Sans-serif bold
    r'[𝖺-𝗓𝖠-𝗓𝟢-𝟫]+\.[𝖺-𝗓𝖠-𝗓]+',
    r'[\U0001D5BA-\U0001D5D3\U0001D5A0-\U0001D5B9]+\.[\U0001D5BA-\U0001D5D3\U0001D5A0-\U0001D5B9]+',
    
    # Sans-serif
    r'[\U0001D5A0-\U0001D5D3]+\.[\U0001D5A0-\U0001D5D3]+',
    
    # Monospace
    r'[\U0001D68A-\U0001D6A3\U0001D670-\U0001D689]+\.[\U0001D68A-\U0001D6A3]+',
    
    # General math alphanumeric
    r'[\U0001D400-\U0001D7FF]+\.[\U0001D400-\U0001D7FF]+',
    
    # Arrow followed by stylized URL
    r'→\s*[\U0001D400-\U0001D7FFａ-ｚＡ-Ｚ０-９]+\.[\U0001D400-\U0001D7FFａ-ｚＡ-Ｚ]+',
]


class ContentCleaner:
    """Clean HTML/XHTML content - remove watermarks, ads, fix structure."""
    
    def __init__(self, custom_watermarks: List[str] = None):
        self.watermark_patterns = []
        
        all_patterns = DEFAULT_WATERMARKS + (custom_watermarks or [])
        for pattern in all_patterns:
            try:
                self.watermark_patterns.append(re.compile(pattern, re.IGNORECASE))
            except re.error:
                pass
        
        self.stats = {
            'elements_removed': 0,
            'empty_tags_removed': 0,
            'watermarks_removed': 0,
            'chars_cleaned': 0,
            'ad_divs_removed': 0,
            'self_closing_fixed': 0
        }
    
    def reset_stats(self):
        """Reset statistics."""
        for key in self.stats:
            self.stats[key] = 0
    
    def clean_text(self, text: str) -> str:
        """Clean text content - remove watermarks and invisible chars."""
        if not text:
            return text
        
        original = text
        
        # Remove invisible characters
        for char in INVISIBLE_CHARS:
            text = text.replace(char, '')
        
        # Replace non-breaking hyphen
        text = text.replace('\u2011', '-')
        
        # Remove watermarks
        for pattern in self.watermark_patterns:
            new_text = pattern.sub('', text)
            if new_text != text:
                self.stats['watermarks_removed'] += 1
                text = new_text
        
        if text != original:
            self.stats['chars_cleaned'] += 1
        
        return text
    
    def clean_html(self, html_content: str) -> str:
        """Clean HTML content and return cleaned HTML string."""
        try:
            # Parse HTML
            root = lxml_html.fromstring(html_content)
            
            # Clean content
            root = self._clean_content(root)
            
            # Serialize back to string
            return lxml_html.tostring(root, encoding='unicode')
        except Exception as e:
            # If parsing fails, do basic text cleaning
            return self._clean_text_only(html_content)
    
    def _clean_text_only(self, text: str) -> str:
        """Fallback: just clean the text without parsing."""
        return self.clean_text(text)
    
    def _clean_content(self, root) -> etree._Element:
        """Clean content - remove bad elements, fix text, etc."""
        
        # Remove forbidden elements
        for tag in REMOVE_ELEMENTS:
            for elem in root.iter(tag):
                self._remove_element_keep_tail(elem)
                self.stats['elements_removed'] += 1
        
        # Remove empty ad divs
        for elem in root.iter('div'):
            class_attr = elem.get('class', '')
            classes = set(class_attr.lower().split())
            if classes & REMOVE_DIV_CLASSES:
                # Check if it's empty or only whitespace
                has_content = False
                if elem.text and elem.text.strip():
                    has_content = True
                for child in elem:
                    if child.tag not in [etree.Comment]:
                        has_content = True
                        break
                    if child.tail and child.tail.strip():
                        has_content = True
                        break
                
                if not has_content:
                    self._remove_element_keep_tail(elem)
                    self.stats['ad_divs_removed'] += 1
        
        # Remove empty inline tags
        for tag in ['a', 'i', 'b', 'u', 'span', 'em', 'strong']:
            for elem in root.iter(tag):
                if (elem.get('id') is None and elem.get('name') is None and
                    len(elem) == 0 and not (elem.text and elem.text.strip())):
                    self._remove_element_keep_tail(elem)
                    self.stats['empty_tags_removed'] += 1
        
        # Clean text content
        for elem in root.iter():
            if elem.text:
                elem.text = self.clean_text(elem.text)
            if elem.tail:
                elem.tail = self.clean_text(elem.tail)
        
        return root
    
    def _remove_element_keep_tail(self, elem):
        """Remove element but keep its tail text."""
        parent = elem.getparent()
        if parent is None:
            return
        
        idx = list(parent).index(elem)
        if elem.tail:
            if idx > 0:
                prev = parent[idx - 1]
                prev.tail = (prev.tail or '') + elem.tail
            else:
                parent.text = (parent.text or '') + elem.tail
        parent.remove(elem)
    
    def get_stats(self) -> dict:
        """Get cleaning statistics."""
        return self.stats.copy()


def is_chinese(text: str) -> bool:
    """Check if text contains Chinese characters."""
    if not text:
        return False
    return bool(re.search(r'[\u4e00-\u9fff\u3400-\u4dbf]', text))


def count_chinese_chars(text: str) -> int:
    """Count Chinese characters in text."""
    if not text:
        return 0
    return len(re.findall(r'[\u4e00-\u9fff\u3400-\u4dbf]', text))
