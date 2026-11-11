import os
import subprocess
import math
from pypdf import PdfReader, PdfWriter
from config import BIN_FOLDER, SUMATRA_EXE, CACHE_FOLDER

SUMATRA_PATH = os.path.join(BIN_FOLDER, SUMATRA_EXE)

def split_pdf_for_duplex(pdf_path, printer_name):
    """
    Splits the PDF into ODD and EVEN parts.
    Automatically detects Canon (reverse even) vs Epson/Other (normal even).
    """
    reader = PdfReader(pdf_path)
    n = len(reader.pages)
    
    odd_writer = PdfWriter()
    even_writer = PdfWriter()
    
    # 1. Odd pages are always normal (1st, 3rd, 5th...)
    for i in range(0, n, 2):
        odd_writer.add_page(reader.pages[i])
        
    # 2. Check Printer for Even Page Logic
    is_canon = 'canon' in printer_name.lower()
    
    if is_canon:
        # Canon: Even pages in REVERSE order
        for i in reversed(range(1, n, 2)):
            even_writer.add_page(reader.pages[i])
    else:
        # Epson / Default: Even pages in NORMAL order (2nd, 4th, 6th...)
        for i in range(1, n, 2):
            even_writer.add_page(reader.pages[i])

    # Save files
    base_name = os.path.basename(pdf_path).replace('.pdf', '')
    odd_path = os.path.join(CACHE_FOLDER, f"{base_name}_ODD.pdf")
    even_path = os.path.join(CACHE_FOLDER, f"{base_name}_EVEN.pdf")
    
    with open(odd_path, 'wb') as f:
        odd_writer.write(f)
        
    has_even = len(even_writer.pages) > 0
    if has_even:
        with open(even_path, 'wb') as f:
            even_writer.write(f)

    return odd_path, even_path, has_even

def send_to_printer(file_path, printer_name):
    """Sends a single PDF to Sumatra silently."""
    try:
        subprocess.run([SUMATRA_PATH, '-print-to', printer_name, '-silent', file_path], check=True)
        return True, "Success"
    except Exception as e:
        return False, str(e)