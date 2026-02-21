#!/usr/bin/env python3
"""
Novel Downloader & Translator
A standalone GUI application for downloading and translating web novels to EPUB.

Based on WebToEpub extension and fixTranslate.py
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
        
        # === URL Input Section ===
        url_frame = ctk.CTkFrame(self)
        url_frame.grid(row=0, column=0, padx=10, pady=(10, 5), sticky="ew")
        url_frame.grid_columnconfigure(1, weight=1)
        
        ctk.CTkLabel(url_frame, text="URL:", font=("", 14)).grid(
            row=0, column=0, padx=(10, 5), pady=10
        )
        
        self.url_entry = ctk.CTkEntry(url_frame, placeholder_text="Enter novel URL (e.g., https://twkan.com/book/12345.html)")
        self.url_entry.grid(row=0, column=1, padx=5, pady=10, sticky="ew")
        
        self.fetch_btn = ctk.CTkButton(url_frame, text="Fetch Chapters", command=self._on_fetch)
        self.fetch_btn.grid(row=0, column=2, padx=(5, 10), pady=10)
        
        # === Novel Info Section (with cover preview) ===
        info_frame = ctk.CTkFrame(self)
        info_frame.grid(row=1, column=0, padx=10, pady=5, sticky="ew")
        info_frame.grid_columnconfigure(1, weight=1)
        
        # Cover image on the left
        self.cover_frame = ctk.CTkFrame(info_frame, width=100, height=140)
        self.cover_frame.grid(row=0, column=0, rowspan=3, padx=10, pady=10, sticky="ns")
        self.cover_frame.grid_propagate(False)
        
        self.cover_label = ctk.CTkLabel(self.cover_frame, text="No Cover", width=100, height=140)
        self.cover_label.pack(expand=True, fill="both")
        
        # Info on the right
        info_right = ctk.CTkFrame(info_frame, fg_color="transparent")
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
        list_frame = ctk.CTkFrame(self)
        list_frame.grid(row=2, column=0, padx=10, pady=5, sticky="nsew")
        list_frame.grid_columnconfigure(0, weight=1)
        list_frame.grid_rowconfigure(1, weight=1)
        
        # Selection buttons
        btn_frame = ctk.CTkFrame(list_frame, fg_color="transparent")
        btn_frame.grid(row=0, column=0, padx=5, pady=5, sticky="ew")
        
        ctk.CTkButton(btn_frame, text="Select All", width=100, command=self._select_all).pack(side="left", padx=5)
        ctk.CTkButton(btn_frame, text="Select None", width=100, command=self._select_none).pack(side="left", padx=5)
        ctk.CTkButton(btn_frame, text="Invert", width=100, command=self._invert_selection).pack(side="left", padx=5)
        
        self.selected_label = ctk.CTkLabel(btn_frame, text="Selected: 0")
        self.selected_label.pack(side="right", padx=10)
        
        # Chapter listbox with checkboxes
        self.chapter_frame = ctk.CTkScrollableFrame(list_frame)
        self.chapter_frame.grid(row=1, column=0, padx=5, pady=5, sticky="nsew")
        self.chapter_frame.grid_columnconfigure(0, weight=1)
        
        self.chapter_vars: List[ctk.BooleanVar] = []
        self.chapter_checkboxes: List[ctk.CTkCheckBox] = []
        
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
        
        # Auto-generate filename using translated title (or original if not available)
        title_for_filename = self.translated_title if self.translated_title else self.novel_info.title
        
        # Clean filename - remove invalid characters
        clean_title = "".join(c for c in title_for_filename if c.isalnum() or c in " ._-").strip()
        clean_title = clean_title[:80]  # Limit length
        
        if not clean_title:
            clean_title = "novel"
        
        # Auto-save in app directory
        output_path = str(self.app_dir / f"{clean_title}.epub")
        
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
    
    def _download_thread(self, chapters: List[Chapter], output_path: str):
        """Download and build EPUB in background thread."""
        try:
            total = len(chapters)
            
            # Phase 1: Download chapter content
            self.after(0, lambda: self._update_status("Downloading chapters..."))
            
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
                
                # Small delay to avoid rate limiting
                time.sleep(self.parser.request_delay)
            
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
