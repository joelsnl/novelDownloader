# Novel Downloader & Translator

A standalone Windows application for downloading Chinese web novels and translating them to English EPUBs.

Based on WebToEpub extension (by dteviot) and fixTranslate.py (from another project of mine).

<img width="898" height="729" alt="image" src="https://github.com/user-attachments/assets/1a40bb3c-a92b-4c7b-a210-7fd50562a887" />

## Features

- **Download novels** from supported sites (currently: twkan.com)
- **Remove watermarks** and ads automatically
- **Translate to English** using Google Translate (free, concurrent)
- **Create EPUB** files ready for e-readers
- **Select specific chapters** to download
- **Progress tracking** with cancel support

## Installation

### Option 1: Run from Source (Recommended for development)

1. Install Python 3.10 or newer
2. Clone/download this folder
3. Install dependencies:
   ```bash
   cd novel_downloader
   pip install -r requirements.txt
   ```
4. Run the app:
   ```bash
   python app.py
   ```

### Option 2: Build Standalone Executable

1. Install dependencies + PyInstaller:
   ```bash
   pip install -r requirements.txt
   pip install pyinstaller
   ```
2. Build:
   ```bash
   python build.py
   ```
3. Find the executable in `dist/NovelDownloader.exe`

## Usage

1. **Enter URL**: Paste the URL of the novel's main page
   - Example: `https://twkan.com/book/76222.html`

2. **Fetch Chapters**: Click "Fetch Chapters" to load the chapter list

3. **Select Chapters**: Check/uncheck chapters you want to download
   - Use "Select All", "Select None", or "Invert" for bulk selection

4. **Options**:
   - ✅ Remove watermarks & ads - Cleans the content
   - ✅ Translate to English - Translates Chinese text
   - Translation Workers - Number of concurrent translation requests (default: 50)

5. **Download**: Click "Download EPUB" and choose save location

## Supported Sites

| Site | URL Pattern | Status |
|------|-------------|--------|
| twkan.com | `https://twkan.com/book/{id}.html` | ✅ Working |

## Adding New Sites

To add support for a new site, create a new parser in `parsers/`:

```python
# parsers/newsite.py
from core.parser import BaseParser, Chapter, NovelInfo, register_parser

@register_parser
class NewSiteParser(BaseParser):
    SITE_NAME = "newsite.com"
    SITE_DOMAINS = ["newsite.com", "www.newsite.com"]
    
    def get_novel_info(self, url: str) -> NovelInfo:
        # Extract title, author, cover, etc.
        pass
    
    def get_chapter_list(self, url: str) -> List[Chapter]:
        # Return list of chapters
        pass
    
    def get_chapter_content(self, chapter: Chapter) -> str:
        # Fetch and return chapter HTML content
        pass
```

Then import it in `parsers/__init__.py`:
```python
from parsers.newsite import NewSiteParser
```

## Project Structure

```
novel_downloader/
├── app.py              # Main GUI application
├── requirements.txt    # Python dependencies
├── build.py           # PyInstaller build script
├── core/
│   ├── __init__.py
│   ├── parser.py      # Base parser class
│   ├── cleaner.py     # Watermark/ad removal
│   ├── translator.py  # Google Translate integration
│   └── epub_builder.py # EPUB creation
└── parsers/
    ├── __init__.py
    └── twkan.py       # twkan.com parser
```

## Troubleshooting

### "Translation failed" errors
- Reduce workers (try 20-30 instead of 50)
- Google may rate-limit; the app will retry with backoff

### "Could not extract book ID"
- Make sure you're using the main novel page URL
- Check that the site is supported

### EPUB won't open
- Try a different reader (Calibre recommended)
- Check if the novel has special characters in the title

## Credits

- Based on [WebToEpub](https://github.com/nicholasa/WebToEpub) browser extension
- Translation logic from fixTranslate.py
- Uses [ebooklib](https://github.com/aerkalov/ebooklib) for EPUB creation
- GUI built with [CustomTkinter](https://github.com/TomSchimansky/CustomTkinter)

## License

MIT License - Feel free to modify and distribute.
