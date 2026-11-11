import os
import sys

# 1. Determine the base folder dynamically
if getattr(sys, 'frozen', False):
    # If running as a compiled .exe
    BASE_SCRIPT_DIR = os.path.dirname(sys.executable)
else:
    # If running as a normal Python script
    BASE_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# 2. Make Documents folder dynamic (Works for any Windows user)
DOCUMENTS_DIR = ""

# App Directories
BASE_DB_DIR = os.path.join(BASE_SCRIPT_DIR, 'database')
CACHE_FOLDER = os.path.join(BASE_SCRIPT_DIR, '.pdf_cache')
BIN_FOLDER = os.path.join(BASE_SCRIPT_DIR, 'bin')
BACKUP_FOLDER = os.path.join(BASE_SCRIPT_DIR, 'backups')

SUMATRA_EXE = 'SumatraPDF-3.6.1-64.exe'
DEFAULT_PRICE_PER_SHEET = ""
PRINTER_KEYWORDS = ""

# Filename Parsing Keywords
SUBJECT_KEYWORDS = {
    "math": "Mathematics", "maths": "Mathematics", "mathematics": "Mathematics",
    "eng": "English", "english": "English",
    "phy": "Physics", "physics": "Physics",
    "chem": "Chemistry", "chemistry": "Chemistry",
    "bio": "Biology", "biology": "Biology",
    "sci": "Science", "science": "Science",
    "hist": "History", "history": "History",
    "geo": "Geography", "geography": "Geography",
    "civ": "Civics", "civics": "Civics", "citizenship": "Citizenship",
    "social": "Social Studies", "sst": "Social Studies",
    "amh": "Amharic", "amharic": "Amharic",
    "it": "IT", "ict": "IT", "computer": "IT"
}

GRADES = ""