"""
Site parsers for Novel Downloader
Import this module to register all parsers
"""

# Import all parsers to register them
from parsers.twkan import TwkanParser

__all__ = ['TwkanParser']
