from __future__ import annotations
from collections.abc import Callable
import logging
from ctypes import CDLL
import math
from typing import cast, override

CDLL("libgtk4-layer-shell.so.0")
import gi  # noqa: E402

gi.require_version("Gtk4LayerShell", "1.0")
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

import time  # noqa: E402
import os
import difflib  # noqa: E402

from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk, Pango  # noqa: E402
from gi.repository import Gtk4LayerShell as LayerShell  # noqa: E402

from ._config import (  # noqa: E402
    DEFAULT_CSS_PROVIDER,
    DEFAULT_DARK_CSS_PROVIDER,
    DEFAULT_DARK_USER_CSS_PROVIDER,
    DEFAULT_USER_CSS_PROVIDER,
)

logger = logging.getLogger(__name__)


class HittaItem(GObject.Object):
    _name: str
    _icon: Gio.Icon
    _description: str

    def __init__(self, name: str, icon: Gio.Icon, description: str = ""):
        super().__init__()
        self._name = name
        self._icon = icon
        self._description = description

    @GObject.Property(type=str)
    def name(self) -> str:
        return self._name

    @GObject.Property(type=Gio.Icon)
    def icon(self) -> Gio.Icon:
        return self._icon

    @GObject.Property(type=str)
    def description(self) -> str:
        return self._description

    def execute(self) -> None:
        """Execute the item. To be implemented by subclasses."""
        raise NotImplementedError


class HittaAppItem(HittaItem):
    _app_info: Gio.AppInfo

    def __init__(self, app_info: Gio.AppInfo):
        name = app_info.get_display_name() or ""
        description = app_info.get_description() or ""
        icon = app_info.get_icon() or Gio.ThemedIcon.new("application-x-executable")
        super().__init__(name, icon, description)
        self._app_info = app_info

    @override
    def execute(self) -> None:
        """Launch the application."""
        try:
            self._app_info.launch([], None)
            logger.info(f"Launched app: {self.name}")
        except Exception as e:
            logger.error(f"Failed to launch app {self.name}: {e}")


class HittaFileItem(HittaItem):
    _filepath: str

    def __init__(self, filepath: str, icon: Gio.Icon):
        name = os.path.basename(filepath)
        description = os.path.dirname(filepath)
        super().__init__(name, icon, description)
        self._filepath = filepath

    @override
    def execute(self) -> None:
        """Open the file or folder with the default application."""
        try:
            file = Gio.File.new_for_path(self._filepath)
            Gtk.show_uri(None, file.get_uri(), Gdk.CURRENT_TIME)
            logger.info(f"Opened file: {self._filepath}")
        except Exception as e:
            logger.error(f"Failed to open file {self._filepath}: {e}")


class SearchProvider:
    callback: Callable[[list[HittaItem] | None], None]

    def __init__(self, callback: Callable[[list[HittaItem] | None], None]):
        self.callback = callback

    def search(self, query: str) -> None:
        raise NotImplementedError

    def cancel_search(self) -> None:
        pass


