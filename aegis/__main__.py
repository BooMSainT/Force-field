import argparse
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description='Aegis Field — Kali desktop monitoring')
    parser.add_argument('--adapter', help='Bluetooth adapter, e.g. hci0')
    parser.add_argument('--probe-interface', help='Override automatic monitor-adapter selection')
    parser.add_argument('--data-dir', type=Path, default=Path(os.environ.get('XDG_DATA_HOME', str(Path.home()/'.local/share')))/'aegis-field')
    args = parser.parse_args()
    os.umask(0o077)
    args.data_dir.mkdir(parents=True,exist_ok=True)
    # One process owns the persistent database and encounter lifecycle.
    import fcntl
    lock = (args.data_dir/'app.lock').open('w')
    try:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:
        parser.exit(1,'Aegis Field is already running.\n')
    from .ui import App
    App(args).mainloop()


if __name__ == '__main__':
    main()
