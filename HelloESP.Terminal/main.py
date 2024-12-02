import gi

gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib, Pango
import serial
import serial.tools.list_ports

from transfer_file import *
from ESP32Tracing import *
from generalFunctions import *
from TerminalHandler import *

class SerialInterface(Gtk.Window):
    def __init__(self):
        super().__init__(title="Interfaccia Seriale")
        self.set_border_width(10)
        self.set_default_size(800, 500)

        # Variabile per la connessione seriale
        self.serial_conn = None
        self.tracer = None

        # Layout principale con pannello espandibile
        self.main_paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        self.add(self.main_paned)

        # Contenitore principale per terminal e controlli
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.main_paned.pack1(vbox, True, False)  # resize=True, shrink=False

        # Area superiore per controlli
        controls_box = Gtk.Box(spacing=6)
        vbox.pack_start(controls_box, False, False, 0)

        # Combo box per le porte seriali
        self.port_combo = Gtk.ComboBoxText()
        self.refresh_ports()
        controls_box.pack_start(self.port_combo, True, True, 0)

        # Pulsante aggiorna porte
        refresh_button = Gtk.Button(label="Aggiorna Porte")
        refresh_button.connect("clicked", self.on_refresh_clicked)
        controls_box.pack_start(refresh_button, False, False, 0)

        # Pulsante connetti/disconnetti
        self.connect_button = Gtk.Button(label="Connetti")
        self.connect_button.connect("clicked", self.on_connect_clicked)
        controls_box.pack_start(self.connect_button, False, False, 0)

        # Toggle per il pannello file
        if False:
            self.files_toggle = Gtk.ToggleButton(label="File Manager")
            self.files_toggle.connect("toggled", self.on_files_toggle)
            controls_box.pack_start(self.files_toggle, False, False, 0)

        self.dev_restart_button = Gtk.Button(label="Restart dev")
        self.dev_restart_button.connect("clicket", self.on_dev_reset_clicked)
        controls_box.pack_start(self.dev_restart_button, False, False, 0)

        # Area terminale
        scrolled_window = Gtk.ScrolledWindow()
        scrolled_window.set_hexpand(True)
        scrolled_window.set_vexpand(True)
        vbox.pack_start(scrolled_window, True, True, 0)

        self.terminal_handler = TerminalHandler()
        self.terminal = self.terminal_handler.terminal

        #self.terminal = Gtk.TextView()
        #self.terminal.set_editable(False)
        #self.terminal.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        #self.terminal_buffer = self.terminal.get_buffer()

        # Imposta font monospace per il terminale
        # Create a CSS provider
        css_provider = Gtk.CssProvider()

        # Define the CSS with the font settings
        css = b"""
        terminal {
            font-family: monospace;
        }
        """

        # Load the CSS
        css_provider.load_from_data(css)

        # Apply the CSS to the terminal widget
        style_context = self.terminal.get_style_context()
        style_context.add_provider(css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        scrolled_window.add(self.terminal)

        # Area input
        input_box = Gtk.Box(spacing=6)
        vbox.pack_start(input_box, False, False, 0)

        self.input_entry = Gtk.Entry()
        input_box.pack_start(self.input_entry, True, True, 0)

        send_button = Gtk.Button(label="Invia")
        send_button.connect("clicked", self.on_send_clicked)
        input_box.pack_start(send_button, False, False, 0)

        reset_button = Gtk.Button(label="Reset")
        reset_button.connect("clicked", self.on_reset_clicked)
        input_box.pack_start(reset_button, False, False, 0)

        # Area comandi
        cmd_box = Gtk.Box(spacing=6)
        vbox.pack_start(cmd_box, False, False, 0)

        # Label per distinguere l'area comandi
        cmd_label = Gtk.Label(label="Comandi:")
        cmd_box.pack_start(cmd_label, False, False, 5)

        self.cmd_entry = Gtk.Entry()
        self.cmd_entry.set_placeholder_text("Inserisci comando...")  # Testo suggerimento
        cmd_box.pack_start(self.cmd_entry, True, True, 0)

        execute_button = Gtk.Button(label="Esegui")
        execute_button.connect("clicked", self.on_execute_clicked)
        cmd_box.pack_start(execute_button, False, False, 0)

        # Pannello File Manager
        self.setup_file_manager()

    def setup_file_manager(self):
        """Setup del pannello di gestione file"""
        file_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.main_paned.pack2(file_box, False, False)  # resize=False, shrink=False

        # Label intestazione
        header = Gtk.Label(label="File Manager")
        header.set_markup("<b>File Manager</b>")
        file_box.pack_start(header, False, False, 5)

        # Pulsanti azione
        button_box = Gtk.Box(spacing=6)
        file_box.pack_start(button_box, False, False, 0)

        refresh_files_btn = Gtk.Button(label="Aggiorna")
        refresh_files_btn.connect("clicked", self.on_refresh_files)
        button_box.pack_start(refresh_files_btn, True, True, 0)

        upload_btn = Gtk.Button(label="Carica")
        upload_btn.connect("clicked", self.on_upload_file)
        button_box.pack_start(upload_btn, True, True, 0)

        download_btn = Gtk.Button(label="Scarica")
        download_btn.connect("clicked", self.on_download_file)
        button_box.pack_start(download_btn, True, True, 0)

        delete_btn = Gtk.Button(label="Elimina")
        delete_btn.connect("clicked", self.on_delete_file)
        button_box.pack_start(delete_btn, True, True, 0)

        # Lista file su device
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        file_box.pack_start(scrolled, True, True, 0)

        # Store per la lista file: nome, dimensione, data modifica
        self.files_store = Gtk.ListStore(str, str, str)

        self.files_view = Gtk.TreeView(model=self.files_store)
        self.files_view.set_headers_visible(True)

        # Colonne
        renderer = Gtk.CellRendererText()
        column = Gtk.TreeViewColumn("Nome", renderer, text=0)
        column.set_resizable(True)
        column.set_min_width(150)
        self.files_view.append_column(column)

        renderer = Gtk.CellRendererText()
        column = Gtk.TreeViewColumn("Dimensione", renderer, text=1)
        self.files_view.append_column(column)

        renderer = Gtk.CellRendererText()
        column = Gtk.TreeViewColumn("Data", renderer, text=2)
        self.files_view.append_column(column)

        scrolled.add(self.files_view)

        # Area stato operazioni
        self.status_bar = Gtk.Statusbar()
        file_box.pack_start(self.status_bar, False, False, 0)

    def on_files_toggle(self, button):
        """Gestisce il toggle del pannello file"""
        if button.get_active():
            self.main_paned.get_child2().show()
            if self.serial_conn:
                self.refresh_file_list()
        else:
            self.main_paned.get_child2().hide()

    def on_execute_clicked(self, button):
        command = self.cmd_entry.get_text()
        if command:
            try:
                success, response = execute_command(self, command)
                if success:
                    self.append_terminal(f"Comando eseguito: {command}\nRisposta: {response}\n")
                else:
                    self.append_terminal(f"Errore nell'esecuzione del comando: {response}\n")
            except SerialCommandError as e:
                self.append_terminal(f"Errore seriale: {str(e)}\n")
                if __debug__:
                    raise e
            except Exception as e:
                if __debug__:
                    raise e
            finally:
                self.cmd_entry.set_text("")  # Pulisce il campo dopo l'esecuzione

    def refresh_file_list(self):
        """Aggiorna la lista dei file sul device"""
        if not self.serial_conn:
            self.show_status("Nessuna connessione seriale")
            return

        try:
            files = list_files(self.serial_conn)
            self.files_store.clear()
            for filename, size in files:
                # Formatta dimensione in KB/MB
                if size < 1024:
                    size_str = f"{size} B"
                elif size < 1024 * 1024:
                    size_str = f"{size / 1024:.1f} KB"
                else:
                    size_str = f"{size / 1024 / 1024:.1f} MB"

                self.files_store.append([filename, size_str, "-"])
            self.show_status(f"Trovati {len(files)} file")
        except SerialCommandError as e:
            self.show_status(f"Errore: {str(e)}")
            self.append_terminal(f"Errore lettura file: {str(e)}\n")

    def on_refresh_files(self, button):
        """Handler refresh lista file"""
        self.refresh_file_list()

    def on_upload_file(self, button):
        """Handler upload file"""
        if not self.serial_conn:
            self.show_status("Nessuna connessione seriale")
            return

        dialog = Gtk.FileChooserDialog(
            title="Seleziona file da caricare",
            parent=self,
            action=Gtk.FileChooserAction.OPEN
        )
        dialog.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            Gtk.STOCK_OPEN, Gtk.ResponseType.OK
        )

        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            filename = dialog.get_filename()
            try:
                with open(filename, 'rb') as f:
                    data = f.read()
                    base_name = os.path.basename(filename)
                    success, msg = write_file(self, base_name, data)
                    if success:
                        self.show_status(f"File {base_name} caricato con successo")
                        self.append_terminal(f"File caricato: {base_name}\n")
                        self.refresh_file_list()
                    else:
                        self.show_status(f"Errore upload: {msg}")
                        self.append_terminal(f"Errore upload: {msg}\n")
            except Exception as e:
                self.show_status(f"Errore: {str(e)}")
                self.append_terminal(f"Errore upload: {str(e)}\n")

        dialog.destroy()

    def on_download_file(self, button):
        """Handler download file"""
        selection = self.files_view.get_selection()
        model, treeiter = selection.get_selected()
        if not treeiter:
            self.show_status("Nessun file selezionato")
            return

        if not self.serial_conn:
            self.show_status("Nessuna connessione seriale")
            return

        filename = model[treeiter][0]

        dialog = Gtk.FileChooserDialog(
            title="Salva file",
            parent=self,
            action=Gtk.FileChooserAction.SAVE
        )
        dialog.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            Gtk.STOCK_SAVE, Gtk.ResponseType.OK
        )
        dialog.set_current_name(filename)

        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            save_path = dialog.get_filename()
            try:
                data = read_file(self.serial_conn, filename)
                with open(save_path, 'wb') as f:
                    f.write(data)
                self.show_status(f"File {filename} scaricato con successo")
                self.append_terminal(f"File scaricato: {filename}\n")
            except Exception as e:
                self.show_status(f"Errore download: {str(e)}")
                self.append_terminal(f"Errore download: {str(e)}\n")

        dialog.destroy()

    def on_delete_file(self, button):
        """Handler eliminazione file"""
        selection = self.files_view.get_selection()
        model, treeiter = selection.get_selected()
        if not treeiter:
            self.show_status("Nessun file selezionato")
            return

        if not self.serial_conn:
            self.show_status("Nessuna connessione seriale")
            return

        filename = model[treeiter][0]

        dialog = Gtk.MessageDialog(
            parent=self,
            flags=0,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.OK_CANCEL,
            text=f"Eliminare il file {filename}?"
        )
        dialog.format_secondary_text(
            "Questa operazione non può essere annullata"
        )

        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            try:
                success, msg = delete_file(self.serial_conn, filename)
                if success:
                    self.show_status(f"File {filename} eliminato")
                    self.append_terminal(f"File eliminato: {filename}\n")
                    self.refresh_file_list()
                else:
                    self.show_status(f"Errore eliminazione: {msg}")
                    self.append_terminal(f"Errore eliminazione: {msg}\n")
            except Exception as e:
                self.show_status(f"Errore: {str(e)}")
                self.append_terminal(f"Errore eliminazione: {str(e)}\n")

        dialog.destroy()

    def show_status(self, message):
        """Mostra un messaggio nella status bar"""
        context_id = self.status_bar.get_context_id("file_ops")
        self.status_bar.pop(context_id)
        self.status_bar.push(context_id, message)

        # ... resto della classe esistente ...

    def refresh_ports(self):
        self.port_combo.remove_all()
        ports = serial.tools.list_ports.comports()
        for port in ports:
            self.port_combo.append_text(port.device)
        if ports:
            self.port_combo.set_active(0)

    def on_refresh_clicked(self, button):
        self.refresh_ports()

    def init_tracing(self):
        self.tracer = ESP32BacktraceParser(serial=self.serial_conn)

        self.tracer.serialInterface = self
        self.tracer.set_debug_files(
            addr2line_path="/Users/riccardo/.espressif/tools/xtensa-esp-elf/esp-13.2.0_20240530/xtensa-esp-elf/bin/xtensa-esp32-elf-addr2line", # find $HOME/.espressif -name "xtensa-esp32-elf-addr2line"
            elf_file="/Users/riccardo/Sources/GitHub/hello.esp32/hello-idf/build/hello-idf.elf"
        )

        # Avvio del monitoraggio
        # self.tracer.monitor_serial() # make it manual

    def stop_tracing(self):
        self.tracer = None

    def update_tracing(self, line):
        if self.tracer is not None:
            self.tracer.read_line(line)
            #print("tracer.read_line called")

    def on_dev_reset_clicked(self, button):
        if self.serial_conn is not None:
            send_buffer(self.serial_conn, "$$$RESET$$$".encode("ascii"))

    def on_connect_clicked(self, button):
        if self.serial_conn is None:
            try:
                port = self.port_combo.get_active_text()
                if port:
                    self.serial_conn = serial.Serial(port, 115200, timeout=0)
                    self.connect_button.set_label("Disconnetti")
                    self.append_terminal("Connesso a " + port + "\n")
                    if self.files_toggle.get_active():
                        self.refresh_file_list()
                    GLib.timeout_add(100, self.read_serial)

                    self.init_tracing()
            except serial.SerialException as e:
                self.append_terminal(f"Errore di connessione: {str(e)}\n")
                self.serial_conn = None
        else:
            self.serial_conn.close()
            self.serial_conn = None
            self.connect_button.set_label("Connetti")
            self.append_terminal("Disconnesso\n")
            self.files_store.clear()
            self.stop_tracing()

    def on_send_clicked(self, button):
        if self.serial_conn and self.serial_conn.is_open:
            text = self.input_entry.get_text()
            if text:
                try:
                    data = (text + "\n").encode()
                    self.serial_conn.write(data)
                    self.append_terminal(f"Inviato: {text}\n")
                    self.input_entry.set_text("")
                except serial.SerialException as e:
                    self.append_terminal(f"Errore di invio: {str(e)}\n")

    def on_reset_clicked(self, button):
        buffer = self.terminal.get_buffer()
        buffer.set_text("")

    def read_serial(self):
        if self.serial_conn and self.serial_conn.is_open:
            try:
                while self.serial_conn.in_waiting:
                    data = self.serial_conn.read(self.serial_conn.in_waiting)
                    rec = safe_decode(data)
                    self.update_tracing(rec)

                    self.append_terminal(data.decode('ascii', errors='replace'))
            except serial.SerialException as e:
                self.append_terminal(f"Errore di lettura: {str(e)}\n")
                self.serial_conn.close()
                self.serial_conn = None
                self.connect_button.set_label("Connetti")
                return False
            except Exception as e:
                #print("Data undecoded: ", data)
                self.append_terminal(rec)
                return False

            return True
        return False

    def append_terminal(self, text):
        if self.tracer is not None:
            text = self.tracer.replace_memory_addresses(text)
        self.terminal_handler.append_terminal(text)
        return

        end_iter = self.terminal_buffer.get_end_iter()
        self.terminal_buffer.insert(end_iter, text)
        # Auto-scroll
        self.terminal.scroll_to_iter(self.terminal_buffer.get_end_iter(), 0.0, False, 0.0, 0.0)


def main():
    win = SerialInterface()
    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    Gtk.main()

if __name__ == "__main__":
    main()