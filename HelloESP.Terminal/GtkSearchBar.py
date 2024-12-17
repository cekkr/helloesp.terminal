import re
from gi.repository import Gtk, Gdk, GObject, Pango


class SearchBar:
    def __init__(self, terminal_handler):
        self.terminal_handler = terminal_handler
        self.search_highlights = []
        self.current_match_index = -1

        # Create search bar container
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

        # Add widgets to search box
        self.search_box.pack_start(self.search_entry, False, True, 0)
        self.search_box.pack_start(close_button, False, True, 0)

        # Hide by default
        self.search_box.hide()

        # Add search highlight tag to terminal buffer
        self.search_tag = Gtk.TextTag.new('search-highlight')
        self.search_tag.set_property('background', '#FFE066')  # Yellow background
        self.search_tag.set_property('foreground', '#000000')  # Black text

        self.current_match_tag = Gtk.TextTag.new('current-match')
        self.current_match_tag.set_property('background', '#FF9933')  # Orange background
        self.current_match_tag.set_property('foreground', '#000000')  # Black text

        self.terminal_handler.tag_table.add(self.search_tag)
        self.terminal_handler.tag_table.add(self.current_match_tag)

        # Setup keyboard shortcuts
        self.terminal_handler.terminal.connect('key-press-event', self.on_key_press)

    def on_key_press(self, widget, event):
        # Check for Cmd+F (Mac) or Ctrl+F
        if event.state & Gdk.ModifierType.CONTROL_MASK or event.state & Gdk.ModifierType.META_MASK:
            if event.keyval == Gdk.KEY_f:
                self.show_search()
                return True
        # Check for Escape key
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
        self.terminal_handler.terminal.grab_focus()

    def clear_highlights(self):
        buffer = self.terminal_handler.terminal_buffer
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

        buffer = self.terminal_handler.terminal_buffer
        text = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), True)

        # Find all matches
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

        buffer = self.terminal_handler.terminal_buffer

        # Remove current match highlighting
        start = buffer.get_start_iter()
        end = buffer.get_end_iter()
        buffer.remove_tag(self.current_match_tag, start, end)

        # Highlight current match
        start_offset, end_offset = self.search_highlights[self.current_match_index]
        start_iter = buffer.get_iter_at_offset(start_offset)
        end_iter = buffer.get_iter_at_offset(end_offset)
        buffer.apply_tag(self.current_match_tag, start_iter, end_iter)

        # Scroll to current match
        self.terminal_handler.terminal.scroll_to_iter(start_iter, 0.0, True, 0.0, 0.5)

    def on_search_next(self, *args):
        if not self.search_highlights:
            return

        self.current_match_index = (self.current_match_index + 1) % len(self.search_highlights)
        self.highlight_current_match()
