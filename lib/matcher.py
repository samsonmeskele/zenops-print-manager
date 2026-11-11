import re
from config import SUBJECT_KEYWORDS, GRADES

def parse_filename(filename):
    """
    Analyzes a filename and returns (grade, subject).
    If it cannot determine either, returns None.
    """
    # Remove extension and convert to lowercase
    name = filename.lower().rsplit('.', 1)[0]
    
    # 1. Find Grade 
    grade = None
    
    # Pattern A: Prefix (G9, Gr9, Grd9, Grad9, Grade9, Grade 9)
    match_prefix = re.search(r'\b(?:grade|grad|grd|gr|g)\s*([6-9]|1[0-2])\b', name)
    # Pattern B: Suffix (9grade, 9 grad)
    match_suffix = re.search(r'\b([6-9]|1[0-2])\s*(?:grade|grad|grd)\b', name)
    # Pattern C: Ordinal (9th, 10th)
    match_ordinal = re.search(r'\b([6-9]|1[0-2])(?:st|nd|rd|th)\b', name)
    
    if match_prefix:
        grade = int(match_prefix.group(1))
    elif match_suffix:
        grade = int(match_suffix.group(1))
    elif match_ordinal:
        grade = int(match_ordinal.group(1))
        
    # Validate grade is between 6 and 12
    if grade not in GRADES:
        grade = None

    # 2. Find Subject
    subject = None
    for key, subj_name in SUBJECT_KEYWORDS.items():
        # \b ensures we match whole words only (e.g. "it" won't match inside "history")
        if re.search(r'\b' + key + r'\b', name):
            subject = subj_name
            break

    return grade, subject