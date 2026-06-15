"""
Language detection for bilingual support (English/Marathi).
"""

# Marathi Unicode character set (Devanagari script used for Marathi)
MARATHI_CHARS = set(
    'अआइईउऊऋएऐओऔकखगघङचछजझञटठडढणतथदधनपफबभमयरलवशषसह'
    'ऽािीुूृेैोौंःॅॉ'
)


def detect_language(text: str) -> str:
    """
    Detect if text is primarily Marathi or English.
    
    Args:
        text: Input text to analyze
        
    Returns:
        'marathi' if Marathi characters detected, otherwise 'english'
    """
    if not text:
        return 'english'
    
    # Check for Marathi characters
    for char in text:
        if char in MARATHI_CHARS:
            return 'marathi'
    
    return 'english'
