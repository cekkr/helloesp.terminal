import re
from gi.repository import Gtk, Gdk, Pango

class TerminalHandler:
    def __init__(self):
        self.tag_table = Gtk.TextTagTable()
        self.terminal_buffer = Gtk.TextBuffer(tag_table=self.tag_table)
        self.terminal = Gtk.TextView(buffer=self.terminal_buffer)

        self.colors = {
            '30': 'black',
            '31': 'red',
            '32': 'green',
            '33': 'yellow',
            '34': 'blue',
            '35': 'magenta',
            '36': 'cyan',
            '37': 'white',
            '90': '#666666',
            '91': '#ff0000',
            '92': '#00ff00',
            '93': '#ffff00',
            '94': '#0000ff',
            '95': '#ff00ff',
            '96': '#00ffff',
            '97': '#ffffff'
        }

        self._init_tags()

        # Debug: stampa tutti i tag disponibili
        print("Tags disponibili:")
        self.tag_table.foreach(lambda tag, _: print(f"- {tag.get_property('name')}"))

    def _init_tags(self):
        # Color tags
        for code, color in self.colors.items():
            tag_name = f'fg_{code}'
            tag = Gtk.TextTag.new(tag_name)
            tag.set_property('foreground', color)
            self.tag_table.add(tag)

            bg_code = str(int(code) + 10)
            tag_name = f'bg_{bg_code}'
            tag = Gtk.TextTag.new(tag_name)
            tag.set_property('background', color)
            self.tag_table.add(tag)

        # Style tags con debug
        style_tags = {
            '1': ('weight', Pango.Weight.BOLD),
            '3': ('style', Pango.Style.ITALIC),
            '4': ('underline', Pango.Underline.SINGLE),
            '9': ('strikethrough', True),
        }

        for code, (prop, value) in style_tags.items():
            tag_name = f'style_{code}'
            tag = Gtk.TextTag.new(tag_name)
            tag.set_property(prop, value)
            print(f"Creato tag {tag_name} con proprietà {prop}={value}")
            self.tag_table.add(tag)

    def append_terminal(self, text):
        print(f"\nProcessing text: {repr(text)}")  # Debug
        ansi_escape = re.compile(r'\x1b\[((?:\d+;)*\d+)m')

        match_positions = []
        current_tags = set()

        for match in ansi_escape.finditer(text):
            start, end = match.span()
            codes = match.group(1).split(';')
            match_positions.append((start, end, codes))
            print(f"Found ANSI codes: {codes} at position {start}:{end}")  # Debug

        last_end = 0
        for start, end, codes in match_positions:
            if start > last_end:
                segment = text[last_end:start]
                print(f"Inserting segment '{segment}' with tags: {current_tags}")  # Debug
                self._insert_with_tags(segment, current_tags)

            self._update_tags(codes, current_tags)
            last_end = end

        if last_end < len(text):
            segment = text[last_end:]
            print(f"Inserting final segment '{segment}' with tags: {current_tags}")  # Debug
            self._insert_with_tags(segment, current_tags)

        self.terminal.scroll_to_iter(self.terminal_buffer.get_end_iter(), 0.0, False, 0.0, 0.0)

    def _update_tags(self, codes, current_tags):
        print(f"Updating tags with codes: {codes}")  # Debug
        for code in codes:
            if code == '0':
                current_tags.clear()
                print("Reset tags")  # Debug
            elif code in self.colors:
                current_tags = {tag for tag in current_tags if not tag.startswith('fg_')}
                current_tags.add(f'fg_{code}')
            elif code.startswith('4') and code != '4':
                current_tags = {tag for tag in current_tags if not tag.startswith('bg_')}
                current_tags.add(f'bg_{code}')
            elif code in ('1', '3', '4', '9'):
                tag_name = f'style_{code}'
                current_tags.add(tag_name)
                print(f"Added style tag: {tag_name}")  # Debug
        print(f"Current tags after update: {current_tags}")  # Debug

    def _insert_with_tags(self, text, tags):
        if not text:
            return

        end_iter = self.terminal_buffer.get_end_iter()
        start_mark = self.terminal_buffer.create_mark(None, end_iter, True)

        self.terminal_buffer.insert(end_iter, text)

        start_iter = self.terminal_buffer.get_iter_at_mark(start_mark)
        end_iter = self.terminal_buffer.get_end_iter()

        for tag_name in tags:
            tag = self.tag_table.lookup(tag_name)
            if tag:
                self.terminal_buffer.apply_tag(tag, start_iter, end_iter)
                print(f"Applied tag {tag_name} to text '{text}'")  # Debug
            else:
                print(f"Warning: Tag {tag_name} not found!")  # Debug

        self.terminal_buffer.delete_mark(start_mark)


# Test function
def test_terminal():
    handler = TerminalHandler()
    window = Gtk.Window()
    window.set_default_size(400, 300)
    window.add(handler.terminal)

    # Test various text attributes
    test_text = "Normal \x1b[1mBold\x1b[0m \x1b[3mItalic\x1b[0m \x1b[4mUnderline\x1b[0m \x1b[31mRed\x1b[0m\n"
    handler.append_terminal(test_text)

    window.connect("destroy", Gtk.main_quit)
    window.show_all()
    Gtk.main()


if __name__ == "__main__":
    test_terminal()