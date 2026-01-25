"""
Google Translate (Free) - Concurrent translation with retry logic
Based on fixTranslate.py GoogleFreeTranslate implementation
"""

import requests
import time
import threading
import concurrent.futures
from typing import List, Tuple, Dict, Optional, Callable


class GoogleTranslator:
    """Google Translate Free API with concurrent requests and retry logic."""
    
    ENDPOINT = 'https://translate.googleapis.com/translate_a/single'
    USER_AGENT = (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
        '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    )
    
    def __init__(
        self,
        source_lang: str = 'zh-CN',
        target_lang: str = 'en',
        max_workers: int = 50,
        request_timeout: int = 15,
        max_retries: int = 5,
        request_interval: float = 0.0
    ):
        self.source_lang = source_lang
        self.target_lang = target_lang
        self.max_workers = max_workers
        self.request_timeout = request_timeout
        self.max_retries = max_retries
        self.request_interval = request_interval
        
        # Statistics
        self.stats = {
            'requests': 0,
            'paragraphs_translated': 0,
            'characters_translated': 0,
            'cache_hits': 0,
            'errors': 0,
            'retries': 0
        }
        
        # Thread-safe cache and counters
        self.cache: Dict[str, str] = {}
        self.cache_lock = threading.Lock()
        self.stats_lock = threading.Lock()
        self.progress_lock = threading.Lock()
        
        # Progress tracking
        self.completed = 0
        self.total = 0
        self.progress_callback: Optional[Callable[[int, int], None]] = None
        
        # Failed texts for reporting
        self.failed_texts: List[Tuple[int, str]] = []
        self.failed_lock = threading.Lock()
        
        # Control flag
        self._cancel_requested = False
    
    def cancel(self):
        """Request cancellation of ongoing translation."""
        self._cancel_requested = True
    
    def _translate_single(self, text: str, index: int) -> Tuple[int, str]:
        """Translate a single text with exponential backoff retry."""
        if self._cancel_requested:
            return (index, text)
            
        if not text or not text.strip():
            return (index, text)
        
        cache_key = text.strip()
        
        # Check cache
        with self.cache_lock:
            if cache_key in self.cache:
                with self.stats_lock:
                    self.stats['cache_hits'] += 1
                self._update_progress()
                return (index, self.cache[cache_key])
        
        params = {
            'client': 'gtx',
            'sl': self.source_lang,
            'tl': self.target_lang,
            'dt': 't',
            'dj': '1',
            'q': text
        }
        
        last_error = None
        for attempt in range(self.max_retries):
            if self._cancel_requested:
                return (index, text)
                
            try:
                # Use GET for short texts, POST for long texts
                if len(text) <= 1800:
                    response = requests.get(
                        self.ENDPOINT,
                        params=params,
                        headers={'User-Agent': self.USER_AGENT},
                        timeout=self.request_timeout
                    )
                else:
                    response = requests.post(
                        self.ENDPOINT,
                        data=params,
                        headers={'User-Agent': self.USER_AGENT},
                        timeout=self.request_timeout
                    )
                
                response.raise_for_status()
                data = response.json()
                
                # Extract translated text
                translated = ''.join(
                    s.get('trans', '') 
                    for s in data.get('sentences', []) 
                    if 'trans' in s
                )
                
                if translated and translated.strip():
                    # Cache the result
                    with self.cache_lock:
                        self.cache[cache_key] = translated
                    
                    with self.stats_lock:
                        self.stats['requests'] += 1
                        self.stats['paragraphs_translated'] += 1
                        self.stats['characters_translated'] += len(text)
                        if attempt > 0:
                            self.stats['retries'] += attempt
                    
                    self._update_progress()
                    
                    if self.request_interval > 0:
                        time.sleep(self.request_interval)
                    
                    return (index, translated)
                else:
                    raise ValueError("Empty translation response")
                    
            except Exception as e:
                last_error = e
                if attempt < self.max_retries - 1:
                    # Exponential backoff: 2, 4, 8, 16... seconds
                    wait_time = 2 ** (attempt + 1)
                    time.sleep(wait_time)
        
        # All retries failed
        with self.failed_lock:
            preview = text[:50] + '...' if len(text) > 50 else text
            self.failed_texts.append((index, preview))
        
        with self.stats_lock:
            self.stats['errors'] += 1
        
        self._update_progress()
        return (index, text)  # Return original on failure
    
    def _update_progress(self):
        """Update progress counter and call callback if set."""
        with self.progress_lock:
            self.completed += 1
            if self.progress_callback and self.total > 0:
                self.progress_callback(self.completed, self.total)
    
    def translate_texts(
        self,
        texts: List[str],
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> List[str]:
        """
        Translate a list of texts concurrently.
        
        Args:
            texts: List of texts to translate
            progress_callback: Optional callback(completed, total) for progress updates
            
        Returns:
            List of translated texts in same order as input
        """
        if not texts:
            return []
        
        self._cancel_requested = False
        self.total = len(texts)
        self.completed = 0
        self.failed_texts = []
        self.progress_callback = progress_callback
        
        workers = min(self.max_workers, len(texts))
        results = [''] * len(texts)
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(self._translate_single, text, i): i 
                for i, text in enumerate(texts)
            }
            
            for future in concurrent.futures.as_completed(futures):
                if self._cancel_requested:
                    break
                try:
                    index, translated = future.result()
                    results[index] = translated
                except Exception:
                    index = futures[future]
                    results[index] = texts[index]
        
        return results
    
    def translate_text(self, text: str) -> str:
        """Translate a single text (convenience method)."""
        results = self.translate_texts([text])
        return results[0] if results else text
    
    @staticmethod
    def is_chinese(text: str) -> bool:
        """Check if text contains significant Chinese characters."""
        if not text:
            return False
        import re
        chinese_count = len(re.findall(r'[\u4e00-\u9fff\u3400-\u4dbf]', text))
        return chinese_count > len(text) * 0.1  # More than 10% Chinese
    
    def get_stats(self) -> Dict:
        """Get translation statistics."""
        return self.stats.copy()
    
    def reset_stats(self):
        """Reset statistics."""
        self.stats = {
            'requests': 0,
            'paragraphs_translated': 0,
            'characters_translated': 0,
            'cache_hits': 0,
            'errors': 0,
            'retries': 0
        }
        self.failed_texts.clear()
    
    def clear_cache(self):
        """Clear the translation cache."""
        with self.cache_lock:
            self.cache.clear()
