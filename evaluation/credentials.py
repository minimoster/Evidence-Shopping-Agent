"""Interactive-only transient secret input. Never fall back to echoed stdin."""
import getpass
import sys
import warnings


def read_transient_key():
    if not sys.stdin.isatty():
        raise ValueError('no interactive terminal: refusing echoed or redirected credential input')
    with warnings.catch_warnings():
        warnings.simplefilter('error', getpass.GetPassWarning)
        return getpass.getpass('Relay API key (hidden, not saved): ')
