from __future__ import annotations
from collections.abc import Callable, Generator
from getopt import GetoptError
import logging
from ctypes import CDLL
import math
import signal
from typing import cast, final, override

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


class Action(GObject.Object):
    name: GObject.Property = GObject.Property(type=str)
    icon: GObject.Property = GObject.Property(
        type=Gio.Icon,
        default=Gio.ThemedIcon.new_with_default_fallbacks("application-x-executable"),
    )
    description: GObject.Property = GObject.Property(type=str)

    def __init__(
        self, name: str, description: str, icon: Gio.Icon | None = None
    ) -> None:
        super().__init__()
        self.name = name
        self.description = description
        if icon:
            self.icon = icon

    def execute(self) -> None:
        try:
            self.do_execute()
        except Exception:
            logger.exception("failed to execute")

    def get_actions(self) -> list[Action]:
        actions: list[Action] = []
        for action in self.do_get_actions():
            actions.append(action)
        return actions

    def do_get_actions(self) -> Generator[Action]:
        yield from ()

    def do_execute(self) -> None:
        raise NotImplementedError


class FileAction(Action):
    file_launcher: Gtk.FileLauncher

    def __init__(
        self, file: Gio.File, name: str, description: str, icon: Gio.Icon | None
    ) -> None:
        super().__init__(name=name, description=description, icon=icon)
        self.file_launcher = Gtk.FileLauncher.new(file)


@final
class OpenFile(FileAction):
    def __init__(self, file: Gio.File) -> None:
        super().__init__(
            file=file,
            name="Open file",
            description="Open file using default application",
            icon=Gio.ThemedIcon.new("document-open"),
        )

    @override
    def do_execute(self) -> None:
        self.file_launcher.launch(None, None, None)


@final
class OpenContainingFolder(FileAction):
    def __init__(self, file: Gio.File):
        super().__init__(
            file=file,
            name="Open containing directory",
            description="Open the folder that contains this file",
            icon=Gio.ThemedIcon.new("folder-open"),
        )

    @override
    def do_execute(self) -> None:
        self.file_launcher.open_containing_folder(None, None, None)


@final
class CopyFilePath(FileAction):
    def __init__(self, file: Gio.File):
        super().__init__(
            file=file,
            name="Copy file path",
            description="Copy the full file path to clipboard",
            icon=Gio.ThemedIcon.new("edit-copy"),
        )

    @override
    def do_execute(self) -> None:
        display = Gdk.Display.get_default()
        file = self.file_launcher.get_file()
        if display and file:
            clipboard = display.get_clipboard()
            clipboard.set(file.get_path())


@final
class CopyFileName(FileAction):
    def __init__(self, file: Gio.File):
        super().__init__(
            file=file,
            name="Copy file name",
            description="Copy the file name to clipboard",
            icon=Gio.ThemedIcon.new("edit-copy"),
        )

    @override
    def do_execute(self) -> None:
        display = Gdk.Display.get_default()
        file = self.file_launcher.get_file()
        if display and file:
            clipboard = display.get_clipboard()
            clipboard.set(file.get_basename())


@final
class OpenWith(FileAction):
    def __init__(
        self,
        file: Gio.File,
        default_app_info: Gio.AppInfo,
        all_app_infos: list[Gio.AppInfo],
    ):
        super().__init__(
            file=file,
            name="Open with...",
            description="Choose application to open file with",
            icon=default_app_info.get_icon()
            or Gio.ThemedIcon.new("application-x-executable"),
        )
        self.default_app_info = default_app_info
        self.all_app_infos = all_app_infos

    @override
    def do_execute(self) -> None:
        self.default_app_info.launch([self.file_launcher.get_file()], None)

    @override
    def do_get_actions(self) -> Generator[Action]:
        for app_info in self.all_app_infos:
            if app_info.should_show() and app_info != self.default_app_info:
                yield OpenWithSpecificApp(self.file_launcher.get_file(), app_info)


