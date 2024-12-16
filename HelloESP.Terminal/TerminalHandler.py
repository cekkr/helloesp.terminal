import re
from gi.repository import Gtk, Gdk, Pango
from gi.repository import GObject


class TerminalHandler:
    def __init__(self):
        self.tag_table = Gtk.TextTagTable()
        self.terminal_buffer = Gtk.TextBuffer(tag_table=self.tag_table)
        self.terminal = Gtk.TextView(buffer=self.terminal_buffer)

        # Configure TextView
        self.terminal.set_wrap_mode(Gtk.WrapMode.CHAR)
        self.terminal.set_editable(False)

        # Create scrolled window
        self.scrolled_window = Gtk.ScrolledWindow()
        self.scrolled_window.add(self.terminal)
        self.scrolled_window.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)

        # Keep reference to the adjustment
        self.vadj = self.scrolled_window.get_vadjustment()

        # Buffer update handling
        self.pending_updates = []
        self.update_pending = False

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
        for code in codes:
            if code == '0':
                current_tags.clear()
            else:
                new_tags = self._parse_ansi_code(code)
                if new_tags:
                    # Remove conflicting tags before adding new ones
                    if any(tag.startswith('fg_') for tag in new_tags):
                        current_tags = {tag for tag in current_tags if not tag.startswith('fg_')}
                    if any(tag.startswith('bg_') for tag in new_tags):
                        current_tags = {tag for tag in current_tags if not tag.startswith('bg_')}
                    current_tags.update(new_tags)

    def _schedule_update(self, text, tags):
        """Schedule a text update to be processed in the main loop"""
        self.pending_updates.append((text, tags))
        if not self.update_pending:
            self.update_pending = True
            GObject.idle_add(self._process_updates, priority=GObject.PRIORITY_LOW)

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

            adj = self.vadj
            if adj:
                GObject.idle_add(
                    lambda: adj.set_value(adj.get_upper() - adj.get_page_size()),
                    priority=GObject.PRIORITY_LOW
                )

        except Exception as e:
            print(f"Error processing updates: {e}")

        self.update_pending = False
        return False

    def append_terminal(self, text):
        if not text:
            return

        try:
            text = self._sanitize_text(text)
            ansi_pattern = re.compile(r'\x1b\[([0-9;]*)m')

            segments = []
            current_position = 0
            current_tags = set()

            for match in ansi_pattern.finditer(text):
                print("Found ANSI pattern")

                start, end = match.span()
                if start > current_position:
                    segments.append((text[current_position:start], current_tags.copy()))

                codes = match.group(1).split(';') if match.group(1) else ['0']
                self._update_tags(codes, current_tags)
                current_position = end

            if current_position < len(text):
                segments.append((text[current_position:], current_tags.copy()))

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

    def get_widget(self):
        """Return the scrolled window containing the terminal"""
        return self.scrolled_window