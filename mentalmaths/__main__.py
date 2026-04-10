import curses

from .app import main


def run() -> None:
    curses.wrapper(main)


if __name__ == "__main__":
    run()
