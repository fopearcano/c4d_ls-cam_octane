"""
ls_ui.py
--------
User-facing feedback helpers for the C4D_ls-cam plugin.

This module is intentionally thin in the skeleton. The command plugin is
fire-and-forget -- it does not need a dialog. We centralize status messaging
here so a future GUI (e.g. a GeDialog with a properties panel) can plug in
without touching the rig builder.
"""

import c4d


def status(message):
    """Write *message* to the C4D status bar (bottom-left of the editor)."""
    try:
        c4d.StatusSetText("[C4D_ls-cam] {0}".format(message))
    except Exception:
        # StatusSetText is editor-only; tolerate headless contexts (Cmd line).
        pass


def info(message):
    """Show a non-blocking informational dialog."""
    c4d.gui.MessageDialog(message, type=c4d.GEMB_OK)


def error(message):
    """Show a blocking error dialog. Use only for unrecoverable failures."""
    c4d.gui.MessageDialog(
        "C4D_ls-cam error:\n\n{0}".format(message),
        type=c4d.GEMB_OK,
    )


def log(message, debug=False):
    """
    Print *message* to the C4D Python console.

    Pass debug=True for verbose-only logs; the caller is expected to gate
    those on the controller's debug_mode user-data flag.
    """
    if debug:
        print("[C4D_ls-cam][debug] {0}".format(message))
    else:
        print("[C4D_ls-cam] {0}".format(message))
