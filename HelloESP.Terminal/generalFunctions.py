import re


def safe_decode(buffer_data, encoding='utf8', strip_ansi=True):
    """
    Decodifica in modo sicuro un buffer rimuovendo caratteri problematici e codici ANSI.

    Args:
        buffer_data (bytes): Il buffer da decodificare
        encoding (str): L'encoding da utilizzare (default: 'utf8')
        strip_ansi (bool): Se rimuovere i codici ANSI (default: True)

    Returns:
        str: La stringa decodificata e pulita
    """
    try:
        # Prima decodifica il buffer in stringa
        text = buffer_data.decode(encoding, errors='ignore')

        if strip_ansi:
            # Rimuove i codici ANSI escape
            # Questo pattern cattura le sequenze che iniziano con ESC[ e finiscono con m
            ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
            text = ansi_escape.sub('', text)

        # Opzionalmente, puoi anche ripulire altri caratteri di controllo mantenendo
        # solo newline e tab
        text = ''.join(char for char in text if char >= ' ' or char in '\n\t\r')

        return text
    except Exception as e:
        # Fallback estremo: rimuovi tutti i bytes problematici
        safe_bytes = bytearray()
        for byte in buffer_data:
            if (32 <= byte <= 126) or byte in {9, 10, 13}:
                safe_bytes.append(byte)
        return safe_bytes.decode(encoding, errors='ignore')


def contains_alphanumeric(text):
    """
    Controlla se una stringa contiene almeno un carattere alfanumerico.

    Args:
        text (str): La stringa da controllare

    Returns:
        bool: True se la stringa contiene almeno un carattere alfanumerico,
              False se contiene solo caratteri speciali
    """
    # Controllo se la stringa è vuota
    if not text:
        return False

    # Utilizzo any() con isalnum() per verificare se c'è almeno
    # un carattere alfanumerico
    return any(char.isalnum() for char in text)