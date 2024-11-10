import gi

gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib
import serial
import serial.tools.list_ports

from transfer_file import *

class SerialInterface(Gtk.Window):
    def __init__(self):
        super().__init__(title="Interfaccia Seriale")
        self.set_border_width(10)
        self.set_default_size(600, 400)

        # Variabile per la connessione seriale
        self.serial_conn = None

        # Layout principale
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.add(vbox)

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

        # Area terminale
        scrolled_window = Gtk.ScrolledWindow()
        scrolled_window.set_hexpand(True)
        scrolled_window.set_vexpand(True)
        vbox.pack_start(scrolled_window, True, True, 0)

        self.terminal = Gtk.TextView()
        self.terminal.set_editable(False)
        self.terminal.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.terminal_buffer = self.terminal.get_buffer()
        scrolled_window.add(self.terminal)

        # Area input
        input_box = Gtk.Box(spacing=6)
        vbox.pack_start(input_box, False, False, 0)

        self.input_entry = Gtk.Entry()
        input_box.pack_start(self.input_entry, True, True, 0)

        send_button = Gtk.Button(label="Invia")
        send_button.connect("clicked", self.on_send_clicked)
        input_box.pack_start(send_button, False, False, 0)

    def refresh_ports(self):
        self.port_combo.remove_all()
        ports = serial.tools.list_ports.comports()
        for port in ports:
            self.port_combo.append_text(port.device)
        if ports:
            self.port_combo.set_active(0)

    def on_refresh_clicked(self, button):
        self.refresh_ports()

    def on_connect_clicked(self, button):
        if self.serial_conn is None:
            try:
                port = self.port_combo.get_active_text()
                if port:
                    self.serial_conn = serial.Serial(port, 115200, timeout=0)
                    self.connect_button.set_label("Disconnetti")
                    self.append_terminal("Connesso a " + port + "\n")
                    GLib.timeout_add(100, self.read_serial)
            except serial.SerialException as e:
                self.append_terminal(f"Errore di connessione: {str(e)}\n")
                self.serial_conn = None
        else:
            self.serial_conn.close()
            self.serial_conn = None
            self.connect_button.set_label("Connetti")
            self.append_terminal("Disconnesso\n")

    def on_send_clicked(self, button):
        if self.serial_conn and self.serial_conn.is_open:
            text = self.input_entry.get_text()
            if text:
                try:
                    self.serial_conn.write(text.encode())
                    self.append_terminal(f"Inviato: {text}\n")
                    self.input_entry.set_text("")
                except serial.SerialException as e:
                    self.append_terminal(f"Errore di invio: {str(e)}\n")

    def read_serial(self):
        if self.serial_conn and self.serial_conn.is_open:
            try:
                if self.serial_conn.in_waiting:
                    data = self.serial_conn.read(self.serial_conn.in_waiting)
                    self.append_terminal(f"Ricevuto: {data.decode()}\n")
            except serial.SerialException as e:
                self.append_terminal(f"Errore di lettura: {str(e)}\n")
                self.serial_conn.close()
                self.serial_conn = None
                self.connect_button.set_label("Connetti")
                return False
            return True
        return False

    def append_terminal(self, text):
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