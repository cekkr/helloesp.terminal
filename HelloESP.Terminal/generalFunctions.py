def safe_decode(buffer_data, encoding='ascii'):
    """
    Decodifica in modo sicuro un buffer rimuovendo i caratteri non ASCII pericolosi.

    Args:
        buffer_data (bytes): Il buffer da decodificare
        encoding (str): L'encoding da utilizzare (default: 'ascii')

    Returns:
        str: La stringa decodificata e pulita
    """
    try:
        # Prova prima la decodifica normale
        return buffer_data.decode(encoding)
    except UnicodeDecodeError:
        # Se fallisce, converti in bytearray per manipolazione
        byte_array = bytearray(buffer_data)

        # Mantieni solo i caratteri ASCII stampabili (32-126) e alcuni caratteri comuni
        safe_bytes = bytearray()
        for byte in byte_array:
            # Caratteri ASCII stampabili e newline/tab
            if (32 <= byte <= 126) or byte in {9, 10, 13}:  # 9=tab, 10=newline, 13=carriage return
                safe_bytes.append(byte)

        # Decodifica il buffer pulito
        return safe_bytes.decode(encoding, errors='ignore')