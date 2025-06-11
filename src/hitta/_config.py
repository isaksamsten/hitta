import os
import importlib
import importlib.resources

from gi.repository import Gtk

import logging


logging.basicConfig()
logger = logging.getLogger(__name__)


def load_system_style(filename: str = "style.css") -> Gtk.CssProvider:
    with (
        importlib.resources.files("hitta.resources").joinpath(filename).open("rb") as f
    ):
        provider = Gtk.CssProvider()
        css_data = f.read()
        provider.load_from_data(css_data)
        return provider


def load_user_style(filename: str = "style.css") -> Gtk.CssProvider | None:
    config_home = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    user_css_path = os.path.join(config_home, "hitta", filename)
    if os.path.isfile(user_css_path):
        with open(user_css_path, "rb") as f:
            user_provider = Gtk.CssProvider()
            css_data = f.read()
            user_provider.load_from_data(css_data)
            return user_provider


DEFAULT_CSS_PROVIDER = load_system_style(filename="style.css")
DEFAULT_DARK_CSS_PROVIDER = load_system_style(filename="style-dark.css")

DEFAULT_USER_CSS_PROVIDER = load_user_style(filename="style.css")
DEFAULT_DARK_USER_CSS_PROVIDER = load_user_style(filename="style-dark.css")
