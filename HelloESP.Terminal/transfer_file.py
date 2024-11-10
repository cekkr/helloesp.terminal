import serial
import os
import time
from typing import Union, Optional


def upload_file_to_esp32(
        serial_port: Union[str, serial.Serial],
        file_path: str,
        baud_rate: int = 115200,
        timeout: int = 5
) -> bool:
    """
    Carica un file sull'ESP32 tramite connessione seriale.

    Args:
        serial_port: Porta seriale (es. "COM3" o "/dev/ttyUSB0") o oggetto Serial
        file_path: Percorso del file da caricare
        baud_rate: Baud rate della connessione seriale
        timeout: Timeout in secondi per le operazioni seriali

    Returns:
        bool: True se il caricamento è avvenuto con successo, False altrimenti

    Raises:
        FileNotFoundError: Se il file non esiste
        serial.SerialException: Se ci sono problemi con la porta seriale
    """

    # Verifica che il file esista
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File non trovato: {file_path}")

    # Ottiene dimensione file e nome base
    file_size = os.path.getsize(file_path)
    file_name = os.path.basename(file_path)

    # Gestisce sia stringhe che oggetti Serial
    if isinstance(serial_port, str):
        ser = serial.Serial(serial_port, baud_rate, timeout=timeout)
    else:
        ser = serial_port

    try:
        # Svuota i buffer
        ser.reset_input_buffer()
        ser.reset_output_buffer()

        # Invia il comando con nome file e dimensione
        command = f"$$$WRITE_FILE,{file_name},{file_size}\n"
        ser.write(command.encode())

        # Aspetta un momento per l'elaborazione del comando
        time.sleep(0.1)

        # Legge il file e lo invia a blocchi
        with open(file_path, 'rb') as f:
            # Invia il contenuto del file
            while True:
                chunk = f.read(1024)  # Legge a blocchi di 1KB
                if not chunk:
                    break
                ser.write(chunk)
                # Piccola pausa per evitare overflow del buffer
                time.sleep(0.01)

        # Aspetta e legge la risposta
        response = ""
        timeout_start = time.time()

        while time.time() - timeout_start < timeout:
            if ser.in_waiting:
                char = ser.read().decode(errors='ignore')
                response += char
                if '\n' in response:
                    break

        # Verifica la risposta
        if "OK" in response:
            print(f"File {file_name} caricato con successo!")
            return True
        else:
            print(f"Errore nel caricamento del file: {response.strip()}")
            return False

    except Exception as e:
        print(f"Errore durante il caricamento: {str(e)}")
        return False

    finally:
        # Chiude la porta seriale solo se l'abbiamo aperta noi
        if isinstance(serial_port, str):
            ser.close()


# Funzione di utility per trovare le porte seriali ESP32
def find_esp32_ports():
    """
    Trova le porte seriali dove potrebbe essere collegato un ESP32.
    Returns:
        list: Lista delle porte seriali probabilmente ESP32
    """
    import serial.tools.list_ports

    esp_ports = []
    for port in serial.tools.list_ports.comports():
        # Cerca i vendor ID comuni per ESP32
        if any(vid in port.vid for vid in [0x10C4, 0x1A86]):  # Silicon Labs, QinHeng
            esp_ports.append(port.device)
    return esp_ports