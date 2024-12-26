import json
import stat
import subprocess
import threading
from datetime import time
from pathlib import Path

import gi

from MonitorWidget import MonitorWidget
from StreamHandler import StreamHandler
from transfer_file import *

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

from new_transfer_files import *
from ESP32Tracing import *
from generalFunctions import *
from TerminalHandler import *


class SerialInterface(Gtk.Window):
    def __init__(self):
        self.buffer = ""
        self.esp_path = os.getenv('IDF_PATH')

        self.project_path = None #"/Users/riccardo/Sources/GitHub/hello.esp32/hello-idf"

        self.files = SerialCommandHandler(self)

        self._espressif_path = None

        self.main_thread_queue = Queue()

        self.is_building = False
        self.backtrace_loaded = False

        self.block_serial = False
        self.redirect_serial = False
        self.last_serial_output = None

        self.init_receiver()

        super().__init__(title="HelloESP Monitor")
        self.set_border_width(10)
        self.set_default_size(1400, 1000)

        # Serial connection variable
        self.serial_conn = None
        self.tracer = None

        # Main layout with expandable panel
        self.main_paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        self.add(self.main_paned)

        # Main container for terminal and controls
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.main_paned.pack1(vbox, True, False)  # resize=True, shrink=False

        # Upper area for controls
        controls_box = Gtk.Box(spacing=6)
        vbox.pack_start(controls_box, False, False, 0)

        # Combo box for serial ports
        self.port_combo = Gtk.ComboBoxText()
        self.refresh_ports()
        controls_box.pack_start(self.port_combo, True, True, 0)

        # Refresh ports button
        refresh_button = Gtk.Button(label="Refresh Ports")
        refresh_button.connect("clicked", self.on_refresh_clicked)
        controls_box.pack_start(refresh_button, False, False, 0)

        # Connect/disconnect button
        self.connect_button = Gtk.Button(label="Connect")
        self.connect_button.connect("clicked", self.on_connect_clicked)
        controls_box.pack_start(self.connect_button, False, False, 0)

        # Project path selection button
        self.project_path_button = Gtk.Button(label="Select Project Path")
        self.project_path_button.connect("clicked", self.on_project_path_clicked)
        controls_box.pack_start(self.project_path_button, False, False, 0)

        # Update button tooltip with current path
        self._update_project_path_tooltip()

        # File panel toggle
        self.files_toggle = Gtk.ToggleButton(label="File Manager")
        self.files_toggle.connect("toggled", self.on_files_toggle)
        controls_box.pack_start(self.files_toggle, False, False, 0)

        self.dev_restart_button = Gtk.Button(label="Restart Device")
        self.dev_restart_button.connect("clicked", self.on_dev_reset_clicked)
        controls_box.pack_start(self.dev_restart_button, False, False, 0)

        # Terminal area
        self.terminal_handler = TerminalHandler()
        terminal_box = self.terminal_handler.get_widget()
        self.add(terminal_box)
        self.terminal = self.terminal_handler.terminal
        vbox.pack_start(terminal_box, True, True, 0)

        self.terminal_handler.add_save_button()

        # Input area
        input_box = Gtk.Box(spacing=6)
        vbox.pack_start(input_box, False, False, 0)

        self.input_entry = Gtk.Entry()
        self.input_entry.connect("activate", self.on_send_clicked)
        input_box.pack_start(self.input_entry, True, True, 0)

        send_button = Gtk.Button(label="Send")
        send_button.connect("clicked", self.on_send_clicked)
        input_box.pack_start(send_button, False, False, 0)

        reset_button = Gtk.Button(label="Clear")
        reset_button.connect("clicked", self.on_reset_clicked)
        input_box.pack_start(reset_button, False, False, 0)

        # Commands area
        cmd_box = Gtk.Box(spacing=6)
        vbox.pack_start(cmd_box, False, False, 0)

        # Label to distinguish command area
        cmd_label = Gtk.Label(label="Commands:")
        cmd_box.pack_start(cmd_label, False, False, 5)

        self.cmd_entry = Gtk.Entry()
        self.cmd_entry.connect("activate", self.on_execute_clicked)
        self.cmd_entry.set_placeholder_text("Enter command...")  # Placeholder text
        cmd_box.pack_start(self.cmd_entry, True, True, 0)

        execute_button = Gtk.Button(label="Execute")
        execute_button.connect("clicked", self.on_execute_clicked)
        cmd_box.pack_start(execute_button, False, False, 0)

        # File Manager Panel
        self.setup_file_manager()
        self.setup_backtrace_zone(vbox)

        # Monitor widget
        self.monitor_widget = MonitorWidget(self)
        controls_box.pack_start(self.monitor_widget.get_toggle_button(), False, False, 0)

        # Monitor test
        self.monitor_widget.append_text("Tasks monitor")

        self._load_project_path()

        GLib.timeout_add(50, self.check_main_thread_queue)

    def setup_backtrace_zone(self, parent_box=None):
        if parent_box is not None:
            self.backtrace_parent_box = parent_box
            self.TRACEBACK_AREA_HEIGHT = 300

        if self.backtrace_loaded:
            return

        # Create toggle button
        self.backtrace_toggle_button = Gtk.ToggleButton(label="Show Traceback")
        self.backtrace_toggle_button.connect("toggled", self.backtrace_on_toggle_button_clicked)
        self.backtrace_parent_box.pack_start(self.backtrace_toggle_button, False, False, 0)

        # Create container for traceback area
        self.traceback_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)

        # Horizontal box for textbox and Check button
        self.backtrace_input_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

        # Entry for traceback input
        self.backtrace_entry = Gtk.Entry()
        self.backtrace_input_box.pack_start(self.backtrace_entry, True, True, 0)

        # Check button
        self.backtrace_check_button = Gtk.Button(label="Check traceback")
        self.backtrace_check_button.connect("clicked", self.backtrace_on_check_clicked)
        self.backtrace_input_box.pack_start(self.backtrace_check_button, False, False, 0)

        self.traceback_box.pack_start(self.backtrace_input_box, False, False, 0)

        # TextView per i risultati
        scrolled_window = Gtk.ScrolledWindow()
        scrolled_window.set_size_request(-1, self.TRACEBACK_AREA_HEIGHT)

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
            # self.backtrace_on_toggle_button_clicked(self.backtrace_toggle_button)

        # Crea e avvia il thread per l'attesa di 2 secondi
        thread_attesa = threading.Thread(target=hide_it)
        thread_attesa.start()

        self.backtrace_loaded = True

    def setup_file_manager(self):
        """Setup of the file management panel"""
        file_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.main_paned.pack2(file_box, False, False)  # resize=False, shrink=False

        # Compile zone
        compile_button_box = Gtk.Box(spacing=6)
        file_box.pack_start(compile_button_box, False, False, 0)

        btn_build = Gtk.Button(label="Build")
        btn_build.connect("clicked", self.on_build)
        compile_button_box.pack_start(btn_build, True, True, 0)

        # Header label
        header = Gtk.Label(label="File Manager")
        header.set_markup("<b>File Manager</b>")
        file_box.pack_start(header, False, False, 5)

        # Action buttons
        button_box = Gtk.Box(spacing=6)
        file_box.pack_start(button_box, False, False, 0)

        refresh_files_btn = Gtk.Button(label="Refresh")
        refresh_files_btn.connect("clicked", self.on_refresh_files)
        button_box.pack_start(refresh_files_btn, True, True, 0)

        upload_btn = Gtk.Button(label="Upload")
        upload_btn.connect("clicked", self.on_upload_file)
        button_box.pack_start(upload_btn, True, True, 0)

        download_btn = Gtk.Button(label="Download")
        download_btn.connect("clicked", self.on_download_file)
        button_box.pack_start(download_btn, True, True, 0)

        delete_btn = Gtk.Button(label="Delete")
        delete_btn.connect("clicked", self.on_delete_file)
        button_box.pack_start(delete_btn, True, True, 0)

        # File list on device
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        file_box.pack_start(scrolled, True, True, 0)

        # Store for file list: name, size, modification date
        self.files_store = Gtk.ListStore(str, str, str)

        self.files_view = Gtk.TreeView(model=self.files_store)
        self.files_view.set_headers_visible(True)

        # Columns
        renderer = Gtk.CellRendererText()
        column = Gtk.TreeViewColumn("Name", renderer, text=0)
        column.set_resizable(True)
        column.set_min_width(150)
        self.files_view.append_column(column)

        renderer = Gtk.CellRendererText()
        column = Gtk.TreeViewColumn("Size", renderer, text=1)
        self.files_view.append_column(column)

        renderer = Gtk.CellRendererText()
        column = Gtk.TreeViewColumn("Date", renderer, text=2)
        self.files_view.append_column(column)

        scrolled.add(self.files_view)

        # Operations status area
        self.status_bar = Gtk.Statusbar()
        file_box.pack_start(self.status_bar, False, False, 0)

        ###
        ###
        ###

    def check_main_thread_queue(self):
        try:
            while not self.main_thread_queue.empty():
                msg_type, value = self.main_thread_queue.get()

                if msg_type in ["terminal_append", "append_terminal"]:  # don't you worry about the dislexy
                    self.terminal_handler.append_terminal(value)

                    if self.tracer is not None:
                        self.tracer.read_line(value)
                elif msg_type == "self.append_terminal_notrace":
                    self.append_terminal_notrace(value)
                elif msg_type == "terminal_append_notrace":
                    self.terminal_handler.append_terminal(value)
                elif msg_type == "self.append_terminal":
                    self.append_terminal(value)
                elif msg_type == "monitor_append":
                    self.monitor_widget.append_text(value)
                elif msg_type == "self.on_connect_clicked":
                    self.on_connect_clicked(None)
                else:
                    print("msg_type not found: ", msg_type)

        except Exception as e:
            print("check_main_thread_queue: ", str(e))

        return True

    def init_receiver(self):
        def on_received_normal(text):
            self.main_thread_queue.put(("terminal_append_notrace", text))

        def on_received_monitor(text):
            self.main_thread_queue.put(("monitor_append", text))

        self.stream_handler = StreamHandler(on_received_normal)
        self.stream_handler.add_context("!!TASKMONITOR!!", "!!TASKMONITOREND!!", on_received_monitor)


    ###
    ### Project path
    ###

    def _check_project_path(self):
        if self.project_path is None:
            self.on_project_path_clicked(None)

    def check_project_path_dialog(self):
        if self.project_path is not None:
            return True

        """Show a dialog asking user to set the project path."""
        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.OK_CANCEL,
            text="Project path needed",
        )
        dialog.format_secondary_text("Project path not selected, do you want to set it?")

        response = dialog.run()
        dialog.destroy()

        if response == Gtk.ResponseType.OK:
            self.on_project_path_clicked(None)
            if self.project_path is not None:
                return True

        return False

    def _load_project_path(self):
        """Load the saved project path from configuration."""
        config_file = os.path.join(str(Path.home()), '.gtk_smart_dialog_paths.json')
        try:
            if os.path.exists(config_file):
                with open(config_file, 'r') as f:
                    paths = json.load(f)
                    self.project_path = paths.get('project_path')
        except Exception as e:
            print(f"Error loading project path: {e}")

    def _save_project_path(self):
        """Save the current project path to configuration."""
        config_file = os.path.join(str(Path.home()), '.gtk_smart_dialog_paths.json')
        try:
            # Load existing paths or create new dict
            paths = {}
            if os.path.exists(config_file):
                with open(config_file, 'r') as f:
                    paths = json.load(f)

            # Update project path
            paths['project_path'] = self.project_path

            # Save updated configuration
            with open(config_file, 'w') as f:
                json.dump(paths, f, indent=2)
        except Exception as e:
            print(f"Error saving project path: {e}")

    def _update_project_path_tooltip(self):
        """Update the project path button tooltip with current path."""
        tooltip = f"Current project path: {self.project_path or 'Not set'}"

        if self.project_path is not None:
            self.init_tracing()

        self.project_path_button.set_tooltip_text(tooltip)

    def on_project_path_clicked(self, button):
        """Handle project path selection button click."""
        dialog = SmartFileChooserDialog(
            title="Select Project Path",
            parent=self,
            action=Gtk.FileChooserAction.SELECT_FOLDER,
            buttons=("Cancel", Gtk.ResponseType.CANCEL, "Select", Gtk.ResponseType.OK)
        )

        # Set current project path if exists
        if self.project_path and os.path.exists(self.project_path):
            dialog.set_current_folder(self.project_path)

        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            self.project_path = dialog.get_filename()

            if not self.project_path.endswith('hello-idf') and not self.project_path.endswith('hello-idf/'):
                if not self.project_path.endswith('/'):
                    self.project_path += '/'
                self.project_path += 'hello-idf'

            self._save_project_path()
            self._update_project_path_tooltip()

        dialog.destroy()

    ###
    ###
    ###

    def backtrace_on_toggle_button_clicked(self, button):
        if not self.check_project_path_dialog():
            return

        if button.get_active():
            self.traceback_box.show_all()
            button.set_label("Hide Traceback")
        else:
            self.traceback_box.hide()
            button.set_label("Show Traceback")

    def backtrace_on_check_clicked(self, button):
        # Qui puoi implementare la logica per processare il traceback
        input_text = self.backtrace_entry.get_text()
        buffer = self.backtrace_textview.get_buffer()
        input_text = input_text.replace('\\n', '\n')
        buffer.set_text(f"Traceback analysis:\n{input_text}")

        res = self.tracer.read_line_thread(input_text)
        buffer.set_text(f"Traceback analysis:\n{res}")


    def on_build(self, button):
        if not self.check_project_path_dialog():
            return

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
                    self.main_thread_queue.put(("self.on_connect_clicked", None))
                else:
                    print("execute_script completion: ", res)

                self.is_building = False
            except:
                pass

        #self.self.stream_handler.clear()
        self.on_reset_clicked(None)
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
            success, response = self.files.execute_command(command)
            if success:
                self.main_thread_queue.put(("append_terminal", f"Command successful ({command}): {response}\n"))
            else:
                self.main_thread_queue.put(("append_terminal", f"Command error ({command}): {response}\n"))
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
            self.show_status("No serial connection")
            return

        try:
            files = self.files.list_files()
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
            self.show_status(f"Found {len(files)} files")
        except SerialCommandError as e:
            self.show_status(f"Error: {str(e)}")
            self.append_terminal(f"Error while reading files: {str(e)}\n")
            self.files.cmd_end()

    def on_refresh_files(self, button):
        """Handler refresh lista file"""
        self.refresh_file_list()


    def upload_file(self, base_name, data):
        try:
            success, msg = self.files.write_file(base_name, data)
            if success:
                self.show_status(f"File {base_name} successfully loaded")
                self.append_terminal(f"File loaded: {base_name}\n")
                self.refresh_file_list()
            else:
                self.show_status(f"Error upload: {msg}")
                self.append_terminal(f"Error upload: {msg}\n")
        except:
            pass

    def on_upload_file(self, button):
        """Handler upload file"""
        if not self.serial_conn:
            self.show_status("No serial connection")
            return

        dialog = SmartFileChooserDialog(
            title="Select the file to load",
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
                self.show_status(f"Error: {str(e)}")
                self.append_terminal(f"Error upload: {str(e)}\n")

        dialog.destroy()

    def on_download_file(self, button):
        """Handler download file"""

        self.append_terminal("\033[93mDownload file not implemented\033[0m")
        return

        selection = self.files_view.get_selection()
        model, treeiter = selection.get_selected()
        if not treeiter:
            self.show_status("No file selected")
            return

        if not self.serial_conn:
            self.show_status("No serial connection")
            return

        filename = model[treeiter][0]

        dialog = SmartFileChooserDialog(
            title="Save file",
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
                self.show_status(f"File {filename} succesfully downloaded")
                self.append_terminal(f"File downloadedd: {filename}\n")
            except Exception as e:
                self.show_status(f"Error download: {str(e)}")
                self.append_terminal(f"Error download: {str(e)}\n")

        dialog.destroy()

    def on_delete_file(self, button):
        """Handler eliminazione file"""
        selection = self.files_view.get_selection()
        model, treeiter = selection.get_selected()
        if not treeiter:
            self.show_status("No file selected")
            return

        if not self.serial_conn:
            self.show_status("No serial connection")
            return

        filename = model[treeiter][0]

        dialog = Gtk.MessageDialog(
            parent=self,
            flags=0,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.OK_CANCEL,
            text=f"Delete file {filename}?"
        )
        dialog.format_secondary_text(
            "This operation can't be reverted"
        )

        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            try:
                success, msg = self.delete_file(filename)
                if success:
                    self.show_status(f"File {filename} deleted")
                    self.append_terminal(f"File deleted: {filename}\n")
                    self.refresh_file_list()
                else:
                    self.show_status(f"Delete error: {msg}")
                    self.append_terminal(f"Delete error: {msg}\n")
            except Exception as e:
                self.show_status(f"Error: {str(e)}")
                self.append_terminal(f"Delete error: {str(e)}\n")

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
        script_name = os.path.basename(script_path)

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
        else:
            cmd = './' + script_name

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

            def handle_output(pipe, output_type):
                """Modified handle_output with better pipe handling"""
                while not stop_event.is_set():
                    try:
                        if pipe.closed:
                            break

                        if use_text:
                            output = pipe.readline()
                            if not output:  # Empty string means EOF
                                break
                            output_callback(output.rstrip('\n\r'), output_type)
                        else:
                            raw_line = pipe.read1(8192)  # Read chunks instead of lines
                            if not raw_line:  # EOF
                                break
                            if output_callback:
                                line = raw_line.decode('utf-8', errors='replace')
                                output_callback(line, output_type)

                    except (IOError, OSError) as e:
                        if not process.poll():  # Only report if process is still running
                            output_callback(f"I/O Error: {str(e)}", 'stderr')
                        break

            def flush_streams():
                """Modified flush_streams with safety checks"""
                while not stop_event.is_set():
                    try:
                        if process.poll() is not None:  # Process ended
                            break

                        if process.stdout and not process.stdout.closed:
                            process.stdout.flush()
                        if process.stderr and not process.stderr.closed:
                            process.stderr.flush()
                    except (IOError, OSError):
                        break
                    time.sleep(1)

            def monitor_completion():
                try:
                    exit_code = process.wait()
                    stop_event.set()  # Ferma i thread

                    # Attendi che i thread terminino
                    for thread in threads:
                        try:
                            thread.join(timeout=1.0) #timeout=1.0
                        except:
                            print("thread.join exception")

                    print("completion")

                    time.sleep(2)

                    if completion_callback:
                        completion_callback(exit_code)
                except Exception as e:
                    if output_callback:
                        output_callback(f"Error during execute_script monitoring: {str(e)}", 'stderr')
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
                output_callback(f"Start process error: {str(e)}", 'stderr')
                stop_event.set()
                completion_callback(-1)
            raise


    ####
    ####
    ####

    def init_tracing(self):
        if self.project_path is None:
            return

        self.tracer = ESP32BacktraceParser(serial=self)

        self.tracer.serialInterface = self
        self.tracer.set_debug_files(
            addr2line_path= self.espressif_path() + "/tools/xtensa-esp-elf/esp-13.2.0_20240530/xtensa-esp-elf/bin/xtensa-esp32-elf-addr2line", # find $HOME/.espressif -name "xtensa-esp32-elf-addr2line"
            elf_file= self.project_path + "/build/hello-idf.elf"
        )

        #self.setup_backtrace_zone()


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
                    self.connect_button.set_label("Disconnect")
                    self.append_terminal("Connect to " + port + "\n")
                    if self.files_toggle.get_active():
                        self.refresh_file_list()
                    GLib.timeout_add(100, self.read_serial)

                    self.init_tracing()
            except serial.SerialException as e:
                self.append_terminal(f"Connection error: {str(e)}\n")
                self.serial_conn = None
        else:
            self.serial_conn.close()
            self.serial_conn = None
            self.connect_button.set_label("Connect")
            self.append_terminal("Disconnected\n")
            self.files_store.clear()
            self.stop_tracing()

    def on_send_clicked(self, button):
        if self.serial_conn and self.serial_conn.is_open:
            text = self.input_entry.get_text()
            if text:
                try:
                    data = (text + "\n").encode()
                    self.serial_conn.write(data)
                    self.append_terminal(f"Sent: {text}\n")
                    self.input_entry.set_text("")
                except serial.SerialException as e:
                    self.append_terminal(f"Send error: {str(e)}\n")

    def on_reset_clicked(self, button):
        buffer = self.terminal.get_buffer()
        buffer.set_text("")

        self.stream_handler.clear()
        self.init_receiver()

    def read_serial(self):

        if self.serial_conn and self.serial_conn.is_open:
            def send(text):
                if not contains_alphanumeric(text):
                    return

                if text:
                    if not self.redirect_serial:
                        self.main_thread_queue.put(('self.append_terminal', text))
                        self.last_serial_output = text.encode() # ?? why
                    else:
                        if self.last_serial_output is None:
                            self.last_serial_output = text.encode()
                        else:
                            self.last_serial_output += text.encode()

            try:
                while self.serial_conn.in_waiting:
                    if self.block_serial:
                        time.sleep(0.1)
                        continue
                    else:
                        if len(self.files.wfr_thisLine) > 0:
                            for line in self.files.wfr_thisLine.split('\n'):
                                send(line)
                            self.files.wfr_thisLine = ''

                    text = self.serial_conn.read(self.serial_conn.in_waiting).decode('utf-8', errors='replace')
                    send(text)

            except serial.SerialException as e:
                self.append_terminal(f"Reading error: {str(e)}\n")
                self.serial_conn.close()
                self.serial_conn = None
                self.connect_button.set_label("Connect")
                return False
            except Exception as e:
                print("read_serial exception: ", e)
                print("Exception type : ", type(e).__name__)
                traceback.print_exc(file=sys.stdout)
                #self.append_terminal(self.buffer)
                #raise e

            return True
        return False

    def append_terminal(self, text):
        #text += '\n'

        if self.tracer is not None:
            self.tracer.read_line(text)

        self.stream_handler.process_string(text)

    def append_terminal_notrace(self, text):
        #text += '\n'
        self.stream_handler.process_string(text)

def main():
    win = SerialInterface()
    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    Gtk.main()

if __name__ == "__main__":
    main()