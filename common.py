"""
Shared helpers used across the importer, GUI, and CLI tools.
"""

import os
import re

from config import BASE_SCRIPT_DIR

BASE_DB_DIR = os.path.join(BASE_SCRIPT_DIR, 'database')
BASE_CATALOG_DIR = os.path.join(BASE_SCRIPT_DIR, 'catalog')
CACHE_FOLDER = os.path.join(BASE_SCRIPT_DIR, '.pdf_cache')

BIN_FOLDER = os.path.join(BASE_SCRIPT_DIR, 'bin')


def ensure_dirs():
    """Create the working folders (database, catalog, cache) if they don't exist."""
    for folder in [BASE_DB_DIR, BASE_CATALOG_DIR, CACHE_FOLDER]:
        os.makedirs(folder, exist_ok=True)


def get_db_path(client_name):
    """Return the SQLite database path for a given client."""
    return os.path.join(BASE_DB_DIR, f"{client_name.lower()}_database.db")


def get_grade_number(folder_name):
    """Extract a leading grade number from a folder name, e.g. 'Grade 5' -> 5."""
    match = re.search(r'(\d+)', folder_name)
    if match:
        return int(match.group(1))
    return 0


def clear_cache():
    """Wipe and recreate the temporary PDF cache folder."""
    import shutil
    if os.path.exists(CACHE_FOLDER):
        try:
            shutil.rmtree(CACHE_FOLDER)
            os.makedirs(CACHE_FOLDER)
            print("Print cache cleared successfully.")
        except Exception as e:
            print(f"Could not clear cache: {e}")
    else:
        os.makedirs(CACHE_FOLDER)
