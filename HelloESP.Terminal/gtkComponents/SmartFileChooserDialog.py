import gi

gi.require_version('Gtk', '3.0')
from gi.repository import Gtk
import json
import os
from pathlib import Path


class SmartFileChooserDialog(Gtk.FileChooserDialog):
    """
    Estensione di Gtk.FileChooserDialog che memorizza automaticamente
    l'ultima directory utilizzata per ciascun tipo di dialogo.
    """

    # File di configurazione nella home directory dell'utente
    CONFIG_FILE = os.path.join(str(Path.home()), '.gtk_smart_dialog_paths.json')

    def __init__(self, title="", parent=None, action=Gtk.FileChooserAction.OPEN,
                 buttons=("Cancel", Gtk.ResponseType.CANCEL, "OK", Gtk.ResponseType.OK)):
        """
        Inizializza il dialog e carica l'ultima directory utilizzata per questo titolo.

        Args:
            title (str): Titolo del dialog, usato anche come chiave per memorizzare il percorso
            parent (Gtk.Window): Finestra parent
            action (Gtk.FileChooserAction): Tipo di azione (OPEN, SAVE, etc.)
            buttons (tuple): Tupla contenente le coppie (testo_bottone, risposta)
        """
        super().__init__(title=title, parent=parent, action=action)

        # Aggiungi i bottoni
        for i in range(0, len(buttons), 2):
            self.add_button(buttons[i], buttons[i + 1])

        self.title = title
        self.set_modal(True)

        # Carica l'ultima directory utilizzata per questo titolo
        last_path = self._load_last_path()
        if last_path and os.path.exists(last_path):
            self.set_current_folder(last_path)

    def run(self):
        """
        Esegue il dialog e salva il percorso selezionato se l'utente clicca OK.

        Returns:
            int: Il codice di risposta del dialog
        """
        response = super().run()

        if response == Gtk.ResponseType.OK:
            # Salva il percorso corrente
            self._save_last_path(self.get_current_folder())

        return response

    def _load_last_path(self):
        """
        Carica l'ultimo percorso utilizzato per questo titolo dal file di configurazione.

        Returns:
            str: L'ultimo percorso utilizzato o None se non trovato
        """
        try:
            if os.path.exists(self.CONFIG_FILE):
                with open(self.CONFIG_FILE, 'r') as f:
                    paths = json.load(f)
                    return paths.get(self.title)
        except Exception as e:
            print(f"Errore nel caricamento del percorso: {e}")
        return None

    def _save_last_path(self, path):
        """
        Salva il percorso corrente nel file di configurazione.

        Args:
            path (str): Il percorso da salvare
        """
        try:
            # Carica i percorsi esistenti o crea un nuovo dizionario
            paths = {}
            if os.path.exists(self.CONFIG_FILE):
                with open(self.CONFIG_FILE, 'r') as f:
                    paths = json.load(f)

            # Aggiorna il percorso per questo titolo
            paths[self.title] = path

            # Salva il file di configurazione aggiornato
            with open(self.CONFIG_FILE, 'w') as f:
                json.dump(paths, f, indent=2)

        except Exception as e:
            print(f"Errore nel salvataggio del percorso: {e}")


# Esempio di utilizzo:
if __name__ == "__main__":
    def on_file_selected(dialog, response):
        if response == Gtk.ResponseType.OK:
            print(f"File selezionato: {dialog.get_filename()}")
        dialog.destroy()
        Gtk.main_quit()


    win = Gtk.Window(title="Test Dialog")
    win.connect("destroy", Gtk.main_quit)

    button = Gtk.Button(label="Apri File")
    button.connect("clicked", lambda x: SmartFileChooserDialog(
        title="Seleziona un file",
        parent=win,
        action=Gtk.FileChooserAction.OPEN
    ).run())

    win.add(button)
    win.show_all()
    Gtk.main()