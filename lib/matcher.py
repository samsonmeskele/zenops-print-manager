import re
from config import SUBJECT_KEYWORDS, GRADES

# Ways people write "grade", longest first so "grade" wins over "gr" or "g".
_GRADE_WORDS = r'(?:grade|grad|gra|grd|gr|g)'

# Prefix:  g9, gr9, gra9, grad9, grade9, grade 9, gr.9, G-09
_PREFIX = re.compile(rf'(?<![a-z]){_GRADE_WORDS}\s*0?(\d{{1,2}})(?!\d)')
# Suffix:  9g, 9gr, 9 grade
_SUFFIX = re.compile(rf'(?<!\d)0?(\d{{1,2}})\s*{_GRADE_WORDS}(?![a-z])')
# Ordinal: 9th, 10th, 7TH
_ORDINAL = re.compile(r'(?<!\d)0?(\d{1,2})(?:st|nd|rd|th)(?![a-z])')

# Separators that should count as spaces (underscore is a "word" character in
# regex, which is why names like "math_g9" used to fail).
_SEPARATORS = re.compile(r'[_\-.,()\[\]{}+]+')


def _normalize(filename):
    """Lowercase, drop the extension, turn separators into single spaces."""
    name = filename.lower()
    if name.endswith('.pdf') or re.search(r'\.[a-z0-9]{2,4}$', name):
        name = name.rsplit('.', 1)[0]
    name = _SEPARATORS.sub(' ', name)
    return re.sub(r'\s+', ' ', name).strip()


def _find_grade(name):
    # Most specific pattern first; within a pattern, take the first number
    # that is an allowed grade.
    for pattern in (_PREFIX, _SUFFIX, _ORDINAL):
        for m in pattern.finditer(name):
            value = int(m.group(1))
            if value in GRADES:
                return value
    return None


def _find_subject(name):
    # Longer keywords first, so "social studies" beats "social".
    for key in sorted(SUBJECT_KEYWORDS, key=len, reverse=True):
        # Letters on either side block the match ("it" won't match inside
        # "history"), but digits and separators are fine ("g9math", "math9").
        if re.search(r'(?<![a-z])' + key + r'(?![a-z])', name):
            return SUBJECT_KEYWORDS[key]
    return None


def parse_filename(filename):
    """
    Analyzes a filename and returns (grade, subject).
    Either value is None if it cannot be determined.

    Understands, in any letter case:
      g9, gr9, gra9, grd9, grad9, grade9, grade 9, grade_9, Grade-09
      9g, 9gr, 9 grade, 9th
    """
    name = _normalize(filename)
    return _find_grade(name), _find_subject(name)