import serial
import re
import logging
from typing import List, Dict, Optional


class ESP32BacktraceParser:
    def __init__(self, port: str = None, baudrate: int = 115200, serial : serial.Serial = None):
        """
        Inizializza il parser per il backtrace dell'ESP32.

        Args:
            port: Porta seriale (es. 'COM3' o '/dev/ttyUSB0')
            baudrate: Baud rate della comunicazione seriale
        """

        if serial is not None:
            self.serial = serial
        else:
            self.serial = serial.Serial(port, baudrate)

        self.logger = logging.getLogger('ESP32_Monitor')
        self.addr2line_path = None
        self.elf_file = None

    def set_debug_files(self, addr2line_path: str, elf_file: str):
        """
        Imposta i file necessari per il debug simbolico.

        Args:
            addr2line_path: Percorso dell'eseguibile addr2line
            elf_file: Percorso del file ELF del progetto
        """
        self.addr2line_path = addr2line_path
        self.elf_file = elf_file

        self.backtrace_mode = False
        self.current_backtrace: List[Dict] = []

    def parse_backtrace_line(self, line: str) -> Optional[Dict[str, str]]:
        """
        Analizza una singola riga del backtrace.

        Args:
            line: Riga del backtrace da analizzare

        Returns:
            Dictionary con le informazioni estratte o None se non è una riga di backtrace
        """
        # Pattern per il formato tipico del backtrace ESP32
        pattern = r'(?:Backtrace:)?(?:\s*)?(\d+):(\s+)(0x[0-9a-fA-F]+)(?::0x[0-9a-fA-F]+)?'
        match = re.match(pattern, line)

        if match:
            return {
                'frame': match.group(1),
                'address': match.group(3)
            }
        return None

    def get_source_location(self, address: str) -> Optional[Dict[str, str]]:
        """
        Ottiene la posizione nel codice sorgente usando addr2line.

        Args:
            address: Indirizzo di memoria in formato esadecimale

        Returns:
            Dictionary con file e riga del codice sorgente
        """
        if not (self.addr2line_path and self.elf_file):
            self.logger.warning("File di debug non configurati")
            return None

        import subprocess
        try:
            cmd = [
                self.addr2line_path,
                '-e', self.elf_file,
                '-f', '-C', '-p',
                address
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                # Esempio output: main.cpp:123 (function_name)
                output = result.stdout.strip()
                parts = output.split(':')
                if len(parts) >= 2:
                    return {
                        'file': parts[0],
                        'line': parts[1].split()[0],
                        'function': output[output.find('(') + 1:output.find(')')]
                    }
        except Exception as e:
            self.logger.error(f"Errore nell'esecuzione di addr2line: {e}")
        return None

    def monitor_serial(self):
        """
        Monitora la porta seriale e processa i backtrace quando vengono rilevati.
        """

        self.logger.info("Avvio monitoraggio seriale...")

        while True:
            try:
                if self.serial.in_waiting:
                    line = self.serial.readline().decode('utf-8').strip()

                    # Logga sempre la linea originale
                    self.logger.debug(f"Raw serial: {line}")

                    self.read_line(line)

            except serial.SerialException as e:
                self.logger.error(f"Errore seriale: {e}")
                break
            except Exception as e:
                self.logger.error(f"Errore generico: {e}")
                continue

    def read_line(self, input):
        lines = input.split('\n')

        for line in lines:
            # Verifica se inizia un backtrace
            if "Backtrace:" in line:
                self.backtrace_mode = True
                self.current_backtrace = []
                return

            if self.backtrace_mode:
                # Analizza la riga del backtrace
                frame_info = self.parse_backtrace_line(line)

                if frame_info:
                    # Ottieni informazioni sul codice sorgente
                    source_info = self.get_source_location(frame_info['address'])
                    if source_info:
                        frame_info.update(source_info)
                    self.current_backtrace.append(frame_info)
                else:
                    # Se la riga non corrisponde al pattern, il backtrace è finito
                    if self.current_backtrace:
                        self.process_complete_backtrace(self.current_backtrace)
                    self.backtrace_mode = False

                if not line.strip():
                    self.process_complete_backtrace()

    def log(self, what):
        print(what)
        #logger.error(what)

    def process_complete_backtrace(self, backtrace: List[Dict]):
        """
        Processa un backtrace completo.

        Args:
            backtrace: Lista di frame del backtrace
        """
        self.log("=== Backtrace Completo ===")
        for frame in backtrace:
            if 'function' in frame and 'file' in frame and 'line' in frame:
                self.log(
                    f"Frame {frame['frame']}: {frame['function']} "
                    f"at {frame['file']}:{frame['line']} ({frame['address']})"
                )
            else:
                self.log(f"Frame {frame['frame']}: {frame['address']}")
        self.log("========================")