@final
class OpenWithSpecificApp(FileAction):
    def __init__(self, file: Gio.File, app_info: Gio.AppInfo):
        super().__init__(
            file=file,
            name=f"Open with {app_info.get_display_name()}",
            description=f"Open file using {app_info.get_display_name()}",
            icon=app_info.get_icon() or Gio.ThemedIcon.new("application-x-executable"),
        )
        self.app_info = app_info

    @override
    def do_execute(self) -> None:
        self.app_info.launch([self.file_launcher.get_file()], None)


@final
class ApplicationLaunchAction(Action):
    def __init__(self, appinfo: Gio.AppInfo):
        super().__init__(
            name=f"Launch {appinfo.get_display_name()}",
            description="Launch the application",
            icon=appinfo.get_icon() or Gio.ThemedIcon.new("application-x-executable"),
        )
        self.appinfo = appinfo

    @override
    def do_execute(self) -> None:
        self.appinfo.launch([], None)


class SearchResult(Action):
    def __init__(self, name: str, icon: Gio.Icon, description: str):
        super().__init__(name=name, icon=icon, description=description)

    def get_default_action(self) -> Action:
        raise NotImplementedError

    @override
    def do_execute(self) -> None:
        self.get_default_action().execute()


@final
class ApplicationSearchResult(SearchResult):
    def __init__(self, app_info: Gio.AppInfo):
        super().__init__(
            name=app_info.get_display_name() or "",
            description=app_info.get_description() or "",
            icon=app_info.get_icon() or Gio.ThemedIcon.new("application-x-executable"),
        )
        self.appinfo = app_info

    @override
    def get_default_action(self) -> Action:
        return ApplicationLaunchAction(self.appinfo)


