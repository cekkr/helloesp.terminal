import asyncio
from typing import Callable, Optional, List, Tuple
import time
import threading
from queue import Queue
from concurrent.futures import ThreadPoolExecutor

from generalFunctions import contains_alphanumeric


class StreamHandler:
    def __init__(self, default_callback: Optional[Callable] = None):
        """
        Inizializza il processore di stringhe con buffer temporizzato.

        Args:
            default_callback: La funzione di callback predefinita per le stringhe
                            al di fuori dei contesti definiti.
        """

        def justPrint(out: str) -> None:
            print(out)

        self.default_callback = default_callback or justPrint
        self.contexts: List[Tuple[str, str, Callable]] = []
        self.current_context: Optional[Tuple[str, Callable]] = None
        self.buffer = ""
        self.last_input_time = 0
        self.buffer_timeout = 0.2  # 200ms timeout
        self.processing = False
        self.input_queue = Queue()
        self._stop_event = threading.Event()
        self._processor_thread = None
        self._executor = ThreadPoolExecutor(max_workers=1)

        self._start_tags = []
        self._end_tags = []

        self.end_by_start = {}
        self.start_by_end = {}

    def start(self):
        """
        Avvia il thread di processing in background.
        """
        if self._processor_thread is None:
            self._stop_event.clear()
            self._processor_thread = threading.Thread(target=self._process_loop)
            self._processor_thread.daemon = True
            self._processor_thread.start()

    def stop(self):
        """
        Ferma il thread di processing e pulisce il buffer.
        """
        if self._processor_thread is not None:
            self._stop_event.set()
            self.input_queue.put(None)  # Segnale di stop
            self._processor_thread.join()
            self._processor_thread = None
            self.flush()

    def add_context(self, start_tag: str, end_tag: str, callback: Callable) -> None:
        """
        Aggiunge un nuovo contesto con i suoi tag e la sua callback.

        Args:
            start_tag: Il tag che indica l'inizio del contesto
            end_tag: Il tag che indica la fine del contesto
            callback: La funzione da chiamare per le stringhe all'interno di questo contesto
        """
        self.contexts.append((start_tag, end_tag, callback))

        self._start_tags.append(start_tag)
        self._end_tags.append(end_tag)

        self.end_by_start[start_tag] = end_tag
        self.start_by_end[end_tag] = start_tag

    def _process_buffer(self) -> None:
        """
        Processa il buffer internamente, gestendo i contesti e chiamando
        le appropriate callback.
        """
        while self.buffer and not self._stop_event.is_set():
            theres_tag = False
            if self.current_context is None:
                # Cerchiamo il prossimo tag di inizio
                for start_tag, end_tag, callback in self.contexts:
                    remaining_buffer = self.buffer

                    start_pos = self.buffer.find(start_tag)
                    if start_pos >= 0:
                        theres_tag = True
                        self.default_callback(self.buffer[:start_pos])
                        self.buffer = self.buffer[start_pos + len(start_tag):]
                        self.current_context = (end_tag, callback)

                    if end_tag in remaining_buffer:
                        theres_tag = True
                        end_pos = self.buffer.find(end_tag)
                        self.current_context[1](self.buffer[:end_pos])
                        self.buffer = self.buffer[end_pos + len(end_tag):]
                        self.current_context = None
            else:
                # Siamo all'interno di un contesto, cerchiamo il tag di fine
                end_tag, callback = self.current_context
                if end_tag in self.buffer:
                    theres_tag = True

                    # Troviamo la posizione del tag di fine
                    end_pos = self.buffer.find(end_tag)

                    # Processiamo il testo nel contesto con la callback appropriata
                    if end_pos >= 0:
                        callback(self.buffer[:end_pos])

                    # Rimuoviamo il testo processato e il tag di fine
                    self.buffer = self.buffer[end_pos + len(end_tag):]
                    self.current_context = None

            if not theres_tag:
                if '\n' in self.buffer:
                    spl = self.buffer.split('\n')
                    self.buffer = spl.pop()
                    cbk = self.current_context[1] if self.current_context is not None else self.default_callback
                    for line in spl:
                        if contains_alphanumeric(line):
                            cbk(line)
                else:
                    break


    def _process_loop(self):
        """
        Loop principale del thread di processing.
        """
        while not self._stop_event.is_set():
            try:
                if self.input_queue.empty():
                    # Timeout raggiunto, processiamo il buffer
                    if time.time() - self.last_input_time >= self.buffer_timeout:
                        self._process_buffer()
                    continue

                # Attendiamo nuovo input o timeout
                input_data = self.input_queue.get(timeout=self.buffer_timeout)
                if input_data is None:  # Segnale di stop
                    break
                self.buffer += input_data

                def check_to_process():
                    toProcess = False
                    afterProcess = ""
                    if self.current_context is None:
                        for tag in self._end_tags:
                            if tag in self.buffer:
                                spl = self.buffer.split(tag)
                                toProcess = True
                                self.buffer = spl[0] + tag
                                if len(spl) > 1:
                                    afterProcess = tag.join(spl[1:])
                                break
                    else:
                        for tag in self._start_tags:
                            if tag in self.buffer:
                                spl = self.buffer.split(tag)
                                toProcess = True
                                self.buffer = spl[0]
                                afterProcess = tag
                                if len(spl) > 1:
                                    afterProcess += tag.join(spl[1:])
                                break

                    if toProcess:
                        self._process_buffer()
                        self.buffer += afterProcess

                    return toProcess

                update_last_time = False
                while check_to_process():
                    update_last_time = True

                if update_last_time:
                    self.last_input_time = time.time()

            except Exception as e:
                print(f"Errore nel thread di processing: {e}")
                raise e

    def has_start_tag(self, text):
        for tag in self._start_tags:
            if tag in text:
                return tag, text.find(tag)
        return None, -1

    def has_end_tag(self, text):
        for tag in self._end_tags:
            if tag in text:
                return tag, text.find(tag)
        return None, -1

    def process_string(self, input_string: str) -> None:
        """
        Processa una stringa in input in modo sincrono.

        Args:
            input_string: La stringa da processare
        """
        if self._processor_thread is None:
            self.start()

        input_string = input_string.replace('\r', '')

        # Ignore end context of un-opened context
        if self.current_context is None:
            end_tag, end_pos = self.has_end_tag(input_string)
            if end_tag is not None:
                start_tag = self.start_by_end[end_tag]
                start_pos = input_string.find(start_tag)

                if start_pos < 0 or start_pos > end_pos:
                    spl = input_string.split(end_tag)
                    input_string = end_tag.join(spl[1:])
        #todo: else: an open tag before the close tag

        self.input_queue.put(input_string)

    async def process_string_async(self, input_string: str) -> None:
        """
        Processa una stringa in input in modo asincrono.

        Args:
            input_string: La stringa da processare
        """
        if self._processor_thread is None:
            self.start()

        # Usiamo ThreadPoolExecutor per non bloccare l'event loop
        await asyncio.get_event_loop().run_in_executor(
            self._executor,
            self.input_queue.put,
            input_string.replace('\r', '')
        )

    def flush(self) -> None:
        """
        Forza il processing del buffer rimanente con la callback di default.
        """
        if self.buffer:
            self.default_callback(self.buffer)
            self.buffer = ""
            self.current_context = None

    def __del__(self):
        """
        Cleanup alla distruzione dell'oggetto.
        """
        self.stop()
        self._executor.shutdown(wait=False)

    def exit_context(self):
        self.current_context = None

