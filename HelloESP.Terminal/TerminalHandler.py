import re
from array import array

from gi.repository import Gtk, Gdk, Pango
from gi.repository import GObject


class TerminalHandler:
    def __init__(self, max_lines=10000):
        # Terminal setup
        self.max_lines = max_lines  # Maximum number of lines to keep
        self.tag_table = Gtk.TextTagTable()
        self.terminal_buffer = Gtk.TextBuffer(tag_table=self.tag_table)
        self.terminal = Gtk.TextView(buffer=self.terminal_buffer)
        self.scrollDown = True

        # Terminal styling
        rgba = Gdk.RGBA()
        rgba.parse("#2E3436")
        self.terminal.override_background_color(Gtk.StateFlags.NORMAL, rgba)

        rgba_text = Gdk.RGBA()
        rgba_text.parse("#FFFFFF")
        self.terminal.override_color(Gtk.StateFlags.NORMAL, rgba_text)

        font = Pango.FontDescription()
        font.set_family("Monospace")
        font.set_weight(Pango.Weight.BOLD)
        font.set_size(12 * Pango.SCALE)
        self.terminal.override_font(font)

        ###
        ### Selection color
        ###
        # Creare un provider CSS
        css_provider = Gtk.CssProvider()
        css = """
                textview text selection {
                    background-color: #3584e4;
                    color: #ffffff;
                }
                """
        css_provider.load_from_data(css.encode())

        # Applicare lo stile
        context = self.terminal.get_style_context()
        context.add_provider(css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        ####
        ####

        # Terminal configuration
        self.terminal.set_wrap_mode(Gtk.WrapMode.CHAR)
        self.terminal.set_editable(False)

        # Create scrolled window
        self.scrolled_window = Gtk.ScrolledWindow()

        # Create a box inside the scrolled window
        self.terminal_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.scrolled_window.add(self.terminal_box)

        # Setup search first
        self.setup_search()

        # Add search and terminal to the box
        self.terminal_box.pack_start(self.search_box, False, False, 0)
        self.terminal_box.pack_start(self.terminal, True, True, 0)

        self.scrolled_window.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)

        # Keep reference to the adjustment
        self.vadj = self.scrolled_window.get_vadjustment()

        # Rest of the initialization
        self.pending_updates = []
        self.update_pending = False
        self.ansi_pattern = re.compile(r'(?:\\x1b|\x1b)\[([0-9;]*)m')

        # ANSI color definitions (standard colors)
        self.colors = {
            # Standard colors (30-37)
            '0': '#000000',  # Black
            '1': '#CD0000',  # Red
            '2': '#00CD00',  # Green
            '3': '#CDCD00',  # Yellow
            '4': '#0000EE',  # Blue
            '5': '#CD00CD',  # Magenta
            '6': '#00CDCD',  # Cyan
            '7': '#E5E5E5',  # White
            # Bright colors (90-97)
            '8': '#7F7F7F',  # Bright Black (Gray)
            '9': '#FF0000',  # Bright Red
            '10': '#00FF00',  # Bright Green
            '11': '#FFFF00',  # Bright Yellow
            '12': '#5C5CFF',  # Bright Blue
            '13': '#FF00FF',  # Bright Magenta
            '14': '#00FFFF',  # Bright Cyan
            '15': '#FFFFFF'  # Bright White
        }

        self._init_tags()

    def check_line_limit(self):
        """Check if the buffer exceeds the maximum line limit and remove oldest lines if necessary"""
        buffer = self.terminal_buffer
        line_count = buffer.get_line_count()

        if line_count > self.max_lines:
            # Calculate how many lines to remove
            lines_to_remove = line_count - self.max_lines

            # Get iterator for the start of the buffer
            start_iter = buffer.get_start_iter()

            # Get iterator for the end of the lines to remove
            end_iter = buffer.get_iter_at_line(lines_to_remove)

            # Delete the excess lines
            buffer.delete(start_iter, end_iter)

            # Return True if lines were removed
            return True
        return False

    def _process_updates(self):
        """Process pending text updates in the main loop"""
        if not self.pending_updates:
            self.update_pending = False
            return False

        try:
            while self.pending_updates:
                text, tags = self.pending_updates.pop(0)

                end_iter = self.terminal_buffer.get_end_iter()
                mark = self.terminal_buffer.create_mark(None, end_iter, left_gravity=True)

                self.terminal_buffer.insert(end_iter, text)

                if tags:
                    insert_iter = self.terminal_buffer.get_iter_at_mark(mark)
                    end_iter = self.terminal_buffer.get_end_iter()
                    for tag_name in tags:
                        tag = self.tag_table.lookup(tag_name)
                        if tag:
                            self.terminal_buffer.apply_tag(tag, insert_iter, end_iter)

                self.terminal_buffer.delete_mark(mark)

                # Check line limit after each update
                if self.check_line_limit():
                    #self.scrollDown = True
                    pass

            adj = self.vadj
            if adj and self.scrollDown:
                GObject.idle_add(
                    lambda: adj.set_value(adj.get_upper() - adj.get_page_size()),
                    priority=GObject.PRIORITY_LOW
                )

        except Exception as e:
            print(f"Error processing updates: {e}")

        self.update_pending = False
        return False

    def setup_search(self):
        # Search state
        self.search_highlights = []
        self.current_match_index = -1

        # Create search bar components
        self.search_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.search_box.set_margin_start(6)
        self.search_box.set_margin_end(6)
        self.search_box.set_margin_top(6)
        self.search_box.set_margin_bottom(6)

        # Create search entry
        self.search_entry = Gtk.SearchEntry()
        self.search_entry.set_width_chars(30)
        self.search_entry.connect('changed', self.on_search_changed)
        self.search_entry.connect('activate', self.on_search_next)

        # Create close button
        close_button = Gtk.Button.new_from_icon_name('window-close-symbolic', Gtk.IconSize.BUTTON)
        close_button.connect('clicked', self.hide_search)

        # Pack search components
        self.search_box.pack_start(self.search_entry, False, True, 0)
        self.search_box.pack_start(close_button, False, True, 0)
        self.search_box.hide()  # Hide by default

        # Create search tags
        self.search_tag = Gtk.TextTag.new('search-highlight')
        self.search_tag.set_property('background', '#FFE066')
        self.search_tag.set_property('foreground', '#000000')

        self.current_match_tag = Gtk.TextTag.new('current-match')
        self.current_match_tag.set_property('background', '#FF9933')
        self.current_match_tag.set_property('foreground', '#000000')

        self.tag_table.add(self.search_tag)
        self.tag_table.add(self.current_match_tag)

        # Setup keyboard shortcuts
        self.terminal.connect('key-press-event', self.on_key_press)

    def on_key_press(self, widget, event):
        if event.state & Gdk.ModifierType.CONTROL_MASK or event.state & Gdk.ModifierType.META_MASK:
            if event.keyval == Gdk.KEY_f:
                self.show_search()
                return True
        elif event.keyval == Gdk.KEY_Escape:
            self.hide_search()
            return True
        return False

    def show_search(self):
        self.search_box.show_all()
        self.search_entry.grab_focus()

    def hide_search(self, *args):
        self.search_box.hide()
        self.clear_highlights()
        self.terminal.grab_focus()

    def clear_highlights(self):
        buffer = self.terminal_buffer
        start = buffer.get_start_iter()
        end = buffer.get_end_iter()
        buffer.remove_tag(self.search_tag, start, end)
        buffer.remove_tag(self.current_match_tag, start, end)
        self.search_highlights = []
        self.current_match_index = -1

    def on_search_changed(self, entry):
        self.clear_highlights()
        search_text = entry.get_text()

        if not search_text:
            return

        buffer = self.terminal_buffer
        text = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), True)

        for match in re.finditer(re.escape(search_text), text, re.IGNORECASE):
            start_iter = buffer.get_iter_at_offset(match.start())
            end_iter = buffer.get_iter_at_offset(match.end())
            buffer.apply_tag(self.search_tag, start_iter, end_iter)
            self.search_highlights.append((start_iter.get_offset(), end_iter.get_offset()))

        if self.search_highlights:
            self.current_match_index = 0
            self.highlight_current_match()

    def highlight_current_match(self):
        if not self.search_highlights:
            return

        buffer = self.terminal_buffer
        start = buffer.get_start_iter()
        end = buffer.get_end_iter()
        buffer.remove_tag(self.current_match_tag, start, end)

        start_offset, end_offset = self.search_highlights[self.current_match_index]
        start_iter = buffer.get_iter_at_offset(start_offset)
        end_iter = buffer.get_iter_at_offset(end_offset)
        buffer.apply_tag(self.current_match_tag, start_iter, end_iter)

        self.terminal.scroll_to_iter(start_iter, 0.0, True, 0.0, 0.5)

    def on_search_next(self, *args):
        if not self.search_highlights:
            return
        self.current_match_index = (self.current_match_index + 1) % len(self.search_highlights)
        self.highlight_current_match()

    def get_widget(self):
        """Return the main container with search bar and terminal"""
        return self.scrolled_window

    def _init_tags(self):
        # Initialize basic style tags
        basic_styles = {
            'bold': {'weight': Pango.Weight.BOLD},
            'dim': {'weight': Pango.Weight.LIGHT},
            'italic': {'style': Pango.Style.ITALIC},
            'underline': {'underline': Pango.Underline.SINGLE},
            'blink': {'background': '#FFFFFF'},  # Simulate blink with background
            'reverse': {},  # Will be handled specially
            'hidden': {'foreground': '#FFFFFF', 'background': '#FFFFFF'},
            'strike': {'strikethrough': True}
        }

        for style_name, properties in basic_styles.items():
            tag = Gtk.TextTag.new(style_name)
            for prop, value in properties.items():
                tag.set_property(prop, value)
            self.tag_table.add(tag)

        # Initialize color tags
        for code, color in self.colors.items():
            # Foreground color tags (30-37, 90-97)
            fg_tag = Gtk.TextTag.new(f'fg_{code}')
            fg_tag.set_property('foreground', color)
            self.tag_table.add(fg_tag)

            # Background color tags (40-47, 100-107)
            bg_tag = Gtk.TextTag.new(f'bg_{code}')
            bg_tag.set_property('background', color)
            self.tag_table.add(bg_tag)

    def _parse_ansi_code(self, code):
        """Parse ANSI code and return corresponding tag names"""
        tags = set()

        # Handle simple cases first
        simple_mappings = {
            '0': set(),  # Reset
            '1': {'bold'},
            '2': {'dim'},
            '3': {'italic'},
            '4': {'underline'},
            '5': {'blink'},
            '7': {'reverse'},
            '8': {'hidden'},
            '9': {'strike'}
        }

        if code in simple_mappings:
            return simple_mappings[code]

        # Handle colors
        try:
            code_num = int(code)
            if 30 <= code_num <= 37:  # Standard foreground colors
                tags.add(f'fg_{code_num - 30}')
            elif 40 <= code_num <= 47:  # Standard background colors
                tags.add(f'bg_{code_num - 40}')
            elif 90 <= code_num <= 97:  # Bright foreground colors
                tags.add(f'fg_{code_num - 82}')  # Maps 90-97 to 8-15
            elif 100 <= code_num <= 107:  # Bright background colors
                tags.add(f'bg_{code_num - 92}')  # Maps 100-107 to 8-15
        except ValueError:
            pass

        return tags

    def _update_tags(self, codes, current_tags):
        if type(codes) is not list:
            codes = [codes]

        for code in codes:
            if code == '0':
                current_tags.clear()
            else:
                new_tags = self._parse_ansi_code(code)
                if new_tags:
                    # Remove conflicting tags before adding new ones
                    if any(tag.startswith('fg_') for tag in new_tags):
                        # Rimuove solo i tag fg_ esistenti
                        current_tags = {tag for tag in current_tags if not tag.startswith('fg_')}
                    if any(tag.startswith('bg_') for tag in new_tags):
                        # Rimuove solo i tag bg_ esistenti
                        current_tags = {tag for tag in current_tags if not tag.startswith('bg_')}
                    current_tags.update(new_tags)

        return current_tags

    def _schedule_update(self, text, tags):
        """Schedule a text update to be processed in the main loop"""
        self.pending_updates.append((text, tags))
        if not self.update_pending:
            self.update_pending = True
            GObject.idle_add(self._process_updates, priority=GObject.PRIORITY_LOW)

    def normalize_ansi(self, text):
        """
        Normalizza le sequenze ANSI nel testo, convertendo le versioni escaped
        nella forma corretta con \x1b.

        Args:
            text (str): Il testo contenente sequenze ANSI (escaped o non)

        Returns:
            str: Il testo con tutte le sequenze ANSI normalizzate
        """

        def replacer(match):
            # Estrae i codici numerici dal gruppo catturato
            codes = match.group(1)
            # Ricostruisce la sequenza ANSI nella forma corretta
            return f"\x1b[{codes}m"

        # Applica la sostituzione su tutto il testo
        return self.ansi_pattern.sub(replacer, text)

    def append_terminal(self, text):
        if not text:
            return

        adj = self.vadj
        current_pos = adj.get_value()
        # Calcola la differenza tra la posizione massima e quella corrente
        max_pos = adj.get_upper() - adj.get_page_size()
        distance_from_bottom = max_pos - current_pos

        if distance_from_bottom <= 30 or max_pos <= 0:
            self.scrollDown = True
        else:
            self.scrollDown = False

        try:
            text = self.normalize_ansi(text)
            text = self._sanitize_text(text)
            ansi_pattern = self.ansi_pattern  # re.compile(r'(?:\\x1b|\x1b)\[([0-9;]*)m')

            segments = []
            last_position = 0
            current_tags = set()

            def add_piece(up_to):
                segments.append((text[last_position:up_to], current_tags.copy()))

            for match in ansi_pattern.finditer(text):
                start, end = match.span()

                if last_position == 0 and start > 0:
                    add_piece(start)
                elif last_position > 0 and last_position != start:
                    add_piece(start)

                codes = match.group(1).split(';') if match.group(1) else ['0']
                current_tags = self._update_tags(codes, current_tags)
                last_position = end

            if last_position < len(text):
                add_piece(len(text))

            for content, tags in segments:
                self._schedule_update(content, tags)

        except Exception as e:
            print(f"Error in append_terminal: {e}")

    def _sanitize_text(self, text):
        """Sanitize text while preserving ANSI escape sequences"""
        if not isinstance(text, str):
            try:
                text = str(text)
            except:
                return ""

        text = self._handle_control_sequences(text)

        # Preserve ANSI escape sequences while cleaning other characters
        parts = []
        current_pos = 0
        for match in re.finditer(r'\x1b\[[0-9;]*m', text):
            start, end = match.span()
            # Clean the text between ANSI sequences
            clean_text = ''.join(
                char for char in text[current_pos:start]
                if char in '\n\t' or (ord(char) >= 32 and ord(char) <= 126) or ord(char) > 159
            )
            parts.append(clean_text)
            parts.append(text[start:end])  # Keep the ANSI sequence as-is
            current_pos = end

        # Clean the remaining text after the last ANSI sequence
        clean_text = ''.join(
            char for char in text[current_pos:]
            if char in '\n\t' or (ord(char) >= 32 and ord(char) <= 126) or ord(char) > 159
        )
        parts.append(clean_text)

        return ''.join(parts)

    def _handle_control_sequences(self, text):
        # Keep ANSI color/style sequences while handling other control chars
        control_chars = {
            '\x08': self._handle_backspace,
            '\r': self._handle_carriage_return,
            '\x1b[K': self._handle_clear_line,
            '\x1b[2K': self._handle_clear_entire_line,
            '\x1b[1K': self._handle_clear_to_start
        }

        result = []
        i = 0
        while i < len(text):
            handled = False
            for seq, handler in control_chars.items():
                if text[i:].startswith(seq):
                    handler(text, i)
                    i += len(seq)
                    handled = True
                    break

            if not handled:
                result.append(text[i])
                i += 1

        return ''.join(result)

    def _handle_backspace(self, text, pos):
        """Handle backspace character by removing previous character if it exists"""
        try:
            end_iter = self.terminal_buffer.get_end_iter()
            start_iter = end_iter.copy()
            if start_iter.backward_char():  # If there's a character to delete
                self.terminal_buffer.delete(start_iter, end_iter)
        except Exception as e:
            print(f"Error handling backspace: {e}")

    def _handle_carriage_return(self, text, pos):
        """Handle carriage return by moving to start of the current line"""
        try:
            end_iter = self.terminal_buffer.get_end_iter()
            line_start = end_iter.copy()
            line_start.backward_chars(end_iter.get_line_offset())
            # Delete from line start to current position
            self.terminal_buffer.delete(line_start, end_iter)
        except Exception as e:
            print(f"Error handling carriage return: {e}")

    def _handle_clear_line(self, text, pos):
        """Clear from cursor to the end of line"""
        try:
            end_iter = self.terminal_buffer.get_end_iter()
            line_end = end_iter.copy()
            line_end.forward_to_line_end()
            # Delete from current position to end of line
            self.terminal_buffer.delete(end_iter, line_end)
        except Exception as e:
            print(f"Error handling clear line: {e}")

    def _handle_clear_entire_line(self, text, pos):
        """Clear the entire current line"""
        try:
            end_iter = self.terminal_buffer.get_end_iter()
            line_start = end_iter.copy()
            line_end = end_iter.copy()

            # Move to start of line
            line_start.backward_chars(end_iter.get_line_offset())
            # Move to end of line
            line_end.forward_to_line_end()

            # Delete the entire line
            self.terminal_buffer.delete(line_start, line_end)
        except Exception as e:
            print(f"Error handling clear entire line: {e}")

    def _handle_clear_to_start(self, text, pos):
        """Clear from cursor to the start of line"""
        try:
            end_iter = self.terminal_buffer.get_end_iter()
            line_start = end_iter.copy()

            # Move to start of line
            line_start.backward_chars(end_iter.get_line_offset())

            # Delete from start of line to current position
            self.terminal_buffer.delete(line_start, end_iter)
        except Exception as e:
            print(f"Error handling clear to start: {e}")
