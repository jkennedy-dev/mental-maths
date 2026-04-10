import curses

from .app import main

if __name__ == "__main__":
    curses.wrapper(main)