@final
class FileSearchResult(SearchResult):
    _icon_map: dict[str, Gio.Icon] = {
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

    def __init__(self, filepath: str):
        super().__init__(
            name=os.path.basename(filepath),
            description=os.path.dirname(filepath),
            icon=self._get_file_icon(filepath),
        )
        self.file = Gio.File.new_for_path(filepath)

    def _get_file_icon(self, filepath: str) -> Gio.Icon:
        if os.path.isdir(filepath):
            return Gio.ThemedIcon.new("folder")

        _, ext = os.path.splitext(filepath.lower())
        if ext in FileSearchResult._icon_map:
            return FileSearchResult._icon_map[ext]
        else:
            return Gio.ThemedIcon.new("text-x-generic")

    @override
    def get_default_action(self) -> Action:
        return OpenFile(self.file)

    @override
    def do_get_actions(self) -> Generator[Action]:
        yield OpenContainingFolder(self.file)
        yield CopyFilePath(self.file)
        yield CopyFileName(self.file)

        file_info = self.file.query_info(
            "standard::content-type", Gio.FileQueryInfoFlags.NONE, None
        )
        if file_info:
            content_type = file_info.get_content_type()
            if content_type:
                app_infos = Gio.AppInfo.get_all_for_type(content_type)
                valid_app_infos = [app for app in app_infos if app.should_show()]

                if valid_app_infos:
                    default_app = Gio.AppInfo.get_default_for_type(content_type, False)
                    if default_app and default_app.should_show():
                        yield OpenWith(self.file, default_app, valid_app_infos)
                    elif valid_app_infos:
                        yield OpenWith(self.file, valid_app_infos[0], valid_app_infos)


class SearchProvider:
    callback: Callable[[list[SearchResult] | None], None]

    def __init__(self, callback: Callable[[list[SearchResult] | None], None]):
        self.callback = callback

    def search(self, query: str) -> None:
        raise NotImplementedError

    def cancel_search(self) -> None:
        pass


class FileSearchProvider(SearchProvider):
    _current_subprocess: Gio.Subprocess | None

    def __init__(self, callback: Callable[[list[SearchResult] | None], None]):
        super().__init__(callback)
        self._current_subprocess = None

    @override
    def search(
        self,
        query: str,
    ) -> None:
        if len(query) < 2:
            self.callback([])
            return

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

                items: list[SearchResult] = []
                for score, line in results[:50]:
                    item = FileSearchResult(line)
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

        if os.path.isdir(filepath):
            score += 2

        if not search_text.startswith("."):
            path_parts = filepath.split(os.sep)
            for part in path_parts[:-1]:
                if part.startswith(".") and part != "." and part != "..":
                    score -= 10
                    break

        return score


class AppSearchProvider(SearchProvider):
    _app_infos: list[Gio.AppInfo]

    def __init__(self, callback: Callable[[list[SearchResult] | None], None]):
        super().__init__(callback)
        self._app_infos = Gio.AppInfo.get_all()

    @override
    def search(self, query: str):
        if not self._app_infos:
            self.callback([])
            return

        query_lower = query.lower()
        scored_results: list[tuple[float, SearchResult]] = []

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
                item = ApplicationSearchResult(app_info)
                scored_results.append((score, item))

        # Sort by score and take top 50
        scored_results.sort(key=lambda x: x[0], reverse=True)
        items = [item for score, item in scored_results[:50]]

        self.callback(items)

    def _has_fuzzy_match(
        self, name: str, description: str, query: str
    ) -> tuple[float, bool]:
        score = self._fuzzy_match_score(name, query)
        if score > 0:
            return score, True

        if len(query) <= 3:
            desc_score = self._fuzzy_match_score(description, query)
            if desc_score > 0:
                return desc_score * 0.5, True

        return 0.0, False

    def _fuzzy_match_score(self, text: str, query: str) -> float:
        if not query or not text:
            return 0.0

        # Early exit for very short queries on long text
        if len(query) == 1 and len(text) > 50:
            return 0.0

        text_lower = text.lower()
        query_lower = query.lower()

        # Fast path for exact substring matches
        if query_lower in text_lower:
            pos = text_lower.find(query_lower)
            score = 100.0
            score += max(0, 20 - pos)
            if pos == 0 or not text[pos - 1].isalnum():
                score += 20
            return score

        # Only do expensive fuzzy matching for reasonable length combinations
        if len(text) > 100 and len(query) < 3:
            return 0.0

        text_idx = 0
        query_idx = 0
        score = 0.0
        consecutive_bonus = 0
        gap_penalty = 0

        while query_idx < len(query_lower) and text_idx < len(text_lower):
            query_char = query_lower[query_idx]

            match_found = False
            gap_start = text_idx

            while text_idx < len(text_lower):
                text_char = text_lower[text_idx]

                if text_char == query_char:
                    match_found = True
                    char_score = 1.0

                    if text_idx < len(text) and text[text_idx] == query[query_idx]:
                        char_score += 0.5

                    if text_idx == 0 or not text[text_idx - 1].isalnum():
                        char_score += 2.0
                    elif text[text_idx].isupper():
                        char_score += 1.0

                    if consecutive_bonus > 0:
                        char_score += consecutive_bonus
                        consecutive_bonus += 0.5
                    else:
                        consecutive_bonus = 0.5

                    gap_size = text_idx - gap_start
                    if gap_size > 0:
                        gap_penalty += gap_size * 0.1

                    score += char_score
                    text_idx += 1
                    break

                text_idx += 1

            if not match_found:
                return 0.0

            query_idx += 1
            if query_idx < len(query_lower):
                consecutive_bonus = 0

        if query_idx < len(query_lower):
            return 0.0

        final_score = max(0.0, score - gap_penalty)
        length_bonus = max(0, 10 - len(text) // 2)
        final_score += length_bonus

        min_score = len(query) * 0.5
        return final_score if final_score >= min_score else 0.0

    def _score_app_match(
        self, name: str, description: str, query: str, score: float
    ) -> float:
        if len(name) < 20:
            return score + 2

        return score


class SearchResultWidget(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        self.icon = Gtk.Image()
        self.icon.set_icon_size(Gtk.IconSize.LARGE)

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

    def bind_item(self, item: SearchResult):
        self.icon.set_from_gicon(item.icon)

        self.name.set_text(item.name)
        self.description.set_text(item.description)


@final
class ActionWidget(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        self.icon = Gtk.Image()
        self.icon.set_icon_size(Gtk.IconSize.LARGE)

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

    def bind_item(self, item: Action):
        self.icon.set_from_gicon(item.icon)
        self.name.set_text(item.name)
        self.description.set_text(item.description)


class MaxHeightScrolledWindow(Gtk.ScrolledWindow):
    max_height: int

    def __init__(self, max_height: int = 100):
        super().__init__()
        self.max_height = max_height
        self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.set_propagate_natural_height(True)

    @override
    def do_measure(
        self, orientation: Gtk.Orientation, for_size: int
    ) -> tuple[int, int, int, int]:
        child = self.get_child()
        if child is None:
            return 0, 0, -1, -1

        minimum, natural, minimum_baseline, natural_baseline = child.measure(
            orientation, for_size
        )

        if orientation == Gtk.Orientation.VERTICAL:
            minimum = min(minimum, self.max_height)
            natural = min(natural, self.max_height)

        return minimum, natural, minimum_baseline, natural_baseline


class ResultList(MaxHeightScrolledWindow):
    list_model: Gio.ListStore
    selection_model: Gtk.SingleSelection
    list_view: Gtk.ListView

    def __init__(
        self,
        item_type: type[Action],
        factory: Gtk.ListItemFactory | None = None,
        max_height: int = 100,
    ):
        super().__init__(max_height=max_height)
        self.list_model = Gio.ListStore(item_type=item_type)
        self.selection_model = Gtk.SingleSelection(model=self.list_model)

        if factory is None:
            factory = Gtk.SignalListItemFactory()

        self.list_view = Gtk.ListView(
            name="results",
            model=self.selection_model,
            factory=factory,
            can_target=False,
        )
        self.list_model.connect("items-changed", self._on_items_changed)
        self.set_child(self.list_view)

    def navigate_list(self, direction: int):
        n_items = self.list_model.get_n_items()
        if n_items == 0:
            return

        current = self.selection_model.get_selected()
        if current == Gtk.INVALID_LIST_POSITION:
            new_selection = 0
        else:
            new_selection = current + direction
            if new_selection < 0:
                new_selection = n_items - 1
            elif new_selection >= n_items:
                new_selection = 0

        self.selection_model.set_selected(new_selection)
        self.list_view.scroll_to(new_selection, Gtk.ListScrollFlags.NONE, None)

    def get_selected(self) -> Action | None:
        selected_position = self.selection_model.get_selected()
        if selected_position != Gtk.INVALID_LIST_POSITION:
            return cast(Action, self.list_model.get_item(selected_position))
        return None

    def execute_default_action(self) -> None:
        selected = self.get_selected()
        if selected is not None:
            selected.execute()

    def get_actions(self) -> list[Action] | None:
        selected = self.get_selected()
        if selected is not None:
            return selected.get_actions()
        return None

    def set_items(self, items: list[Action]):
        self.list_model.splice(0, self.list_model.get_n_items(), items)

        if self.list_model.get_n_items() > 0:
            self.selection_model.set_selected(0)

    def _on_items_changed(
        self, _model: int, _position: int, _removed: int, _added: int
    ) -> None:
        self.queue_resize()


@final
class SearchResultList(ResultList):
    def __init__(self, max_height: int = 100):
        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self._on_factory_setup)
        factory.connect("bind", self._on_factory_bind)

        super().__init__(SearchResult, factory=factory, max_height=max_height)

    def _on_factory_setup(
        self, factory: Gtk.SignalListItemFactory, list_item: Gtk.ListItem
    ) -> None:
        list_item.set_child(SearchResultWidget())

    def _on_factory_bind(
        self, factory: Gtk.SignalListItemFactory, list_item: Gtk.ListItem
    ) -> None:
        item = cast(SearchResult, list_item.get_item())
        widget = cast(SearchResultWidget, list_item.get_child())
        widget.bind_item(item)


@final
class ActionList(ResultList):
    def __init__(self, max_height: int = 100):
        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self._on_factory_setup)
        factory.connect("bind", self._on_factory_bind)

        super().__init__(Action, factory=factory, max_height=max_height)

    def _on_factory_setup(
        self, factory: Gtk.SignalListItemFactory, list_item: Gtk.ListItem
    ) -> None:
        list_item.set_child(ActionWidget())

    def _on_factory_bind(
        self, factory: Gtk.SignalListItemFactory, list_item: Gtk.ListItem
    ) -> None:
        item = cast(Action, list_item.get_item())
        widget = cast(ActionWidget, list_item.get_child())
        widget.bind_item(item)


class ResultStack(Gtk.Stack):
    search_result: SearchResultList
    _stack: list[ResultList]
    _search_states: list[tuple[str, list[Action]]]  # (query, original_items)

    def __init__(self, max_height: int = 200):
        super().__init__(hhomogeneous=True, vhomogeneous=False)
        self.search_result = SearchResultList(max_height=max_height)
        self._stack = [self.search_result]
        self._search_states = [("", [])]  # Initial state for search results
        self.add_child(self.search_result)
        self.set_visible_child(self.search_result)

    def get_current_list(self) -> ResultList:
        return self._stack[-1]

    def is_at_search_level(self) -> bool:
        """Return True if currently showing search results, False if showing actions."""
        return len(self._stack) <= 1

    def search_current_level(self, query: str) -> None:
        if len(self._stack) <= 1:
            return  # Search results are handled by the window

        current_list = self._stack[-1]
        current_query, original_items = self._search_states[-1]

        if not query:
            # Empty query, show all original items
            current_list.set_items(original_items)
        else:
            # Filter items based on query
            query_lower = query.lower()
            filtered_items = []

            for item in original_items:
                if (
                    query_lower in item.name.lower()
                    or query_lower in item.description.lower()
                ):
                    filtered_items.append(item)

            current_list.set_items(filtered_items)

        # Update the search state for current level
        self._search_states[-1] = (query, original_items)

    def get_current_search_query(self) -> str:
        if len(self._search_states) > 0:
            return self._search_states[-1][0]
        return ""

    def update_current_search_state(self, query: str) -> None:
        """Update the search query for the current level while preserving original items."""
        if len(self._search_states) > 0:
            original_items = self._search_states[-1][1]
            self._search_states[-1] = (query, original_items)

    def push_actions(self, actions: list[Action]) -> None:
        if len(actions) == 0:
            return

        action_list = ActionList(max_height=200)
        action_list.set_items(actions)
        self._stack.append(action_list)
        self._search_states.append(("", actions))  # Store original actions
        self.add_child(action_list)
        self.set_visible_child(action_list)

    def pop_stack(self) -> bool:
        if len(self._stack) <= 1:
            return False

        current_list = self._stack.pop()
        self._search_states.pop()
        self.remove(current_list)

        previous_list = self._stack[-1]
        self.set_visible_child(previous_list)
        return True

    def reset_to_search_results(self) -> None:
        while len(self._stack) > 1:
            current_list = self._stack.pop()
            self.remove(current_list)

        self._search_states = [("", [])]
        self.set_visible_child(self.search_result)
        self.search_result.set_items([])


class HittaWindow(Gtk.Window):
    input: Gtk.TextView
    result_stack: ResultStack

    def __init__(self, app: HittaApp):
        super().__init__(application=app, name="hitta")
        self.set_size_request(600, -1)

        self.file_search_provider: SearchProvider = FileSearchProvider(
            self._on_search_results
        )
        self.app_search_provider: SearchProvider = AppSearchProvider(
            self._on_search_results
        )

        main_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=0, name="main-view"
        )

        self.input = Gtk.TextView(name="input")
        self.input.set_cursor_visible(False)
        self.input.set_accepts_tab(False)

        window_key_controller = Gtk.EventControllerKey()
        window_key_controller.connect("key-pressed", self._on_window_key_pressed)
        window_key_controller.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        self.add_controller(window_key_controller)

        self.result_stack = ResultStack(max_height=200)
        main_box.set_size_request(400, -1)
        main_box.set_valign(Gtk.Align.START)
        main_box.set_vexpand(True)
        main_box.append(self.input)
        main_box.append(self.result_stack)

        self.set_child(main_box)

        input_buffer = self.input.get_buffer()
        input_buffer.connect("changed", self._on_input_changed)

        self._search_timeout_id = None

        self.connect("map", self._on_window_mapped)

    def _on_window_key_pressed(
        self, controller: Gtk.EventController, keyval: int, keycode: int, state: int
    ) -> bool:
        self.input.grab_focus()

        if keyval == Gdk.KEY_Up or keyval == Gdk.KEY_KP_Up:
            self.result_stack.get_current_list().navigate_list(-1)
            return True
        elif keyval == Gdk.KEY_Down or keyval == Gdk.KEY_KP_Down:
            self.result_stack.get_current_list().navigate_list(1)
            return True
        elif keyval == Gdk.KEY_Return or keyval == Gdk.KEY_KP_Enter:
            self._on_submit()
            return True
        elif keyval == Gdk.KEY_Escape:
            if not self.result_stack.pop_stack():
                self.input.get_buffer().set_text("")
                self.result_stack.reset_to_search_results()
                self.set_visible(False)
            else:
                # Restore the previous search query when popping
                previous_query = self.result_stack.get_current_search_query()
                self.input.get_buffer().set_text(previous_query)
            return True
        elif keyval in (Gdk.KEY_Control_L, Gdk.KEY_Control_R):
            # Show actions when Ctrl is pressed
            current_list = self.result_stack.get_current_list()
            actions = current_list.get_actions()
            if actions:
                current_query = (
                    self.input.get_buffer()
                    .get_text(
                        self.input.get_buffer().get_start_iter(),
                        self.input.get_buffer().get_end_iter(),
                        False,
                    )
                    .strip()
                )
                self.result_stack.update_current_search_state(current_query)

                self.result_stack.push_actions(actions)
                # Clear input when showing actions
                self.input.get_buffer().set_text("")
            return True

        return False

    def _on_window_mapped(self, window: Gtk.Window):
        def focus_input():
            self.input.grab_focus()
            return False

        GLib.idle_add(focus_input)

    def _on_input_changed(self, buffer: Gtk.TextBuffer):
        if self._search_timeout_id is not None:
            _ = GLib.source_remove(self._search_timeout_id)
            self._search_timeout_id = None

        search_text = buffer.get_text(
            buffer.get_start_iter(), buffer.get_end_iter(), False
        ).strip()

        if not self.result_stack.is_at_search_level():
            self.result_stack.search_current_level(search_text)
        elif search_text:
            timeout = 100 if len(search_text) < 5 else 30
            self._search_timeout_id = GLib.timeout_add(
                timeout, self._perform_search, search_text
            )

    def _perform_search(self, search_text: str) -> bool:
        self._search_timeout_id = None

        self.file_search_provider.cancel_search()

        if search_text.startswith("'"):
            query = search_text[1:]
            if query:
                self.file_search_provider.search(query)
        else:
            self.app_search_provider.search(search_text)

        return False

    def _on_search_results(self, items: list[SearchResult] | None) -> None:
        if items is None:
            items = []

        self.result_stack.search_result.set_items(items)

    def _on_submit(self):
        buffer = self.input.get_buffer()
        self.result_stack.get_current_list().execute_default_action()
        buffer.set_text("")
        self.result_stack.reset_to_search_results()
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

    def on_usr1_signal(signum: object, frame: object):
        if app.window is not None:
            app.window.set_visible(True)

    signal.signal(signal.SIGUSR1, on_usr1_signal)

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
