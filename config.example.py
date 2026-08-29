"""
ZenOps Print Manager - Configuration Template

Copy this file to `config.py` and fill in your real paths and client list.
`config.py` is listed in .gitignore, so your local file paths and business
data are never committed to version control.
"""

# --- Directories ---
# Where scripts, the SumatraPDF binary, and generated databases/catalogs live.
BASE_SCRIPT_DIR = r'C:\Path\To\Scripts'

# Root folder containing one subfolder per client, each holding PDF handouts
# organized into grade-numbered subfolders (e.g. "Grade 5/Math.pdf").
BASE_HANDOUTS_DIR = r'C:\Path\To\Handouts'

# --- Printer ---
SUMATRA_EXE = 'SumatraPDF-3.5.2-64.exe'

# Only printers whose name contains one of these keywords (case-insensitive)
# will show up in the printer selection dropdown.
PRINTER_KEYWORDS = ['canon']

# --- Pricing ---
# Base rate charged per physical sheet of paper.
PRICE_PER_SHEET = 5.0

# --- Clients ---
# Each client maps to a print "mode":
#   "duplex"  -> front-and-back printing. 2 PDF pages = 1 physical sheet.
#                Pages are split into odd/even batches for manual flip-and-reprint.
#   "simplex" -> single-sided printing, printed as-is with no odd/even split.
#                1 PDF page = 1 physical sheet.
CLIENTS = {
    "ClientA": {"mode": "duplex"},
    "ClientB": {"mode": "duplex"},
    "ClientC": {"mode": "duplex"},
    "ClientD": {"mode": "simplex"},
    "ClientE": {"mode": "duplex"},
}