class FileSearchProvider(SearchProvider):
    icon_map: dict[str, Gio.Icon] = {
        ".txt": Gio.ThemedIcon.new("text-x-generic"),
        ".py": Gio.ThemedIcon.new("text-x-python"),
        ".js": Gio.ThemedIcon.new("text-x-javascript"),
        ".html": Gio.ThemedIcon.new("text-html"),
        ".pdf": Gio.ThemedIcon.new("application-pdf"),
        ".png": Gio.ThemedIcon.new("image-x-generic"),
        ".jpg": Gio.ThemedIcon.new("image-x-generic"),
        ".jpeg": Gio.ThemedIcon.new("image-x-generic"),
        ".gif": Gio.ThemedIcon.new("image-x-generic"),
        ".mp3": Gio.ThemedIcon.new("audio-x-generic"),
        ".mp4": Gio.ThemedIcon.new("video-x-generic"),
        ".zip": Gio.ThemedIcon.new("package-x-generic"),
    }

    _current_subprocess: Gio.Subprocess | None

    def __init__(self, callback: Callable[[list[HittaItem] | None], None]):
        super().__init__(callback)
        self._current_subprocess = None

    @override
    def search(
        self,
        query: str,
    ) -> None:
        self.cancel_search()

        try:
            launcher = Gio.SubprocessLauncher(flags=Gio.SubprocessFlags.STDOUT_PIPE)
            self._current_subprocess = launcher.spawnv(
                ["locate", "--limit", "500", query]
            )

            self._current_subprocess.communicate_utf8_async(
                None, None, self._on_locate_finished, query
            )

        except Exception as e:
            logger.error(f"Failed to start locate subprocess: {e}")
            self.callback([])

    @override
    def cancel_search(self) -> None:
        if self._current_subprocess is not None:
            self._current_subprocess.force_exit()
            self._current_subprocess = None

    def _on_locate_finished(
        self, subprocess: Gio.Subprocess, result: Gio.AsyncResult, query: str
    ):
        try:
            success, stdout, _stderr = subprocess.communicate_utf8_finish(result)

            if success and stdout:
                lines = stdout.strip().split("\n")

                results: list[tuple[float, str]] = []
                for line in lines:
                    if line.strip():
                        score = self._score_match(line, query)
                        results.append((score, line))

                results.sort(key=lambda x: x[0], reverse=True)

                items: list[HittaItem] = []
                for score, line in results[:50]:
                    icon = self._get_file_icon(line)
                    item = HittaFileItem(line, icon)
                    items.append(item)

                self.callback(items)
            else:
                self.callback([])

        except Exception as e:
            logger.error(f"Error processing locate results: {e}")
            self.callback([])
        finally:
            self._current_subprocess = None

    def _score_match(self, filepath: str, search_text: str) -> float:
        score = 0.0
        basename = os.path.basename(filepath)
        search_lower = search_text.lower()
        filepath_lower = filepath.lower()
        basename_lower = basename.lower()

        if basename_lower == search_lower:
            score += 100
        elif filepath_lower == search_lower:
            score += 90

        if basename_lower.startswith(search_lower):
            score += 50
        elif filepath_lower.startswith(search_lower):
            score += 40

        if search_lower in basename_lower:
            score += 30
            pos = basename_lower.find(search_lower)
            score += (20 - pos) if pos < 20 else 0
        elif search_lower in filepath_lower:
            score += 20

        path_depth = filepath.count(os.sep)
        score += max(0, 10 - path_depth)

        home_dir = os.path.expanduser("~")
        if filepath.startswith(home_dir):
            score += 5
        elif any(filepath.startswith(path) for path in ["/usr/bin", "/usr/local/bin"]):
            score += 3

        if os.path.isdir(filepath):
            score += 2

        if os.path.basename(filepath).startswith(".") and not search_text.startswith(
            "."
        ):
            score -= 10

        if os.path.isfile(filepath) and os.access(filepath, os.X_OK):
            score += 3

        return score

    def _get_file_icon(self, filepath: str) -> Gio.Icon:
        if os.path.isdir(filepath):
            return Gio.ThemedIcon.new("folder")

        _, ext = os.path.splitext(filepath.lower())
        if ext in FileSearchProvider.icon_map:
            return FileSearchProvider.icon_map[ext]
        else:
            return Gio.ThemedIcon.new("text-x-generic")


