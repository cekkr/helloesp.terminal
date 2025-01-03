import datetime
import threading

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
            raise Exception("Nope, it don't create the serial")

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

        self.serialInterface = None

        self.backtrace = None
        self.results = ""

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
        self.last_backtrace = ""

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

    def extract_backtrace_addresses(self, line) -> list[str]:
        """
        Estrae gli indirizzi da una stringa di backtrace.
        Se un indirizzo contiene ':', i due componenti vengono uniti come singolo elemento.

        Args:
            line: Stringa contenente il backtrace

        Returns:
            Lista di stringhe contenenti gli indirizzi trovati
        """
        # Rimuove "Backtrace:" se presente
        if "Backtrace:" in line:
            line = line.split("Backtrace:")[1].strip()

        # Lista per memorizzare gli indirizzi trovati
        addresses = []

        # Divide la stringa in parti separate da spazi
        parts = line.split()

        for part in parts:
            if "0x" in part:  # Verifica che sia un indirizzo esadecimale
                addresses.append(part)

        return addresses

    def read_line(self, input):
        threading.Thread(target=self.read_line_thread, args=(input,)).start()

    def read_line_thread(self, input):
        lines = (input+"\n").split('\n')

        self.results = ""
        for line in lines:
            if False:
                self.line_buffer.append(line)

                # Verifica se c'è un crash da analizzare
                crash_info = self.analyze_buffer_for_crash()
                if crash_info:
                    #self.process_crash(crash_info)
                    pass

            bline = line
            if "Backtrace:" in line:
                spl = line.split('Backtrace:')
                self.backtrace_mode = True
                bline = 'Backtrace:' + spl[1]
                self.current_backtrace = [bline]
                continue

            if self.backtrace_mode:
                if '0x' in bline:
                    self.current_backtrace.append(bline)
                else:
                    backtrace = ''.join(self.current_backtrace)
                    backtrace = self.extract_backtrace_addresses(backtrace)

                    frames = []
                    numFrame = 0
                    for address in backtrace:
                        frame_info = {
                            'frame': numFrame,
                            'address': address
                        }

                        numFrame += 1
                        source_info = self.get_source_location(frame_info['address'])
                        if source_info:
                            frame_info.update(source_info)

                        frames.append(frame_info)

                    self.backtrace_mode = False
                    self.process_complete_backtrace(frames)
                    continue

                '''
                if self.backtrace is not None and len(backtrace) > 0:
                    for frame_info in backtrace:
                        source_info = self.get_source_location(frame_info['address'])
                        if source_info:
                            frame_info.update(source_info)

                    self.process_complete_backtrace(backtrace)
                    continue
                '''

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

                if frame_info is None or len(frame_info) == 0:
                    self.process_complete_backtrace(self.current_backtrace)

        return self.results

    def replace_memory_addresses(self, input_string):
        """
        Cerca gli indirizzi di memoria ESP32 nel formato 0x3ffxxxxx in una stringa
        e li sostituisce con i loro nomi simbolici usando get_source_location().

        Args:
            input_string (str): La stringa da processare
            get_source_location (callable): Funzione che converte l'indirizzo in nome simbolico

        Returns:
            str: La stringa con gli indirizzi sostituiti
        """
        # Pattern regex per trovare indirizzi ESP32 nel formato 0x3ffxxxxx
        pattern = r'0x[0-9a-f]{8}'

        def replace_match(match):
            address = match.group(0)
            try:
                # Converte la stringa dell'indirizzo in intero
                #addr_int = int(address, 16)
                # Ottiene il nome simbolico
                location = self.get_source_location(address)

                if location is not None:
                    res = ''
                    for k,v in location:
                        res += k+": "+v+"\n"
                    return res

                return address
            except ValueError:
                return address

        try:
            # Sostituisce tutti gli indirizzi trovati
            result = re.sub(pattern, replace_match, input_string)
            return result
        except:
            return input_string

    def log(self, what):
        print(what)
        self.serialInterface.main_thread_queue.put(("terminal_append_notrace", "\x1b[31m"+what+"\x1b[0m\n"))
        self.results += what + '\n'
        #logger.error(what)

    def process_complete_backtrace(self, backtrace: List[Dict]):
        """
        Processa un backtrace completo.

        Args:
            backtrace: Lista di frame del backtrace
        """

        backtrace_stamp = str(backtrace)
        if self.last_backtrace == backtrace_stamp:
            return
        else:
            self.last_backtrace = backtrace_stamp


        self.log("=== Backtrace Completo ===")
        for frame in backtrace:
            if type(frame) is str:
                self.log(frame+"\n")
                continue

            if 'function' in frame and 'file' in frame and 'line' in frame:
                self.log(
                    f"Frame {frame['frame']}: {frame['function']} "
                    f"at {frame['file']}:{frame['line']} ({frame['address']})"
                )
            else:
                self.log(f"Frame {frame['frame']}: {frame['address']}")
        self.log("========================")