import datetime

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

        self.crash_patterns = [
            "Backtrace:",
            "Guru Meditation Error",
            "Panic",
            "Assert failed:",
            "Fatal exception"
        ]

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

        self.line_buffer = []

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

    def analyze_buffer_for_crash(self) -> Optional[Dict]:
        """
        Analizza il buffer circolare per trovare crash e backtrace completi.

        Returns:
            Dictionary contenente le informazioni sul crash e il backtrace
        """
        crash_info = {
            'timestamp': datetime.datetime.now(),
            'crash_type': None,
            'crash_message': None,
            'context_before': [],
            'backtrace': [],
            'context_after': []
        }

        # Cerca all'indietro nel buffer per trovare l'inizio del crash
        buffer_list = list(self.line_buffer)
        crash_start_idx = None

        for i, line in enumerate(buffer_list):
            for pattern in self.crash_patterns:
                if pattern in line:
                    crash_start_idx = i
                    crash_info['crash_type'] = pattern.rstrip(':')
                    crash_info['crash_message'] = line.strip()
                    break
            if crash_start_idx is not None:
                break

        if crash_start_idx is None:
            return None

        # Raccogli il contesto prima del crash
        crash_info['context_before'] = buffer_list[max(0, crash_start_idx - 5):crash_start_idx]

        # Analizza il backtrace e il contesto dopo
        in_backtrace = False
        for line in buffer_list[crash_start_idx:]:
            frame_info = self.parse_backtrace_line(line)
            if frame_info:
                in_backtrace = True
                # Aggiungi informazioni sul codice sorgente se disponibili
                source_info = self.get_source_location(frame_info['address'])
                if source_info:
                    frame_info.update(source_info)
                crash_info['backtrace'].append(frame_info)
            elif in_backtrace:
                # Se eravamo nel backtrace e ora non lo siamo più, questo è il contesto dopo
                crash_info['context_after'].append(line)

        return crash_info if crash_info['backtrace'] else None

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

    def parse_backtrace_line(self, line: str) -> List[Dict[str, str]]:
        """
        Analizza una riga di backtrace, supportando sia il formato multi-riga che quello compresso.

        Args:
            line: Riga del backtrace da analizzare

        Returns:
            Lista di dizionari contenenti le informazioni dei frame
        """
        frames = []

        # Verifica se è una riga di backtrace compressa
        if line.startswith('Backtrace:'):
            # Rimuove 'Backtrace: ' dall'inizio
            addresses = line[10:].strip()
            # Divide tutti i frame (coppie di indirizzi separate da spazio)
            frame_pairs = addresses.split()

            for i, pair in enumerate(frame_pairs):
                # Divide ogni coppia di indirizzi (PC:SP)
                pc, sp = pair.split(':')
                frames.append({
                    'frame': str(i),
                    'pc': pc,  # Program Counter
                    'sp': sp,  # Stack Pointer
                    'address': pc  # Manteniamo pc come address per compatibilità
                })
            return frames

        # Pattern per il formato originale (una riga per frame)
        pattern = r'(?:Backtrace:)?(?:\s*)?(\d+):(\s+)(0x[0-9a-fA-F]+)(?::0x[0-9a-fA-F]+)?'
        match = re.match(pattern, line)

        if match:
            frames.append({
                'frame': match.group(1),
                'address': match.group(3)
            })

        return frames

    def read_line(self, input):
        lines = input.split('\n')

        for line in lines:
            if False:
                self.line_buffer.append(line)

                # Verifica se c'è un crash da analizzare
                crash_info = self.analyze_buffer_for_crash()
                if crash_info:
                    self.process_crash(crash_info)

            if "Backtrace:" in line:
                spl = line.split('Backtrace:')

                if len(spl) > 1:
                    bline = 'Backtrace:' + spl[1]
                    backtrace = self.parse_backtrace_line(bline)
                    if backtrace is not None and len(backtrace) > 0:
                        for frame_info in backtrace:
                            source_info = self.get_source_location(frame_info['address'])
                            if source_info:
                                frame_info.update(source_info)

                        self.process_complete_backtrace(backtrace)
                        continue

            # Verifica se inizia un backtrace
            if "Backtrace:" in line:
                self.backtrace_mode = True
                self.current_backtrace = []
                return

            if self.backtrace_mode:
                self.current_backtrace.append(line)

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
                    self.process_complete_backtrace(self.current_backtrace)

    def log(self, what):
        print(what)
        #logger.error(what)

    def process_crash(self, crash_info: Dict):
        """
        Processa e logga le informazioni complete sul crash.

        Args:
            crash_info: Dictionary con tutte le informazioni sul crash
        """
        self.log("\n=== ESP32 Crash Detected ===")
        self.log(f"Timestamp: {crash_info['timestamp']}")
        self.log(f"Crash Type: {crash_info['crash_type']}")
        self.log(f"Crash Message: {crash_info['crash_message']}")

        self.log("\n--- Context Before Crash ---")
        for line in crash_info['context_before']:
            self.log(f"Context: {line}")

        self.log("\n--- Backtrace ---")
        for frame in crash_info['backtrace']:
            if 'function' in frame and 'file' in frame and 'line' in frame:
                self.log(
                    f"Frame {frame['frame']}: {frame['function']} "
                    f"at {frame['file']}:{frame['line']} ({frame['address']})"
                )
            else:
                self.log(f"Frame {frame['frame']}: {frame['address']}")

        self.log("\n--- Context After Crash ---")
        for line in crash_info['context_after']:
            self.log(f"Context: {line}")

        self.log("=========================\n")

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