class AppSearchProvider(SearchProvider):
    _app_infos: list[Gio.AppInfo]

    def __init__(self, callback: Callable[[list[HittaItem] | None], None]):
        super().__init__(callback)
        self._app_infos = Gio.AppInfo.get_all()

    @override
    def search(self, query: str):
        if not self._app_infos:
            self.callback([])
            return

        query_lower = query.lower()
        scored_results: list[tuple[float, HittaItem]] = []

        for app_info in self._app_infos:
            if not app_info.should_show():
                continue

            name = app_info.get_display_name() or ""
            description = app_info.get_description() or ""

            name_ratio, matches = self._has_fuzzy_match(name, description, query_lower)
            if matches:
                score = self._score_app_match(
                    name, description, query_lower, name_ratio
                )
                item = HittaAppItem(app_info)
                scored_results.append((score, item))

        # Sort by score and take top 50
        scored_results.sort(key=lambda x: x[0], reverse=True)
        items = [item for score, item in scored_results[:50]]

        self.callback(items)

    def _has_fuzzy_match(
        self, name: str, description: str, query: str
    ) -> tuple[float, bool]:
        # Try fuzzy match on name first
        score = self._fuzzy_match_score(name, query)
        if score > 0:
            return score, True

        # Fall back to description for short queries
        if len(query) <= 3:
            desc_score = self._fuzzy_match_score(description, query)
            if desc_score > 0:
                return desc_score * 0.5, True  # Lower score for description matches

        return 0.0, False

    def _fuzzy_match_score(self, text: str, query: str) -> float:
        if not query or not text:
            return 0.0

        text_lower = text.lower()
        query_lower = query.lower()

        # Exact substring match gets highest score
        if query_lower in text_lower:
            pos = text_lower.find(query_lower)
            # Bonus for earlier position and word boundary
            score = 100.0
            score += max(0, 20 - pos)  # Earlier is better
            if pos == 0 or not text[pos - 1].isalnum():  # Word boundary
                score += 20
            return score

        # Character-by-character fuzzy matching
        text_idx = 0
        query_idx = 0
        score = 0.0
        consecutive_bonus = 0
        gap_penalty = 0

        while query_idx < len(query_lower) and text_idx < len(text_lower):
            query_char = query_lower[query_idx]

            # Find next matching character
            match_found = False
            gap_start = text_idx

            while text_idx < len(text_lower):
                text_char = text_lower[text_idx]

                if text_char == query_char:
                    match_found = True

                    # Base score for character match
                    char_score = 1.0

                    # Case match bonus
                    if text_idx < len(text) and text[text_idx] == query[query_idx]:
                        char_score += 0.5

                    # Word boundary bonus
                    if text_idx == 0 or not text[text_idx - 1].isalnum():
                        char_score += 2.0
                    # CamelCase bonus
                    elif text[text_idx].isupper():
                        char_score += 1.0

                    # Consecutive character bonus
                    if consecutive_bonus > 0:
                        char_score += consecutive_bonus
                        consecutive_bonus += (
                            0.5  # Increasing bonus for longer sequences
                        )
                    else:
                        consecutive_bonus = 0.5

                    # Gap penalty (distance from last match)
                    gap_size = text_idx - gap_start
                    if gap_size > 0:
                        gap_penalty += gap_size * 0.1

                    score += char_score
                    text_idx += 1
                    break

                text_idx += 1

            if not match_found:
                return 0.0  # No match found for this query character

            query_idx += 1
            if query_idx < len(query_lower):
                consecutive_bonus = 0  # Reset for next character

        # Check if we matched all query characters
        if query_idx < len(query_lower):
            return 0.0

        # Apply gap penalty and normalize
        final_score = max(0.0, score - gap_penalty)

        # Length normalization - prefer shorter matches
        length_bonus = max(0, 10 - len(text) // 2)
        final_score += length_bonus

        # Minimum threshold for fuzzy matches
        min_score = len(query) * 0.5
        return final_score if final_score >= min_score else 0.0

    def _score_app_match(
        self, name: str, description: str, query: str, fuzzy_score: float
    ) -> float:
        # The fuzzy score already includes most of the logic we need
        score = fuzzy_score

        # Small bonus for shorter names (accessibility)
        if len(name) < 20:
            score += 2

        return score


class HittaItemWidget(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        self.icon = Gtk.Image()
        self.icon.set_icon_size(Gtk.IconSize.NORMAL)

        inner_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        self.name: Gtk.Label = Gtk.Label(name="name")
        self.name.set_halign(Gtk.Align.START)
        self.name.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        self.name.set_max_width_chars(50)

        self.description: Gtk.Label = Gtk.Label(name="description")
        self.description.set_halign(Gtk.Align.START)
        self.description.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        self.description.set_max_width_chars(50)
        inner_box.append(self.name)
        inner_box.append(self.description)

        self.append(self.icon)
        self.append(inner_box)

    def bind_item(self, item: HittaItem):
        self.icon.set_from_gicon(item.icon)

        self.name.set_text(item.name)
        self.description.set_text(item.description)


class ScrolledListView(Gtk.ScrolledWindow):
    def __init__(
        self, list_view: Gtk.ListView, list_model: Gio.ListStore, max_height: int = 100
    ):
        super().__init__()
        self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.set_propagate_natural_height(True)
        self.set_child(list_view)
        self.max_height = max_height
        self.list_view = list_view
        self.list_model = list_model
        self.list_model.connect("items-changed", self._on_items_changed)

    def _on_items_changed(self, model, position, removed, added):
        self.queue_resize()

    def do_measure(self, orientation, for_size):
        # Get the child's measurement
        child = self.get_child()
        if child is None:
            return 0, 0, -1, -1

        minimum, natural, minimum_baseline, natural_baseline = child.measure(
            orientation, for_size
        )

        # Apply height constraint only for vertical orientation
        if orientation == Gtk.Orientation.VERTICAL:
            minimum = min(minimum, self.max_height)
            natural = min(natural, self.max_height)

        return minimum, natural, minimum_baseline, natural_baseline


class HittaWindow(Gtk.Window):
    input: Gtk.TextView
    result_list: Gtk.ListView
    list_model: Gio.ListStore
    selection_model: Gtk.SingleSelection

    def __init__(self, app: HittaApp):
        super().__init__(application=app, name="hitta")
        self.set_size_request(600, -1)

        # Initialize search providers
        self.file_search_provider: SearchProvider = FileSearchProvider(
            self._on_search_results
        )
        self.app_search_provider: SearchProvider = AppSearchProvider(
            self._on_search_results
        )

        # Create main container
        main_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=0, name="main-view"
        )

        # Create input
        self.input = Gtk.TextView(name="input")
        self.input.set_cursor_visible(False)
        self.input.set_accepts_tab(False)

        # Create window-level key controller with high priority to override defaults
        window_key_controller = Gtk.EventControllerKey()
        window_key_controller.connect("key-pressed", self._on_window_key_pressed)
        # Set propagation phase to capture to intercept before other handlers
        window_key_controller.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        self.add_controller(window_key_controller)

        # Create list model
        self.list_model = Gio.ListStore(item_type=HittaItem)

        # Create selection model
        self.selection_model = Gtk.SingleSelection(model=self.list_model)

        # Create list item factory
        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self._on_factory_setup)
        factory.connect("bind", self._on_factory_bind)

        # Create result list
        self.result_list = Gtk.ListView(
            name="results",
            model=self.selection_model,
            factory=factory,
            single_click_activate=True,
        )
        self.result_list.connect("activate", self._on_result_list_activate)
        self.scrolled_list_view = ScrolledListView(
            self.result_list, self.list_model, max_height=200
        )
        main_box.set_size_request(400, -1)
        main_box.set_valign(Gtk.Align.START)
        main_box.set_vexpand(True)
        main_box.append(self.input)
        main_box.append(self.scrolled_list_view)

        self.set_child(main_box)

        input_buffer = self.input.get_buffer()
        input_buffer.connect("changed", self._on_input_changed)

        self._search_timeout_id = None

        self.connect("map", self._on_window_mapped)

    def _on_factory_setup(
        self, factory: Gtk.SignalListItemFactory, list_item: Gtk.ListItem
    ) -> None:
        widget = HittaItemWidget()
        list_item.set_child(widget)

    def _on_factory_bind(
        self, factory: Gtk.SignalListItemFactory, list_item: Gtk.ListItem
    ) -> None:
        item: HittaItem = list_item.get_item()
        widget: HittaItemWidget = list_item.get_child()
        widget.bind_item(item)

    def _on_window_key_pressed(self, controller, keyval, keycode, state):
        self.input.grab_focus()

        if keyval == Gdk.KEY_Up or keyval == Gdk.KEY_KP_Up:
            self._navigate_list(-1)
            return True
        elif keyval == Gdk.KEY_Down or keyval == Gdk.KEY_KP_Down:
            self._navigate_list(1)
            return True
        elif keyval == Gdk.KEY_Return or keyval == Gdk.KEY_KP_Enter:
            # Handle Enter key - trigger submission
            self._on_submit()
            return True
        elif keyval == Gdk.KEY_Escape:
            self.set_visible(False)
            return True

        return False

    def _navigate_list(self, direction: int):
        n_items = self.list_model.get_n_items()
        if n_items == 0:
            return

        current = self.selection_model.get_selected()
        if current == Gtk.INVALID_LIST_POSITION:
            new_selection = 0
        else:
            new_selection = current + direction
            # Wrap around at boundaries
            if new_selection < 0:
                new_selection = n_items - 1
            elif new_selection >= n_items:
                new_selection = 0

        self.selection_model.set_selected(new_selection)

        self.result_list.scroll_to(new_selection, Gtk.ListScrollFlags.NONE, None)

    def _on_window_mapped(self, window: Gtk.Window):
        def focus_input():
            _ = self.input.grab_focus()
            return False

        _ = GLib.idle_add(focus_input)

    def _on_input_changed(self, buffer: Gtk.TextBuffer):
        if self._search_timeout_id is not None:
            _ = GLib.source_remove(self._search_timeout_id)
            self._search_timeout_id = None

        search_text = buffer.get_text(
            buffer.get_start_iter(), buffer.get_end_iter(), False
        ).strip()

        if search_text:
            self._search_timeout_id = GLib.timeout_add(
                30, self._perform_search, search_text
            )
        else:
            self.list_model.remove_all()

    def _perform_search(self, search_text: str) -> bool:
        self._search_timeout_id = None

        self.file_search_provider.cancel_search()

        if search_text.startswith("'"):
            query = search_text[1:]
            if query:
                self.file_search_provider.search(query)
            else:
                self.list_model.remove_all()
        else:
            self.app_search_provider.search(search_text)

        return False  # Don't repeat the timeout

    def _on_search_results(self, items: list[HittaItem] | None) -> None:
        self.list_model.remove_all()

        if items is None:
            return

        for item in items:
            self.list_model.append(item)

        if self.list_model.get_n_items() > 0:
            self.selection_model.set_selected(0)

    def _on_result_list_activate(self, list_view: Gtk.ListView, position: int):
        """Handle mouse activation (click/double-click) on a result item."""
        if position != Gtk.INVALID_LIST_POSITION:
            selected_item = self.list_model.get_item(position)
            selected_item.execute()
        self.input.get_buffer().set_text("")
        self.set_visible(False)

    def _on_submit(self):
        buffer = self.input.get_buffer()
        text = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False)

        selected_position = self.selection_model.get_selected()
        if selected_position != Gtk.INVALID_LIST_POSITION:
            selected_item = self.list_model.get_item(selected_position)
            selected_item.execute()
        else:
            print(f"Submitted: {text}, No item selected")

        buffer.set_text("")
        self.set_visible(False)


