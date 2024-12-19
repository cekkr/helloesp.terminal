class StreamHandler:
    def __init__(self, default_callback = None):
        """
        Inizializza il processore di stringhe.

        Args:
            default_callback: La funzione di callback predefinita per le stringhe
                            al di fuori dei contesti definiti.
        """

        def justPrint(out):
            print(out)

        if default_callback is None:
            default_callback = justPrint

        self.default_callback = default_callback
        self.contexts = []  # Lista di tuple (start_tag, end_tag, callback)
        self.current_context = None
        self.buffer = ""

    def add_context(self, start_tag, end_tag, callback):
        """
        Aggiunge un nuovo contesto con i suoi tag e la sua callback.

        Args:
            start_tag: Il tag che indica l'inizio del contesto
            end_tag: Il tag che indica la fine del contesto
            callback: La funzione da chiamare per le stringhe all'interno di questo contesto
        """
        self.contexts.append((start_tag, end_tag, callback))

    def process_string(self, input_string):
        """
        Processa una stringa in input, gestendo i contesti e chiamando
        le appropriate callback.

        Args:
            input_string: La stringa da processare
        """
        # Aggiungiamo la stringa al buffer esistente
        self.buffer += input_string

        while self.buffer:
            if self.current_context is None:
                # Cerchiamo il prossimo tag di inizio
                found_start = False
                for start_tag, end_tag, callback in self.contexts:
                    if start_tag in self.buffer:
                        # Troviamo la posizione del tag di inizio
                        start_pos = self.buffer.index(start_tag)

                        # Processiamo il testo prima del tag con la callback predefinita
                        if start_pos > 0:
                            self.default_callback(self.buffer[:start_pos])

                        # Rimuoviamo il testo processato e il tag di inizio
                        self.buffer = self.buffer[start_pos + len(start_tag):]
                        self.current_context = (end_tag, callback)
                        found_start = True
                        break

                if not found_start:
                    # Se non troviamo tag di inizio, processiamo tutto il buffer
                    if self.buffer:
                        self.default_callback(self.buffer)
                        self.buffer = ""
                    break

            else:
                # Siamo all'interno di un contesto, cerchiamo il tag di fine
                end_tag, callback = self.current_context
                if end_tag in self.buffer:
                    # Troviamo la posizione del tag di fine
                    end_pos = self.buffer.index(end_tag)

                    # Processiamo il testo nel contesto con la callback appropriata
                    if end_pos > 0:
                        callback(self.buffer[:end_pos])

                    # Rimuoviamo il testo processato e il tag di fine
                    self.buffer = self.buffer[end_pos + len(end_tag):]
                    self.current_context = None
                else:
                    # Se non troviamo il tag di fine, manteniamo il buffer per la prossima iterazione
                    break

'''
# Esempio di utilizzo
def default_handler(text):
    print(f"Default: {text}")


def task_monitor_handler(text):
    print(f"Task Monitor: {text}")


# Creazione e configurazione del processore
processor = StringProcessor(default_handler)
processor.add_context("!!TASKMONITOR!!", "!!TASKMONITOREND!!", task_monitor_handler)

# Test del processore
test_input = """Questo è un testo normale.
!!TASKMONITOR!!
Questo è un task da monitorare
con più righe
!!TASKMONITOREND!!
E questo è di nuovo testo normale."""

# Processiamo la stringa
processor.process_string(test_input)
'''