# Esempio di utilizzo sincrono
def example_sync():
    def default_handler(text: str) -> None:
        print(f"Default: {text}")

    def task_monitor_handler(text: str) -> None:
        print(f"Task Monitor: {text}")

    # Creazione e configurazione del processore
    processor = StreamHandler(default_handler)
    processor.add_context("!!TASKMONITOR!!", "!!TASKMONITOREND!!", task_monitor_handler)

    # Test del processore con input frammentato
    test_input_parts = [
        "Questo è un testo normale.\n!!TASK",
        "MONITOR!!\nQuesto è un task da ",
        "monitorare\ncon più righe\n!!TASKMONITOR",
        "END!!\nE questo è di nuovo testo normale."
    ]

    try:
        for part in test_input_parts:
            processor.process_string(part)
            time.sleep(0.1)  # Simuliamo un ritardo tra i frammenti
    finally:
        processor.stop()


# Esempio di utilizzo sincrono
def example_sync():
    def default_handler(text: str) -> None:
        print(f"Default: {text}")

    def task_monitor_handler(text: str) -> None:
        print(f"Task Monitor: {text}")

    # Creazione e configurazione del processore
    processor = StreamHandler(default_handler)
    processor.add_context("!!TASKMONITOR!!", "!!TASKMONITOREND!!", task_monitor_handler)

    # Test del processore con input frammentato
    test_input_parts = [
        "Questo è un testo normale.\n!!TASK",
        "MONITOR!!\nQuesto è un task da ",
        "monitorare\ncon più righe\n!!TASKMONITOR",
        "END!!\nE questo è di nuovo testo normale."
    ]

    try:
        for part in test_input_parts:
            processor.process_string(part)
            time.sleep(0.1)  # Simuliamo un ritardo tra i frammenti
    finally:
        processor.stop()


# Esempio di utilizzo asincrono
async def example_async():
    def default_handler(text: str) -> None:
        print(f"Default: {text}")

    def task_monitor_handler(text: str) -> None:
        print(f"Task Monitor: {text}")

    # Creazione e configurazione del processore
    processor = StreamHandler(default_handler)
    processor.add_context("!!TASKMONITOR!!", "!!TASKMONITOREND!!", task_monitor_handler)

    # Test del processore con input frammentato
    test_input_parts = [
        "Questo è un testo normale.\n!!TASK",
        "MONITOR!!\nQuesto è un task da ",
        "monitorare\ncon più righe\n!!TASKMONITOR",
        "END!!\nE questo è di nuovo testo normale."
    ]

    try:
        for part in test_input_parts:
            await processor.process_string_async(part)
            await asyncio.sleep(0.1)  # Simuliamo un ritardo tra i frammenti
    finally:
        processor.stop()
