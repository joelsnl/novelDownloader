#!/usr/bin/env python3
"""
Novel Downloader & Translator
A standalone GUI application for downloading and translating web novels to EPUB.

Based on WebToEpub extension and fixTranslate.py

Author: joelsnl and Anthropic Claude
"""

import os
import sys
import time
import threading
import tkinter as tk
from tkinter import filedialog, messagebox
from pathlib import Path
from typing import List, Optional
from io import BytesIO

import customtkinter as ctk
from PIL import Image

# Try curl_cffi for HTTP requests (better compatibility)
try:
    from curl_cffi.requests import Session as HttpSession
    http_session = HttpSession(impersonate="chrome120")
except ImportError:
    import requests
    http_session = requests.Session()
    http_session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0'
    })

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.parser import Chapter, NovelInfo, get_parser_for_url, cleanup_browser
from core.cleaner import ContentCleaner
from core.translator import GoogleTranslator
from core.epub_builder import EPUBBuilder, TranslatedEPUBBuilder
from core.updater import (
    get_current_version, check_for_updates_async, download_update_async,
    get_auto_check_updates, set_auto_check_updates, is_frozen
)

# Import parsers to register them
import parsers


# Set appearance
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


class NovelDownloaderApp(ctk.CTk):
    """Main application window."""
    
    def __init__(self):
        super().__init__()
        
        self.title(f"Novel Downloader & Translator v{get_current_version()}")
        self.geometry("900x700")
        self.minsize(800, 600)
        
        # Get app directory for auto-save
        self.app_dir = Path(os.path.dirname(os.path.abspath(__file__)))
        
        # State
        self.novel_info: Optional[NovelInfo] = None
        self.chapters: List[Chapter] = []
        self.parser = None
        self.is_downloading = False
        self.cancel_requested = False
        self.cover_image = None  # Store PhotoImage reference
        self.translated_title = None  # Store translated title
        
        # Multi-download mode state
        self.multi_mode = False
        self.multi_url_entries: List[ctk.CTkEntry] = []
        self.multi_novels: List[dict] = []  # [{url, parser, info, chapters, status, translated_title}]
        self.multi_result_labels: List[dict] = []  # UI labels for each novel row
        
        # Create UI
        self._create_ui()
        
        # Cleanup browser on close
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        
        # Auto-check for updates on startup (if enabled)
        if get_auto_check_updates():
            self.after(2000, self._auto_check_updates)  # Check after 2 seconds
    
    def _on_close(self):
        """Handle window close - cleanup browser."""
        try:
            cleanup_browser()
        except:
            pass
        self.destroy()
    
    def _create_ui(self):
        """Create all UI elements."""
        
        # Configure grid
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        
        # === Mode Toggle + URL Input Section ===
        url_frame = ctk.CTkFrame(self)
        url_frame.grid(row=0, column=0, padx=10, pady=(10, 5), sticky="ew")
        url_frame.grid_columnconfigure(1, weight=1)
        
        # Mode toggle
        self.mode_switch = ctk.CTkSegmentedButton(
            url_frame, values=["Single", "Multi"],
            command=self._on_mode_change, width=140
        )
        self.mode_switch.set("Single")
        self.mode_switch.grid(row=0, column=0, padx=(10, 5), pady=10)
        
        # Single-mode URL entry
        self.single_url_frame = ctk.CTkFrame(url_frame, fg_color="transparent")
        self.single_url_frame.grid(row=0, column=1, columnspan=2, padx=0, pady=0, sticky="ew")
        self.single_url_frame.grid_columnconfigure(0, weight=1)
        
        self.url_entry = ctk.CTkEntry(self.single_url_frame, placeholder_text="Enter novel URL (e.g., https://twkan.com/book/12345.html)")
        self.url_entry.grid(row=0, column=0, padx=5, pady=10, sticky="ew")
        
        self.fetch_btn = ctk.CTkButton(self.single_url_frame, text="Fetch Chapters", command=self._on_fetch)
        self.fetch_btn.grid(row=0, column=1, padx=(5, 10), pady=10)
        
        # === Single Mode: Novel Info Section (with cover preview) ===
        self.info_frame = ctk.CTkFrame(self)
        self.info_frame.grid(row=1, column=0, padx=10, pady=5, sticky="ew")
        self.info_frame.grid_columnconfigure(1, weight=1)
        
        # Cover image on the left
        self.cover_frame = ctk.CTkFrame(self.info_frame, width=100, height=140)
        self.cover_frame.grid(row=0, column=0, rowspan=3, padx=10, pady=10, sticky="ns")
        self.cover_frame.grid_propagate(False)
        
        self.cover_label = ctk.CTkLabel(self.cover_frame, text="No Cover", width=100, height=140)
        self.cover_label.pack(expand=True, fill="both")
        
        # Info on the right
        info_right = ctk.CTkFrame(self.info_frame, fg_color="transparent")
        info_right.grid(row=0, column=1, rowspan=3, padx=5, pady=5, sticky="nsew")
        info_right.grid_columnconfigure(1, weight=1)
        
        ctk.CTkLabel(info_right, text="Title:", font=("", 12)).grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.title_label = ctk.CTkLabel(info_right, text="-", font=("", 12, "bold"), wraplength=500, justify="left")
        self.title_label.grid(row=0, column=1, columnspan=3, padx=5, pady=5, sticky="w")
        
        ctk.CTkLabel(info_right, text="Author:", font=("", 12)).grid(row=1, column=0, padx=5, pady=5, sticky="w")
        self.author_label = ctk.CTkLabel(info_right, text="-", font=("", 12))
        self.author_label.grid(row=1, column=1, padx=5, pady=5, sticky="w")
        
        ctk.CTkLabel(info_right, text="Chapters:", font=("", 12)).grid(row=1, column=2, padx=(20, 5), pady=5, sticky="w")
        self.chapters_label = ctk.CTkLabel(info_right, text="0", font=("", 12))
        self.chapters_label.grid(row=1, column=3, padx=5, pady=5, sticky="w")
        
        ctk.CTkLabel(info_right, text="English Title:", font=("", 12)).grid(row=2, column=0, padx=5, pady=5, sticky="w")
        self.eng_title_label = ctk.CTkLabel(info_right, text="-", font=("", 11), wraplength=500, justify="left", text_color="gray")
        self.eng_title_label.grid(row=2, column=1, columnspan=3, padx=5, pady=5, sticky="w")
        
        # === Chapter List Section ===
        self.list_frame = ctk.CTkFrame(self)
        self.list_frame.grid(row=2, column=0, padx=10, pady=5, sticky="nsew")
        self.list_frame.grid_columnconfigure(0, weight=1)
        self.list_frame.grid_rowconfigure(1, weight=1)
        
        # Selection buttons
        btn_frame = ctk.CTkFrame(self.list_frame, fg_color="transparent")
        btn_frame.grid(row=0, column=0, padx=5, pady=5, sticky="ew")
        
        ctk.CTkButton(btn_frame, text="Select All", width=100, command=self._select_all).pack(side="left", padx=5)
        ctk.CTkButton(btn_frame, text="Select None", width=100, command=self._select_none).pack(side="left", padx=5)
        ctk.CTkButton(btn_frame, text="Invert", width=100, command=self._invert_selection).pack(side="left", padx=5)
        
        self.selected_label = ctk.CTkLabel(btn_frame, text="Selected: 0")
        self.selected_label.pack(side="right", padx=10)
        
        # Chapter listbox with checkboxes
        self.chapter_frame = ctk.CTkScrollableFrame(self.list_frame)
        self.chapter_frame.grid(row=1, column=0, padx=5, pady=5, sticky="nsew")
        self.chapter_frame.grid_columnconfigure(0, weight=1)
        
        self.chapter_vars: List[ctk.BooleanVar] = []
        self.chapter_checkboxes: List[ctk.CTkCheckBox] = []
        
        # === Multi Mode UI (hidden by default) ===
        self.multi_frame = ctk.CTkFrame(self)
        # Not gridded yet - shown when multi mode is activated
        self.multi_frame.grid_columnconfigure(0, weight=1)
        self.multi_frame.grid_rowconfigure(1, weight=1)
        
        # URL input area with scrollable list
        multi_url_section = ctk.CTkFrame(self.multi_frame)
        multi_url_section.grid(row=0, column=0, padx=5, pady=5, sticky="ew")
        multi_url_section.grid_columnconfigure(0, weight=1)
        
        multi_url_header = ctk.CTkFrame(multi_url_section, fg_color="transparent")
        multi_url_header.grid(row=0, column=0, padx=5, pady=5, sticky="ew")
        
        ctk.CTkLabel(multi_url_header, text="Novel URLs (max 7):", font=("", 13, "bold")).pack(side="left", padx=5)
        
        self.multi_add_btn = ctk.CTkButton(
            multi_url_header, text="+ Add URL", width=90, height=28,
            command=self._multi_add_url
        )
        self.multi_add_btn.pack(side="right", padx=5)
        
        self.multi_remove_btn = ctk.CTkButton(
            multi_url_header, text="- Remove", width=90, height=28,
            command=self._multi_remove_url,
            fg_color="gray40", hover_color="gray30"
        )
        self.multi_remove_btn.pack(side="right", padx=5)
        
        self.multi_fetch_btn = ctk.CTkButton(
            multi_url_header, text="Fetch All", width=100, height=28,
            command=self._on_multi_fetch, fg_color="#2B7A3E", hover_color="#236332"
        )
        self.multi_fetch_btn.pack(side="right", padx=5)
        
        # URL entries container
        self.multi_url_container = ctk.CTkFrame(multi_url_section, fg_color="transparent")
        self.multi_url_container.grid(row=1, column=0, padx=5, pady=(0, 5), sticky="ew")
        self.multi_url_container.grid_columnconfigure(1, weight=1)
        
        # Start with 2 URL fields
        for i in range(2):
            self._multi_create_url_row(i)
        
        # Results table
        self.multi_results_frame = ctk.CTkScrollableFrame(self.multi_frame, label_text="Novels")
        self.multi_results_frame.grid(row=1, column=0, padx=5, pady=5, sticky="nsew")
        self.multi_results_frame.grid_columnconfigure(1, weight=1)
        
        # Multi download button
        self.multi_download_btn = ctk.CTkButton(
            self.multi_frame,
            text="Download All",
            font=("", 14, "bold"),
            height=36, width=160,
            command=self._on_multi_download,
            state="disabled",
            fg_color="#2B7A3E", hover_color="#236332"
        )
        self.multi_download_btn.grid(row=2, column=0, pady=(5, 5))
        
        # === Options Section ===
        options_frame = ctk.CTkFrame(self)
        options_frame.grid(row=3, column=0, padx=10, pady=5, sticky="ew")
        
        # Left side - checkboxes
        left_opts = ctk.CTkFrame(options_frame, fg_color="transparent")
        left_opts.pack(side="left", padx=10, pady=10)
        
        self.clean_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(left_opts, text="Remove watermarks & ads", variable=self.clean_var).pack(anchor="w", pady=2)
        
        self.translate_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(left_opts, text="Translate to English", variable=self.translate_var).pack(anchor="w", pady=2)
        
        # Right side - workers
        right_opts = ctk.CTkFrame(options_frame, fg_color="transparent")
        right_opts.pack(side="right", padx=10, pady=10)
        
        ctk.CTkLabel(right_opts, text="Translation Workers:").pack(side="left", padx=5)
        self.workers_entry = ctk.CTkEntry(right_opts, width=60)
        self.workers_entry.insert(0, "200")
        self.workers_entry.pack(side="left", padx=5)
        
        # === Progress Section ===
        progress_frame = ctk.CTkFrame(self)
        progress_frame.grid(row=4, column=0, padx=10, pady=5, sticky="ew")
        progress_frame.grid_columnconfigure(0, weight=1)
        
        self.progress_bar = ctk.CTkProgressBar(progress_frame)
        self.progress_bar.grid(row=0, column=0, padx=10, pady=(10, 5), sticky="ew")
        self.progress_bar.set(0)
        
        self.status_label = ctk.CTkLabel(progress_frame, text="Ready")
        self.status_label.grid(row=1, column=0, padx=10, pady=(5, 10))
        
        # === Download Button ===
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.grid(row=5, column=0, padx=10, pady=10)
        
        self.download_btn = ctk.CTkButton(
            btn_frame, 
            text="Download EPUB", 
            font=("", 14, "bold"),
            height=40,
            width=200,
            command=self._on_download,
            state="disabled"
        )
        self.download_btn.pack(side="left", padx=5)
        
        self.cancel_btn = ctk.CTkButton(
            btn_frame,
            text="Cancel",
            height=40,
            width=100,
            command=self._on_cancel,
            state="disabled",
            fg_color="red",
            hover_color="darkred"
        )
        self.cancel_btn.pack(side="left", padx=5)
        
        # === Footer with Version and Update ===
        footer_frame = ctk.CTkFrame(self, fg_color="transparent")
        footer_frame.grid(row=6, column=0, padx=10, pady=(0, 10), sticky="ew")
        
        # Version label on left
        self.version_label = ctk.CTkLabel(
            footer_frame, 
            text=f"v{get_current_version()}", 
            font=("", 11),
            text_color="gray"
        )
        self.version_label.pack(side="left", padx=10)
        
        # Update section on right
        update_frame = ctk.CTkFrame(footer_frame, fg_color="transparent")
        update_frame.pack(side="right", padx=10)
        
        # Auto-update checkbox
        self.auto_update_var = ctk.BooleanVar(value=get_auto_check_updates())
        self.auto_update_cb = ctk.CTkCheckBox(
            update_frame, 
            text="Auto-check updates",
            variable=self.auto_update_var,
            command=self._on_auto_update_toggle,
            font=("", 11),
            checkbox_width=18,
            checkbox_height=18
        )
        self.auto_update_cb.pack(side="left", padx=(0, 10))
        
        # Check for updates button
        self.update_btn = ctk.CTkButton(
            update_frame,
            text="Check for Updates",
            width=130,
            height=28,
            font=("", 11),
            command=self._on_check_updates
        )
        self.update_btn.pack(side="left")
    
    def _on_fetch(self):
        """Handle fetch button click."""
        url = self.url_entry.get().strip()
        if not url:
            messagebox.showerror("Error", "Please enter a URL")
            return
        
        # Find appropriate parser
        self.parser = get_parser_for_url(url)
        if not self.parser:
            messagebox.showerror("Error", f"Unsupported site. URL: {url}")
            return
        
        # Disable UI
        self.fetch_btn.configure(state="disabled")
        self.status_label.configure(text="Fetching novel info...")
        self.progress_bar.set(0)
        
        # Run in thread
        thread = threading.Thread(target=self._fetch_thread, args=(url,))
        thread.daemon = True
        thread.start()
    
    def _fetch_thread(self, url: str):
        """Fetch novel info in background thread."""
        try:
            # Check if parser supports parallel fetching (faster)
            if hasattr(self.parser, 'fetch_all_parallel'):
                print(f"Fetching novel info and chapters in parallel...")
                self.after(0, lambda: self._update_status("Fetching novel info & chapters (parallel)..."))
                self.novel_info, self.chapters = self.parser.fetch_all_parallel(url)
                print(f"Got novel info: {self.novel_info.title}")
                print(f"Got {len(self.chapters)} chapters")
            else:
                # Fallback to sequential fetching
                print(f"Fetching novel info from: {url}")
                self.novel_info = self.parser.get_novel_info(url)
                print(f"Got novel info: {self.novel_info.title}")
                self.after(0, lambda: self._update_status("Fetching chapter list..."))
                
                print("Fetching chapter list...")
                self.chapters = self.parser.get_chapter_list(url)
                print(f"Got {len(self.chapters)} chapters")
            
            # Update UI in main thread
            self.after(0, self._update_chapter_list)
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            error_msg = f"Failed to fetch: {str(e)}"
            self.after(0, lambda msg=error_msg: self._show_error(msg))
        finally:
            self.after(0, lambda: self.fetch_btn.configure(state="normal"))
    
    def _update_chapter_list(self):
        """Update UI with fetched chapters."""
        if not self.novel_info:
            return
        
        # Update info labels
        self.title_label.configure(text=self.novel_info.title)
        self.author_label.configure(text=self.novel_info.author)
        self.chapters_label.configure(text=str(len(self.chapters)))
        
        # Load cover image in background
        if self.novel_info.cover_url:
            thread = threading.Thread(target=self._load_cover, args=(self.novel_info.cover_url,))
            thread.daemon = True
            thread.start()
        
        # Translate title in background
        thread = threading.Thread(target=self._translate_title, args=(self.novel_info.title,))
        thread.daemon = True
        thread.start()
        
        # Clear existing checkboxes
        for cb in self.chapter_checkboxes:
            cb.destroy()
        self.chapter_vars.clear()
        self.chapter_checkboxes.clear()
        
        # Add chapter checkboxes
        for idx, chapter in enumerate(self.chapters):
            var = ctk.BooleanVar(value=True)
            self.chapter_vars.append(var)
            
            cb = ctk.CTkCheckBox(
                self.chapter_frame,
                text=f"{idx + 1}. {chapter.title[:60]}{'...' if len(chapter.title) > 60 else ''}",
                variable=var,
                command=self._update_selected_count
            )
            cb.grid(row=idx, column=0, padx=5, pady=2, sticky="w")
            self.chapter_checkboxes.append(cb)
        
        self._update_selected_count()
        self.download_btn.configure(state="normal")
        self._update_status(f"Found {len(self.chapters)} chapters. Ready to download.")
    
    def _update_selected_count(self):
        """Update the selected count label."""
        count = sum(1 for var in self.chapter_vars if var.get())
        self.selected_label.configure(text=f"Selected: {count}")
    
    def _select_all(self):
        for var in self.chapter_vars:
            var.set(True)
        self._update_selected_count()
    
    def _select_none(self):
        for var in self.chapter_vars:
            var.set(False)
        self._update_selected_count()
    
    def _invert_selection(self):
        for var in self.chapter_vars:
            var.set(not var.get())
        self._update_selected_count()
    
    def _on_download(self):
        """Handle download button click."""
        if not self.chapters or not self.novel_info:
            return
        
        # Get selected chapters
        selected_chapters = [
            self.chapters[i] for i, var in enumerate(self.chapter_vars) if var.get()
        ]
        
        if not selected_chapters:
            messagebox.showwarning("Warning", "Please select at least one chapter")
            return
        
        # Use translated title if available, otherwise original
        title_for_filename = self.translated_title if self.translated_title else self.novel_info.title
        
        # Create shortened filename like WebToEpub: "First...Last.epub"
        clean_title = self._create_short_filename(title_for_filename)
        
        if not clean_title:
            clean_title = "novel"
        
        # Save to central Downloads directory
        downloads_dir = self._get_downloads_folder()
        output_path = str(downloads_dir / f"{clean_title}.epub")
        
        # If file exists, add number
        counter = 1
        base_path = output_path
        while os.path.exists(output_path):
            output_path = base_path.replace(".epub", f" ({counter}).epub")
            counter += 1
        
        print(f"Auto-saving to: {output_path}")
        
        # Start download
        self.is_downloading = True
        self.cancel_requested = False
        self.download_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        self.fetch_btn.configure(state="disabled")
        
        thread = threading.Thread(
            target=self._download_thread,
            args=(selected_chapters, output_path)
        )
        thread.daemon = True
        thread.start()
    
    def _get_downloads_folder(self) -> Path:
        """Get the user's Downloads folder."""
        # Try common locations
        if sys.platform == "win32":
            # Windows: use USERPROFILE/Downloads
            downloads = Path(os.environ.get("USERPROFILE", "")) / "Downloads"
        else:
            # macOS/Linux: use HOME/Downloads
            downloads = Path(os.environ.get("HOME", "")) / "Downloads"
        
        # Fallback to app directory if Downloads doesn't exist
        if not downloads.exists():
            downloads = self.app_dir
        
        return downloads
    
    def _create_short_filename(self, title: str, max_length: int = 40) -> str:
        """
        Create a shortened filename like WebToEpub does.
        Format: "FirstWord...LastWord" if title is too long.
        """
        # Clean the title - keep only safe characters
        clean = "".join(c for c in title if c.isalnum() or c in " ._-").strip()
        
        # Replace multiple spaces with single space
        clean = " ".join(clean.split())
        
        if not clean:
            return "novel"
        
        # If short enough, return as-is
        if len(clean) <= max_length:
            return clean
        
        # Split into words
        words = clean.split()
        
        if len(words) <= 2:
            # Just truncate if only 1-2 words
            return clean[:max_length]
        
        # Take first 2 words and last word, join with "..."
        first_part = " ".join(words[:2])
        last_part = words[-1]
        
        # Format: "First Two...Last"
        shortened = f"{first_part}...{last_part}"
        
        # If still too long, truncate first part
        if len(shortened) > max_length:
            available = max_length - len(last_part) - 3  # 3 for "..."
            first_part = first_part[:available].rstrip()
            shortened = f"{first_part}...{last_part}"
        
        return shortened
    
    def _download_thread(self, chapters: List[Chapter], output_path: str):
        """Download and build EPUB in background thread."""
        try:
            total = len(chapters)
            delay = self.parser.request_delay
            
            # Phase 1: Download chapter content
            self.after(0, lambda: self._update_status(f"Downloading chapters ({delay}s delay between requests)..."))
            
            for idx, chapter in enumerate(chapters):
                if self.cancel_requested:
                    self.after(0, lambda: self._update_status("Cancelled"))
                    return
                
                progress = (idx + 1) / (total * 2)  # First half is download
                self.after(0, lambda p=progress: self.progress_bar.set(p))
                self.after(0, lambda i=idx, t=chapter.title: self._update_status(
                    f"Downloading [{i+1}/{total}]: {t[:40]}..."
                ))
                
                # Fetch chapter content
                chapter.content = self.parser.get_chapter_content(chapter)
                
                # Delay to avoid rate limiting (shows in status)
                if idx < total - 1:  # Don't wait after last chapter
                    self.after(0, lambda i=idx, d=delay: self._update_status(
                        f"Downloaded [{i+1}/{total}] - waiting {d}s..."
                    ))
                    time.sleep(delay)
            
            # Phase 2: Build EPUB
            self.after(0, lambda: self._update_status("Building EPUB..."))
            
            # Create cleaner and translator
            cleaner = ContentCleaner() if self.clean_var.get() else None
            translator = None
            
            if self.translate_var.get():
                try:
                    workers = int(self.workers_entry.get())
                except ValueError:
                    workers = 200
                translator = GoogleTranslator(max_workers=workers)

            # Build EPUB
            if translator:
                builder = TranslatedEPUBBuilder(cleaner=cleaner, translator=translator)
                
                def progress_cb(current, total_steps, status):
                    if self.cancel_requested:
                        translator.cancel()
                        return
                    progress = 0.5 + (current / total_steps) * 0.5
                    self.after(0, lambda p=progress: self.progress_bar.set(p))
                    self.after(0, lambda s=status: self._update_status(s))
                
                builder.build_with_translation(
                    self.novel_info,
                    chapters,
                    output_path,
                    progress_cb
                )
            else:
                builder = EPUBBuilder(cleaner=cleaner)
                
                def progress_cb(current, total_steps, status):
                    progress = 0.5 + (current / total_steps) * 0.5
                    self.after(0, lambda p=progress: self.progress_bar.set(p))
                    self.after(0, lambda s=status: self._update_status(s))
                
                builder.build(
                    self.novel_info,
                    chapters,
                    output_path,
                    progress_cb
                )
            
            # Done
            self.after(0, lambda: self.progress_bar.set(1.0))
            self.after(0, lambda: self._update_status(f"Done! Saved to: {output_path}"))
            self.after(0, lambda: messagebox.showinfo("Success", f"EPUB saved to:\n{output_path}"))
            
        except Exception as e:
            error_msg = f"Download failed: {str(e)}"
            self.after(0, lambda msg=error_msg: self._show_error(msg))
        finally:
            self.is_downloading = False
            self.after(0, lambda: self.download_btn.configure(state="normal"))
            self.after(0, lambda: self.cancel_btn.configure(state="disabled"))
            self.after(0, lambda: self.fetch_btn.configure(state="normal"))
    
    def _on_cancel(self):
        """Handle cancel button click."""
        self.cancel_requested = True
        self._update_status("Cancelling...")
    
    # ------------------------------------------------------------------
    # Multi-download mode
    # ------------------------------------------------------------------
    
    def _on_mode_change(self, value: str):
        """Toggle between Single and Multi download modes."""
        if self.is_downloading:
            self.mode_switch.set("Multi" if value == "Single" else "Single")
            return
        
        self.multi_mode = (value == "Multi")
        
        if self.multi_mode:
            # Hide single-mode UI
            self.single_url_frame.grid_remove()
            self.info_frame.grid_remove()
            self.list_frame.grid_remove()
            self.download_btn.pack_forget()
            # Show multi-mode UI
            self.multi_frame.grid(row=1, column=0, rowspan=2, padx=10, pady=5, sticky="nsew")
        else:
            # Hide multi-mode UI
            self.multi_frame.grid_remove()
            # Show single-mode UI
            self.single_url_frame.grid()
            self.info_frame.grid()
            self.list_frame.grid()
            self.download_btn.pack(side="left", padx=5)
    
    def _multi_create_url_row(self, index: int):
        """Create a single URL entry row for multi mode."""
        label = ctk.CTkLabel(self.multi_url_container, text=f"{index + 1}.", width=25)
        label.grid(row=index, column=0, padx=(5, 2), pady=3, sticky="w")
        
        entry = ctk.CTkEntry(self.multi_url_container, placeholder_text=f"Novel URL #{index + 1}")
        entry.grid(row=index, column=1, padx=2, pady=3, sticky="ew")
        
        self.multi_url_entries.append(entry)
    
    def _multi_add_url(self):
        """Add a new URL field in multi mode (max 7)."""
        if len(self.multi_url_entries) >= 7:
            messagebox.showinfo("Limit", "Maximum 7 novels in multi-download mode.")
            return
        self._multi_create_url_row(len(self.multi_url_entries))
    
    def _multi_remove_url(self):
        """Remove the last URL field in multi mode (min 2)."""
        if len(self.multi_url_entries) <= 2:
            return
        entry = self.multi_url_entries.pop()
        # Destroy the entry and its label
        row = len(self.multi_url_entries)
        for widget in self.multi_url_container.grid_slaves(row=row):
            widget.destroy()
    
    def _on_multi_fetch(self):
        """Fetch info for all URLs in multi mode."""
        urls = [e.get().strip() for e in self.multi_url_entries if e.get().strip()]
        if not urls:
            messagebox.showerror("Error", "Please enter at least one URL.")
            return
        
        # Validate all URLs have parsers
        parsers = []
        for url in urls:
            parser = get_parser_for_url(url)
            if not parser:
                messagebox.showerror("Error", f"Unsupported site:\n{url}")
                return
            parsers.append((url, parser))
        
        # Clear old results
        self.multi_novels.clear()
        for widget in self.multi_results_frame.winfo_children():
            widget.destroy()
        self.multi_result_labels.clear()
        
        # Create result rows
        for idx, (url, parser) in enumerate(parsers):
            self.multi_novels.append({
                'url': url, 'parser': parser,
                'info': None, 'chapters': [],
                'status': 'pending', 'translated_title': None
            })
            self._multi_create_result_row(idx, url)
        
        # Disable UI during fetch
        self.multi_fetch_btn.configure(state="disabled", text="Fetching...")
        self.multi_download_btn.configure(state="disabled")
        self.multi_add_btn.configure(state="disabled")
        self.multi_remove_btn.configure(state="disabled")
        self.mode_switch.configure(state="disabled")
        self.progress_bar.set(0)
        self._update_status("Fetching novel info...")
        
        thread = threading.Thread(target=self._multi_fetch_thread)
        thread.daemon = True
        thread.start()
    
    def _multi_create_result_row(self, idx: int, url: str):
        """Create a result row in the multi results panel."""
        row_frame = ctk.CTkFrame(self.multi_results_frame)
        row_frame.pack(fill="x", padx=5, pady=3)
        row_frame.grid_columnconfigure(1, weight=1)
        
        num_label = ctk.CTkLabel(row_frame, text=f"{idx + 1}.", width=25, font=("", 12))
        num_label.grid(row=0, column=0, padx=(8, 4), pady=8, sticky="w")
        
        title_label = ctk.CTkLabel(
            row_frame, text=url[:60] + ("..." if len(url) > 60 else ""),
            font=("", 12), anchor="w"
        )
        title_label.grid(row=0, column=1, padx=4, pady=8, sticky="w")
        
        chapters_label = ctk.CTkLabel(row_frame, text="", width=80, font=("", 11), text_color="gray")
        chapters_label.grid(row=0, column=2, padx=4, pady=8)
        
        status_label = ctk.CTkLabel(row_frame, text="Pending", width=90, font=("", 11), text_color="gray")
        status_label.grid(row=0, column=3, padx=(4, 8), pady=8)
        
        self.multi_result_labels.append({
            'frame': row_frame, 'title': title_label,
            'chapters': chapters_label, 'status': status_label
        })
    
    def _multi_fetch_thread(self):
        """Fetch all novels sequentially in background."""
        total = len(self.multi_novels)
        
        for idx, novel in enumerate(self.multi_novels):
            self.after(0, lambda i=idx: self.multi_result_labels[i]['status'].configure(
                text="Fetching...", text_color="orange"
            ))
            self.after(0, lambda i=idx, t=total: self.progress_bar.set((i) / t))
            self.after(0, lambda i=idx, t=total: self._update_status(
                f"Fetching novel {i + 1}/{t}..."
            ))
            
            try:
                parser = novel['parser']
                url = novel['url']
                
                if hasattr(parser, 'fetch_all_parallel'):
                    info, chapters = parser.fetch_all_parallel(url)
                else:
                    info = parser.get_novel_info(url)
                    chapters = parser.get_chapter_list(url)
                
                novel['info'] = info
                novel['chapters'] = chapters
                novel['status'] = 'fetched'
                
                # Translate title
                try:
                    translator = GoogleTranslator(max_workers=1)
                    translated = translator.translate_text(info.title)
                    novel['translated_title'] = translated if translated and translated != info.title else info.title
                except Exception:
                    novel['translated_title'] = info.title
                
                display_title = novel['translated_title']
                if len(display_title) > 45:
                    display_title = display_title[:42] + "..."
                
                self.after(0, lambda i=idx, t=display_title: self.multi_result_labels[i]['title'].configure(text=t))
                self.after(0, lambda i=idx, c=len(chapters): self.multi_result_labels[i]['chapters'].configure(
                    text=f"{c} ch."
                ))
                self.after(0, lambda i=idx: self.multi_result_labels[i]['status'].configure(
                    text="Ready", text_color="#2B7A3E"
                ))
                
            except Exception as e:
                novel['status'] = 'error'
                err = str(e)[:30]
                self.after(0, lambda i=idx, msg=err: self.multi_result_labels[i]['status'].configure(
                    text=f"Error", text_color="red"
                ))
                self.after(0, lambda i=idx, msg=str(e): self.multi_result_labels[i]['title'].configure(
                    text=f"Error: {msg[:50]}"
                ))
        
        # Re-enable UI
        self.after(0, lambda: self.multi_fetch_btn.configure(state="normal", text="Fetch All"))
        self.after(0, lambda: self.multi_add_btn.configure(state="normal"))
        self.after(0, lambda: self.multi_remove_btn.configure(state="normal"))
        self.after(0, lambda: self.mode_switch.configure(state="normal"))
        self.after(0, lambda: self.progress_bar.set(1.0))
        
        # Enable download if at least one novel was fetched successfully
        fetched = [n for n in self.multi_novels if n['status'] == 'fetched']
        if fetched:
            self.after(0, lambda: self.multi_download_btn.configure(state="normal"))
            self.after(0, lambda c=len(fetched), t=total: self._update_status(
                f"Fetched {c}/{t} novels. Ready to download."
            ))
        else:
            self.after(0, lambda: self._update_status("No novels fetched successfully."))
    
    def _on_multi_download(self):
        """Start downloading all fetched novels sequentially."""
        fetched = [n for n in self.multi_novels if n['status'] == 'fetched']
        if not fetched:
            return
        
        self.is_downloading = True
        self.cancel_requested = False
        self.multi_download_btn.configure(state="disabled")
        self.multi_fetch_btn.configure(state="disabled")
        self.multi_add_btn.configure(state="disabled")
        self.multi_remove_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        self.fetch_btn.configure(state="disabled")
        self.mode_switch.configure(state="disabled")
        
        thread = threading.Thread(target=self._multi_download_thread, args=(fetched,))
        thread.daemon = True
        thread.start()
    
    def _multi_download_thread(self, novels: list):
        """Download all novels sequentially in background."""
        total_novels = len(novels)
        results = []  # (title, path, success, error)
        downloads_dir = self._get_downloads_folder()
        
        for novel_idx, novel in enumerate(novels):
            if self.cancel_requested:
                results.append((novel['translated_title'] or "Unknown", "", False, "Cancelled"))
                continue
            
            info = novel['info']
            chapters = novel['chapters']
            parser = novel['parser']
            title_for_filename = novel['translated_title'] if novel['translated_title'] else info.title
            
            # Find the index in the full multi_novels list for UI updates
            full_idx = self.multi_novels.index(novel)
            
            self.after(0, lambda i=full_idx: self.multi_result_labels[i]['status'].configure(
                text="Downloading", text_color="orange"
            ))
            self.after(0, lambda ni=novel_idx, tn=total_novels: self._update_status(
                f"Novel {ni + 1}/{tn}: Downloading chapters..."
            ))
            
            try:
                # Generate output path
                clean_title = self._create_short_filename(title_for_filename)
                if not clean_title:
                    clean_title = "novel"
                output_path = str(downloads_dir / f"{clean_title}.epub")
                counter = 1
                base_path = output_path
                while os.path.exists(output_path):
                    output_path = base_path.replace(".epub", f" ({counter}).epub")
                    counter += 1
                
                # Phase 1: Download chapters
                total_ch = len(chapters)
                delay = parser.request_delay
                
                for ch_idx, chapter in enumerate(chapters):
                    if self.cancel_requested:
                        raise Exception("Cancelled by user")
                    
                    overall = (novel_idx + (ch_idx + 1) / (total_ch * 2)) / total_novels
                    self.after(0, lambda p=overall: self.progress_bar.set(p))
                    self.after(0, lambda ni=novel_idx, tn=total_novels, ci=ch_idx, tc=total_ch: self._update_status(
                        f"Novel {ni + 1}/{tn} — Chapter [{ci + 1}/{tc}]"
                    ))
                    
                    chapter.content = parser.get_chapter_content(chapter)
                    
                    if ch_idx < total_ch - 1:
                        time.sleep(delay)
                
                # Phase 2: Build EPUB
                self.after(0, lambda ni=novel_idx, tn=total_novels: self._update_status(
                    f"Novel {ni + 1}/{tn}: Building EPUB..."
                ))
                
                cleaner = ContentCleaner() if self.clean_var.get() else None
                translator = None
                
                if self.translate_var.get():
                    try:
                        workers = int(self.workers_entry.get())
                    except ValueError:
                        workers = 200
                    translator = GoogleTranslator(max_workers=workers)

                if translator:
                    builder = TranslatedEPUBBuilder(cleaner=cleaner, translator=translator)
                    
                    def progress_cb(current, total_steps, status, _ni=novel_idx, _tn=total_novels):
                        if self.cancel_requested:
                            translator.cancel()
                            return
                        overall = (_ni + 0.5 + (current / total_steps) * 0.5) / _tn
                        self.after(0, lambda p=overall: self.progress_bar.set(p))
                        self.after(0, lambda s=status, ni=_ni, tn=_tn: self._update_status(
                            f"Novel {ni + 1}/{tn}: {s}"
                        ))
                    
                    builder.build_with_translation(info, chapters, output_path, progress_cb)
                else:
                    builder = EPUBBuilder(cleaner=cleaner)
                    
                    def progress_cb(current, total_steps, status, _ni=novel_idx, _tn=total_novels):
                        overall = (_ni + 0.5 + (current / total_steps) * 0.5) / _tn
                        self.after(0, lambda p=overall: self.progress_bar.set(p))
                        self.after(0, lambda s=status, ni=_ni, tn=_tn: self._update_status(
                            f"Novel {ni + 1}/{tn}: {s}"
                        ))
                    
                    builder.build(info, chapters, output_path, progress_cb)
                
                results.append((title_for_filename, output_path, True, None))
                self.after(0, lambda i=full_idx: self.multi_result_labels[i]['status'].configure(
                    text="Done", text_color="#2B7A3E"
                ))
                
            except Exception as e:
                results.append((title_for_filename, "", False, str(e)))
                self.after(0, lambda i=full_idx: self.multi_result_labels[i]['status'].configure(
                    text="Failed", text_color="red"
                ))
        
        # All done - show summary
        self.after(0, lambda: self.progress_bar.set(1.0))
        
        success = [r for r in results if r[2]]
        failed = [r for r in results if not r[2]]
        
        summary = f"Completed: {len(success)}/{len(results)} novels\n\n"
        if success:
            summary += "Saved to:\n"
            for title, path, _, _ in success:
                summary += f"  • {Path(path).name}\n"
        if failed:
            summary += "\nFailed:\n"
            for title, _, _, err in failed:
                short_title = title[:30] + "..." if len(title) > 30 else title
                summary += f"  • {short_title}: {err[:40]}\n"
        
        summary += f"\nLocation: {downloads_dir}"
        
        self.after(0, lambda s=summary: self._update_status(
            f"Done! {len(success)}/{len(results)} novels downloaded."
        ))
        self.after(0, lambda s=summary: messagebox.showinfo("Multi-Download Complete", s))
        
        # Re-enable UI
        self.is_downloading = False
        self.after(0, lambda: self.multi_download_btn.configure(state="normal"))
        self.after(0, lambda: self.multi_fetch_btn.configure(state="normal"))
        self.after(0, lambda: self.multi_add_btn.configure(state="normal"))
        self.after(0, lambda: self.multi_remove_btn.configure(state="normal"))
        self.after(0, lambda: self.cancel_btn.configure(state="disabled"))
        self.after(0, lambda: self.fetch_btn.configure(state="normal"))
        self.after(0, lambda: self.mode_switch.configure(state="normal"))
    
    def _load_cover(self, url: str):
        """Load cover image from URL in background."""
        try:
            print(f"Loading cover from: {url}")
            response = http_session.get(url, timeout=15)
            response.raise_for_status()
            
            # Load image with PIL
            image = Image.open(BytesIO(response.content))
            
            # Resize to fit (100x140 max, keep aspect ratio)
            image.thumbnail((100, 140), Image.Resampling.LANCZOS)
            
            # Convert to CTkImage
            ctk_image = ctk.CTkImage(light_image=image, dark_image=image, size=image.size)
            
            # Update UI in main thread
            self.after(0, lambda: self._set_cover_image(ctk_image))
            print("Cover loaded successfully")
            
        except Exception as e:
            print(f"Failed to load cover: {e}")
    
    def _set_cover_image(self, image):
        """Set the cover image in the UI."""
        self.cover_image = image  # Keep reference
        self.cover_label.configure(image=image, text="")
    
    def _translate_title(self, title: str):
        """Translate the title to English in background."""
        try:
            print(f"Translating title: {title}")
            translator = GoogleTranslator(max_workers=1)
            translated = translator.translate_text(title)
            
            if translated and translated != title:
                self.translated_title = translated
                self.after(0, lambda t=translated: self.eng_title_label.configure(text=t, text_color="white"))
                print(f"Translated title: {translated}")
            else:
                self.translated_title = title
                self.after(0, lambda: self.eng_title_label.configure(text="(same as original)", text_color="gray"))
                
        except Exception as e:
            print(f"Failed to translate title: {e}")
            self.translated_title = title
            self.after(0, lambda: self.eng_title_label.configure(text="(translation failed)", text_color="gray"))
    
    def _update_status(self, text: str):
        """Update status label."""
        self.status_label.configure(text=text)
    
    def _show_error(self, message: str):
        """Show error message."""
        self.status_label.configure(text="Error")
        messagebox.showerror("Error", message)
    
    def _on_auto_update_toggle(self):
        """Handle auto-update checkbox toggle."""
        set_auto_check_updates(self.auto_update_var.get())
    
    def _auto_check_updates(self):
        """Auto-check for updates on startup (silent unless update available)."""
        def callback(has_update, latest_version, message):
            if has_update:
                self.after(0, lambda: self._show_update_available(latest_version, message))
        
        check_for_updates_async(callback)
    
    def _on_check_updates(self):
        """Handle manual check for updates button click."""
        self.update_btn.configure(state="disabled", text="Checking...")
        
        def callback(has_update, latest_version, message):
            self.after(0, lambda: self.update_btn.configure(state="normal", text="Check for Updates"))
            if has_update:
                self.after(0, lambda: self._show_update_available(latest_version, message))
            else:
                self.after(0, lambda: messagebox.showinfo("Up to Date", message))
        
        check_for_updates_async(callback)
    
    def _show_update_available(self, latest_version: str, message: str):
        """Show update available dialog and offer to download."""
        result = messagebox.askyesno(
            "Update Available",
            f"{message}\n\nWould you like to download and install the update?",
            icon="info"
        )
        
        if result:
            self._download_update()
    
    def _download_update(self):
        """Download and install the update."""
        # Import here to check if frozen
        from core.updater import is_frozen
        
        # Create progress dialog
        progress_window = ctk.CTkToplevel(self)
        progress_window.title("Updating...")
        progress_window.geometry("400x150")
        progress_window.transient(self)
        progress_window.grab_set()
        
        # Center the window
        progress_window.update_idletasks()
        x = self.winfo_x() + (self.winfo_width() - 400) // 2
        y = self.winfo_y() + (self.winfo_height() - 150) // 2
        progress_window.geometry(f"+{x}+{y}")
        
        # Progress UI
        ctk.CTkLabel(progress_window, text="Downloading update...", font=("", 14)).pack(pady=(20, 10))
        
        progress_bar = ctk.CTkProgressBar(progress_window, width=350)
        progress_bar.pack(pady=10)
        progress_bar.set(0)
        
        status_label = ctk.CTkLabel(progress_window, text="Connecting...", font=("", 11))
        status_label.pack(pady=5)
        
        def progress_callback(current, total, status):
            self.after(0, lambda: progress_bar.set(current / total))
            self.after(0, lambda s=status: status_label.configure(text=s))
        
        def completion_callback(success, message):
            self.after(0, progress_window.destroy)
            if success:
                self.after(0, lambda: self._handle_update_complete(message))
            else:
                self.after(0, lambda: messagebox.showerror("Update Failed", message))
        
        download_update_async(progress_callback, completion_callback)
    
    def _handle_update_complete(self, message: str):
        """Handle successful update completion."""
        from core.updater import is_frozen
        
        messagebox.showinfo("Update Complete", message)
        
        # If running as compiled executable, close the app so the helper script can replace it
        if is_frozen():
            self.after(500, self._on_close)


def main():
    app = NovelDownloaderApp()
    app.mainloop()


if __name__ == "__main__":
    main()
