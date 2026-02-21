"""
Site parsers for Novel Downloader
Import this module to register all parsers
"""

# Import all parsers to register them
from parsers.twkan import TwkanParser
from parsers.shuba69 import Shuba69Parser
from parsers.uukanshu import UUKanshuParser

__all__ = ['TwkanParser', 'Shuba69Parser', 'UUKanshuParser']