class HittaApp(Adw.Application):
    window: HittaWindow | None

    def __init__(self):
        super().__init__(application_id="io.github.isaksamsten.Hitta")
        self.window = None

    @override
    def do_activate(self) -> None:
        self.window = HittaWindow(self)
        LayerShell.init_for_window(self.window)
        LayerShell.set_namespace(self.window, "hitta")
        LayerShell.set_layer(self.window, LayerShell.Layer.OVERLAY)
        LayerShell.set_keyboard_mode(self.window, LayerShell.KeyboardMode.EXCLUSIVE)
        LayerShell.set_anchor(self.window, LayerShell.Edge.TOP, True)
        LayerShell.set_margin(self.window, LayerShell.Edge.TOP, 200)
        self.window.set_visible(True)
        self.window.show()


def main() -> None:
    app = HittaApp()
    display = Gdk.Display.get_default()
    if display is not None:
        Gtk.StyleContext.add_provider_for_display(
            display,
            DEFAULT_CSS_PROVIDER,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )
        if DEFAULT_USER_CSS_PROVIDER is not None:
            Gtk.StyleContext.add_provider_for_display(
                display,
                DEFAULT_USER_CSS_PROVIDER,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 2,
            )
    else:
        logger.error("Could not find default display")

    if app.get_style_manager().get_dark():
        _set_dark_style()

    _id = app.get_style_manager().connect("notify::dark", on_dark)

    _ = app.register(None)
    _ = app.run(None)


def on_dark(style_manager: Adw.StyleManager, _prop: object):
    if style_manager.get_dark():
        _set_dark_style()
    else:
        display = Gdk.Display.get_default()
        if display is not None:
            Gtk.StyleContext.remove_provider_for_display(
                display, DEFAULT_DARK_CSS_PROVIDER
            )
            if DEFAULT_DARK_USER_CSS_PROVIDER is not None:
                Gtk.StyleContext.remove_provider_for_display(
                    display, DEFAULT_DARK_USER_CSS_PROVIDER
                )
        else:
            logger.error("Could not find default display")


def _set_dark_style():
    display = Gdk.Display.get_default()
    if display is not None:
        Gtk.StyleContext.add_provider_for_display(
            display,
            DEFAULT_DARK_CSS_PROVIDER,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1,
        )
        if DEFAULT_DARK_USER_CSS_PROVIDER is not None:
            Gtk.StyleContext.add_provider_for_display(
                display,
                DEFAULT_DARK_USER_CSS_PROVIDER,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 3,
            )
    else:
        logger.error("Could not find default display")
