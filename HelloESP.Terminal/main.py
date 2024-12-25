import stat
import subprocess
import threading
from datetime import time
from pathlib import Path

import gi

from MonitorWidget import MonitorWidget
from StreamHandler import StreamHandler

#from transfer_file import SerialCommandError

gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib, Pango
import serial
import serial.tools.list_ports

import subprocess
import tempfile
import os
import stat
from pathlib import Path
from typing import Optional, Dict, Union, Callable
from threading import Thread

from transfer_file import *
from ESP32Tracing import *
from generalFunctions import *
from TerminalHandler import *
#from envVar import *

class SerialInterface(Gtk.Window):
    def __init__(self):
        self.buffer = ""
        self.esp_path = os.getenv('IDF_PATH')
        self.project_path = "/Users/riccardo/Sources/GitHub/hello.esp32/hello-idf"
        self._espressif_path = None

        self.main_thread_queue = Queue()

        self.is_building = False
        
        self.block_serial = False
        self.redirect_serial = False
        self.last_serial_output = None

        self.init_receiver()

        super().__init__(title="HelloESP Monitor")
        self.set_border_width(10)
        self.set_default_size(1400, 1000)

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
        self.files_toggle = Gtk.ToggleButton(label="File Manager")
        self.files_toggle.connect("toggled", self.on_files_toggle)
        controls_box.pack_start(self.files_toggle, False, False, 0)

        self.dev_restart_button = Gtk.Button(label="Restart dev")
        self.dev_restart_button.connect("clicked", self.on_dev_reset_clicked)
        controls_box.pack_start(self.dev_restart_button, False, False, 0)

        # Area terminale
        self.terminal_handler = TerminalHandler()
        terminal_box = self.terminal_handler.get_widget()
        self.add(terminal_box)
        self.terminal = self.terminal_handler.terminal
        vbox.pack_start(terminal_box, True, True, 0)

        self.terminal_handler.add_save_button()

        #####
        #####
        #####

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

        #scrolled_window.add(self.terminal)

        # Area input
        input_box = Gtk.Box(spacing=6)
        vbox.pack_start(input_box, False, False, 0)

        self.input_entry = Gtk.Entry()
        self.input_entry.connect("activate", self.on_send_clicked)
        input_box.pack_start(self.input_entry, True, True, 0)

        send_button = Gtk.Button(label="Invia")
        send_button.connect("clicked", self.on_send_clicked)
        input_box.pack_start(send_button, False, False, 0)

        reset_button = Gtk.Button(label="Clear")
        reset_button.connect("clicked", self.on_reset_clicked)
        input_box.pack_start(reset_button, False, False, 0)

        # Area comandi
        cmd_box = Gtk.Box(spacing=6)
        vbox.pack_start(cmd_box, False, False, 0)

        # Label per distinguere l'area comandi
        cmd_label = Gtk.Label(label="Comandi:")
        cmd_box.pack_start(cmd_label, False, False, 5)

        self.cmd_entry = Gtk.Entry()
        self.cmd_entry.connect("activate", self.on_execute_clicked)
        self.cmd_entry.set_placeholder_text("Inserisci comando...")  # Testo suggerimento
        cmd_box.pack_start(self.cmd_entry, True, True, 0)

        execute_button = Gtk.Button(label="Esegui")
        execute_button.connect("clicked", self.on_execute_clicked)
        cmd_box.pack_start(execute_button, False, False, 0)

        # Pannello File Manager
        self.setup_file_manager()
        self.setup_backtrace_zone(vbox)

        # Monitor widget
        self.monitor_widget = MonitorWidget(self)
        controls_box.pack_start(self.monitor_widget.get_toggle_button(), False, False, 0)

        # Test del monitor
        self.monitor_widget.append_text("Tasks monitor")

        #####
        GLib.timeout_add(50, self.check_main_thread_queue)

    ###
    ###
    ###

    def check_main_thread_queue(self):
        try:
            while not self.main_thread_queue.empty():
                msg_type, value = self.main_thread_queue.get()

                if msg_type in ["terminal_append", "append_terminal"]: # don't you worry about the dislexy
                    self.terminal_handler.append_terminal(value)

                    if self.tracer is not None:
                        self.tracer.read_line(value)

                elif msg_type == "terminal_append_notrace":
                    self.terminal_handler.append_terminal(value)
                elif msg_type == "monitor_append":
                    self.monitor_widget.append_text(value)
                else:
                    print("msg_type not found: " , msg_type)

        except Exception as e:
            print("check_main_thread_queue: ", str(e))

        return True

    def init_receiver(self):
        def on_received_normal(text):
            self.update_tracing(text)
            self.main_thread_queue.put(("terminal_append", text))

        def on_received_monitor(text):
            self.main_thread_queue.put(("monitor_append", text))

        self.stream_handler = StreamHandler(on_received_normal)
        self.stream_handler.add_context("!!TASKMONITOR!!", "!!TASKMONITOREND!!", on_received_monitor)

    ###
    ###
    ###

    def setup_backtrace_zone(self, parent_box):
        ###
        ### Backtrace area
        ###
        self.backtrace_parent_box = parent_box

        TRACEBACK_AREA_HEIGHT = 300

        # Creo il pulsante toggle
        self.backtrace_toggle_button = Gtk.ToggleButton(label="Mostra Traceback")
        self.backtrace_toggle_button.connect("toggled", self.backtrace_on_toggle_button_clicked)
        self.backtrace_parent_box.pack_start(self.backtrace_toggle_button, False, False, 0)

        # Creo il contenitore per l'area traceback
        self.traceback_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)

        # Box orizzontale per il textbox e il pulsante Check
        self.backtrace_input_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

        # Entry per inserire il traceback
        self.backtrace_entry = Gtk.Entry()
        self.backtrace_input_box.pack_start(self.backtrace_entry, True, True, 0)

        # Pulsante Check
        self.backtrace_check_button = Gtk.Button(label="Check traceback")
        self.backtrace_check_button.connect("clicked", self.backtrace_on_check_clicked)
        self.backtrace_input_box.pack_start(self.backtrace_check_button, False, False, 0)

        self.traceback_box.pack_start(self.backtrace_input_box, False, False, 0)

        # TextView per i risultati
        scrolled_window = Gtk.ScrolledWindow()
        scrolled_window.set_size_request(-1, TRACEBACK_AREA_HEIGHT)

        self.backtrace_textview = Gtk.TextView()
        self.backtrace_textview.set_wrap_mode(Gtk.WrapMode.WORD)
        self.backtrace_textview.set_editable(False)
        scrolled_window.add(self.backtrace_textview)

        self.traceback_box.pack_start(scrolled_window, True, True, 0)

        # Inizialmente nascondi l'area
        self.backtrace_parent_box.pack_start(self.traceback_box, True, True, 0)

        def hide_it():
            time.sleep(2)
            self.traceback_box.hide()
            #self.backtrace_on_toggle_button_clicked(self.backtrace_toggle_button)

        # Crea e avvia il thread per l'attesa di 2 secondi
        thread_attesa = threading.Thread(target=hide_it)
        thread_attesa.start()

    def setup_file_manager(self):
        """Setup del pannello di gestione file"""
        file_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.main_paned.pack2(file_box, False, False)  # resize=False, shrink=False

        ###
        ### Compile zone
        ###
        compile_button_box = Gtk.Box(spacing=6)
        file_box.pack_start(compile_button_box, False, False, 0)

        btn_build = Gtk.Button(label="Build")
        btn_build.connect("clicked", self.on_build)
        compile_button_box.pack_start(btn_build, True, True, 0)

        ###
        ###
        ###
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

    ###
    ###
    ###

    def backtrace_on_toggle_button_clicked(self, button):
        if button.get_active():
            self.traceback_box.show_all()
            button.set_label("Nascondi Traceback")
        else:
            self.traceback_box.hide()
            button.set_label("Mostra Traceback")

    def backtrace_on_check_clicked(self, button):
        # Qui puoi implementare la logica per processare il traceback
        input_text = self.backtrace_entry.get_text()
        buffer = self.backtrace_textview.get_buffer()
        input_text = input_text.replace('\\n', '\n')
        buffer.set_text(f"Analisi del traceback:\n{input_text}")

        res = self.tracer.read_line_thread(input_text)
        buffer.set_text(f"Analisi del traceback:\n{res}")


    def on_build(self, button):
        self.on_reset_clicked(button)

        if self.is_building:
            return

        self.is_building = True

        if self.serial_conn is not None:
            self.on_connect_clicked(button)
        def output(text, type):
            try:
                #text = cont.decode()
                #self.main_thread_queue.put(("append_terminal", text+'\n'))
                self.append_terminal(text+"\n")
            except:
                print("undecoded process input")

        def completion(res):
            try:
                print("on_build completion: ", res)
                if res == 0:
                    self.on_connect_clicked(button)
                else:
                    print("execute_script completion: ", res)

                self.is_building = False
            except:
                pass

        self.self.stream_handler.clear()
        self.execute_script(self.project_path+'/build.sh', output_callback=output, completion_callback=completion)


    def on_files_toggle(self, button):
        """Gestisce il toggle del pannello file"""
        if button.get_active():
            self.main_paned.get_child2().show()
            if self.serial_conn:
                self.refresh_file_list()
        else:
            self.main_paned.get_child2().hide()

    def thread_execute_command(self, command):
        try:
            success, response = execute_command(self, command)
            if success:
                self.main_thread_queue.put(("append_terminal", f"Comando eseguito: {command}\nRisposta: {response}\n"))
            else:
                self.main_thread_queue.put(("append_terminal", f"Errore nell'esecuzione del comando: {response}\n"))
        except Exception as e:
            self.append_terminal(f"Execute command error: {str(e)}\n")
            if __debug__:
                # raise e
                pass
            print("thread_execute_command: ", e)
            raise e

    def on_execute_clicked(self, button):
        command = self.cmd_entry.get_text()

        if command:
            self.terminal_handler.scrollDown = True

        if command == "clear":
            self.on_reset_clicked(button)
            self.cmd_entry.set_text("")
            return

        if command:
            self.cmd_entry.set_text("")
            threading.Thread(target=self.thread_execute_command, args=(command,)).start()

    def refresh_file_list(self):
        """Aggiorna la lista dei file sul device"""
        if not self.serial_conn:
            self.show_status("Nessuna connessione seriale")
            return

        try:
            files = list_files(self)
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
            cmd_end(self)
            self.show_status(f"Errore: {str(e)}")
            self.append_terminal(f"Errore lettura file: {str(e)}\n")

    def on_refresh_files(self, button):
        """Handler refresh lista file"""
        self.refresh_file_list()


    def upload_file(self, base_name, data):
        try:
            success, msg = write_file(self, base_name, data)
            if success:
                self.show_status(f"File {base_name} caricato con successo")
                self.append_terminal(f"File caricato: {base_name}\n")
                self.refresh_file_list()
            else:
                self.show_status(f"Errore upload: {msg}")
                self.append_terminal(f"Errore upload: {msg}\n")
        except:
            pass

    def on_upload_file(self, button):
        """Handler upload file"""
        if not self.serial_conn:
            self.show_status("Nessuna connessione seriale")
            return

        dialog = SmartFileChooserDialog(
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
                    threading.Thread(target=self.upload_file, args=(base_name, data,)).start()

            except Exception as e:
                self.show_status(f"Errore: {str(e)}")
                self.append_terminal(f"Errore upload: {str(e)}\n")

        dialog.destroy()

    def on_download_file(self, button):
        """Handler download file"""

        self.append_terminal("\033[93mDownload file not implemented\033[0m")
        return

        selection = self.files_view.get_selection()
        model, treeiter = selection.get_selected()
        if not treeiter:
            self.show_status("Nessun file selezionato")
            return

        if not self.serial_conn:
            self.show_status("Nessuna connessione seriale")
            return

        filename = model[treeiter][0]

        dialog = SmartFileChooserDialog(
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
                data = read_file(self, filename)
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
                success, msg = delete_file(self, filename)
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
            # Imposta l'ultima porta come default invece della prima
            self.port_combo.set_active(len(ports) - 1)

    def on_refresh_clicked(self, button):
        self.refresh_ports()

    ####
    ####
    ####

    def espressif_path(self):
        """
        Ottiene il percorso della cartella .espressif.
        Su sistemi Unix (Linux/macOS) sarà nella home directory dell'utente.
        Su Windows sarà in %USERPROFILE%\.espressif

        Returns:
            Path: Il percorso completo alla cartella .espressif
        """
        if self._espressif_path is None:
            if os.name == 'nt':  # Windows
                base_path = os.getenv('USERPROFILE', '')
            else:  # Unix-like (Linux, macOS)
                base_path = os.path.expanduser('~')

            self._espressif_path = Path(base_path) / '.espressif'

            # Crea la directory se non esiste
            if not self._espressif_path.exists():
                return None;

        return str(self._espressif_path)

    #####
    #####
    #####

    def execute_script(self, script_path: str, output_callback: callable = None,
                       completion_callback: callable = None, shell: bool = True) -> subprocess.Popen:
        """
        Esegue uno script shell con supporto per output colorato e formattato in modo asincrono.
        Include flush periodico degli stream.
        """
        import signal
        import os
        import stat
        import subprocess
        from threading import Thread, Event
        import time
        import sys
        import locale

        print("execute_script called")

        script_path = os.path.abspath(script_path)
        script_dir = os.path.dirname(script_path)

        # Verifica esistenza script e imposta permessi
        if not os.path.exists(script_path):
            raise FileNotFoundError(f"Lo script {script_path} non esiste")

        if os.name != 'nt':
            current_mode = os.stat(script_path).st_mode
            os.chmod(script_path, current_mode | stat.S_IXUSR)

        env = os.environ.copy()
        env.update({
            'PYTHONUNBUFFERED': '1',
            'TERM': 'xterm-256color',
            'FORCE_COLOR': '1',
            'CLICOLOR': '1',
            'CLICOLOR_FORCE': '1',
            'COLORTERM': 'truecolor',
            'LANG': 'en_US.UTF-8',
            'LC_ALL': 'en_US.UTF-8',
            'PYTHONIOENCODING': 'UTF-8'
        })

        if os.name == 'nt':
            import ctypes
            kernel32 = ctypes.windll.kernel32
            kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)

        # Rimuoviamo il pipe con perl poiché potrebbe interferire con i codici ANSI
        cmd = script_path

        use_text = False
        if check_program_availability("screen") and False:
            cmd = 'screen bash -c "' + cmd + '; exec bash"'
            use_text = True

        stop_event = Event()

        try:
            process = subprocess.Popen(
                cmd,
                shell=shell,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=use_text,
                bufsize=1,  # Line buffering
                env=env,
                start_new_session=True,
                cwd=script_dir
            )

            def flush_streams():
                """Thread dedicato al flush periodico degli stream"""
                try:
                    while not stop_event.is_set():
                        try:
                            if process.stdout:
                                process.stdout.flush()
                            if process.stderr:
                                process.stderr.flush()
                        except:
                            print("flush_streams exception")
                        time.sleep(1)  # Flush ogni secondo

                    print("flush_streams ended")
                except:
                    print("flush_streams blocked")

            def handle_output(pipe, output_type):
                while not stop_event.is_set():  # Aggiungi controllo dell'evento
                    try:
                        if use_text:
                            output = pipe.readline()
                            if output:
                                print("handle_output text: ", output)
                                output_callback(output.rstrip('\n\r'), output_type)
                        else:
                            raw_line = pipe.readline()
                            print("handle_output: ", raw_line)
                            if not raw_line:
                                break
                            if output_callback:
                                line = raw_line.decode('utf-8', errors='replace')
                                output_callback(line.rstrip('\n\r'), output_type)
                    except Exception as e:
                        if output_callback and not process.poll():
                            output_callback(f"Errore I/O: {str(e)}", 'stderr')

            def monitor_completion():
                try:
                    exit_code = process.wait()
                    stop_event.set()  # Ferma i thread

                    # Attendi che i thread terminino
                    for thread in threads:
                        try:
                            thread.join() #timeout=1.0
                        except:
                            print("thread.join exception")

                    print("completion")

                    if completion_callback:
                        completion_callback(exit_code)
                except Exception as e:
                    if output_callback:
                        output_callback(f"Errore nel monitoraggio: {str(e)}", 'stderr')
                        completion_callback(-1)

            # Avvia i thread includendo quello per il flush
            threads = [
                Thread(target=handle_output, args=(process.stdout, 'stdout'), daemon=True),
                Thread(target=handle_output, args=(process.stderr, 'stderr'), daemon=True),
                Thread(target=monitor_completion, daemon=True),
                Thread(target=flush_streams, daemon=True)
            ]

            for thread in threads:
                thread.start()

            return process

        except Exception as e:
            if output_callback:
                output_callback(f"Errore nell'avvio del processo: {str(e)}", 'stderr')
                stop_event.set()
                completion_callback(-1)
            raise


    ####
    ####
    ####

    def init_tracing(self):
        self.tracer = ESP32BacktraceParser(serial=self.serial_conn)

        self.tracer.serialInterface = self
        self.tracer.set_debug_files(
            addr2line_path= self.espressif_path() + "/tools/xtensa-esp-elf/esp-13.2.0_20240530/xtensa-esp-elf/bin/xtensa-esp32-elf-addr2line", # find $HOME/.espressif -name "xtensa-esp32-elf-addr2line"
            elf_file= self.project_path + "/build/hello-idf.elf"
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
            #send_buffer(self.serial_conn, "$$$RESET$$$".encode("utf8"))

            # Toglie DTR
            self.serial_conn.setDTR(False)
            time.sleep(0.1)
            # Imposta DTR
            self.serial_conn.setDTR(True)

    def on_connect_clicked(self, button):
        if self.serial_conn is None:
            try:
                port = self.port_combo.get_active_text()
                if port:
                    baudrate = 115200
                    baudrate = 230400

                    self.serial_conn = serial.Serial(port, baudrate, timeout=0)
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

        #self.stream_handler.clear()
        self.init_receiver()

    def read_serial(self):
        global wfr_thisLine

        if self.serial_conn and self.serial_conn.is_open:
            def send(text):
                if not contains_alphanumeric(text):
                    return

                if text:
                    if not self.redirect_serial:
                        self.append_terminal(text)
                        self.last_serial_output = text.encode()
                    else:
                        if self.last_serial_output is None:
                            self.last_serial_output = text.encode()
                        else:
                            self.last_serial_output.extend(text.encode())

            try:
                while self.serial_conn.in_waiting:
                    if self.block_serial:
                        time.sleep(0.1)
                        continue
                    else:
                        if len(wfr_thisLine) > 0:
                            for line in wfr_thisLine.split('\n'):
                                self.append_terminal(line)
                            wfr_thisLine = ''

                    text = self.serial_conn.read(self.serial_conn.in_waiting).decode('utf-8', errors='replace')
                    send(text)

            except serial.SerialException as e:
                self.append_terminal(f"Errore di lettura: {str(e)}\n")
                self.serial_conn.close()
                self.serial_conn = None
                self.connect_button.set_label("Connetti")
                return False
            except Exception as e:
                print("read_serial Exception")
                #self.append_terminal(self.buffer)
                #raise e

            return True
        return False

    def append_terminal(self, text):
        self.stream_handler.process_string(text)


def main():
    win = SerialInterface()
    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    Gtk.main()

if __name__ == "__main__":
    main()