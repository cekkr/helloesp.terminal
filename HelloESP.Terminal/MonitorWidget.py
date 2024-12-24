from gi.overrides.Gtk import Gtk

from TerminalHandler import TerminalHandler


class MonitorWidget:
    def __init__(self, parent_window):
        # Main container
        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)

        self.use_terminal = True

        if self.use_terminal:
            # Create the monitor view
            self.terminal_handler = TerminalHandler()
            self.terminal_handler.do_scroll_down = False
            self.terminal_box = self.terminal_handler.get_widget()
            self.monitor_view = self.terminal_handler.terminal

            self.buffer = self.terminal_handler.terminal_buffer
        else:
            self.monitor_view = Gtk.TextView()
            self.monitor_view.set_editable(False)
            self.monitor_view.set_cursor_visible(False)

            # Set up scrolled window for the monitor
            self.scrolled_window = Gtk.ScrolledWindow()
            self.scrolled_window.set_size_request(300, 200)  # Width and height
            self.scrolled_window.add(self.monitor_view)

        # Add custom styling
        css_provider = Gtk.CssProvider()
        css = b"""
        textview {
            font-family: monospace;
            color: #00ff00;
            background-color: #1a1a1a;
        }
        textview text {
            color: #00ff00;
            background-color: #1a1a1a;
        }
        """
        css_provider.load_from_data(css)

        # Apply the CSS styling
        style_context = self.monitor_view.get_style_context()
        style_context.add_provider(css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        if self.use_terminal:
            self.box.pack_start(self.terminal_handler.get_widget(), True, True, 0)
        else:
            # Create the buffer for text
            self.buffer = self.monitor_view.get_buffer()
            self.buffer.set_text("Tasks monitor\n")

            # Add to box
            self.box.pack_start(self.scrolled_window, True, True, 0)

        # Toggle button setup
        self.toggle_button = Gtk.ToggleButton(label="Monitor")
        self.toggle_button.connect("toggled", self.on_toggle_clicked)

        # Get reference to the file manager box
        self.file_box = parent_window.main_paned.get_child2()

        # Add our monitor to the existing file_box
        if self.file_box:
            self.file_box.pack_start(self.box, True, True, 0)
            self.box.hide()  # Initially hidden

        self.current_state = ""
        self.save_to_current_state = True

    def on_toggle_clicked(self, button):
        """Handle toggle button clicks"""
        if button.get_active():
            self.box.show_all()
        else:
            self.box.hide()

    def update_monitor(self, text):
        """Update the monitor text"""
        if self.terminal_handler:

            # Salva la posizione dello scroll corrente
            textview = self.terminal_handler.terminal
            vadj = textview.get_vadjustment()
            scroll_pos = vadj.get_value()

            # Memorizza la posizione del cursore
            buffer = self.terminal_handler.terminal_buffer
            cursor_mark = buffer.get_insert()
            cursor_iter = buffer.get_iter_at_mark(cursor_mark)
            cursor_offset = cursor_iter.get_offset()

            ####
            self.terminal_handler.append_terminal(text + "\n")
            ####

            # Ripristina la posizione del cursore se possibile
            try:
                new_cursor_iter = buffer.get_iter_at_offset(cursor_offset)
                buffer.place_cursor(new_cursor_iter)
            except:
                # Se l'offset non è più valido, non fare nulla
                pass

            # Assicurati che l'interfaccia sia aggiornata
            while Gtk.events_pending():
                Gtk.main_iteration()

            # Ripristina la posizione dello scroll
            vadj.set_value(scroll_pos)

            # Forza l'aggiornamento della vista
            textview.queue_draw()
        else:
            end_iter = self.buffer.get_end_iter()
            self.buffer.insert(end_iter, text + "\n")
            # Scroll to the bottom
            mark = self.buffer.create_mark(None, end_iter, False)
            self.monitor_view.scroll_to_mark(mark, 0.0, True, 0.0, 1.0)

    def end_append(self):
        if self.current_state:
            self.clear()
            self.update_monitor(self.current_state)
            self.current_state = ''

    def append_text(self, text):
        """Append text to the monitor"""

        if '!!clear!!' in text:
            if not self.save_to_current_state:
                self.clear()
            text = text.replace('!!clear!!', '')

        if '!!end!!' in text:
            self.end_append()
            text = text.replace('!!end!!', '')

        if not text:
            return

        if self.save_to_current_state:
            self.current_state += text + '\n'
            return

        self.update_monitor(text)

    def clear(self):
        """Clear all text from the monitor"""
        self.buffer.set_text("")

    def get_toggle_button(self):
        """Return the toggle button to be placed in the controls"""
        return self.toggle_button

