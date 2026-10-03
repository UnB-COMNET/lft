import os
import subprocess
import time
from pathlib import Path


# Brief: Restores terminal formatting after Docker commands leave output misaligned
def restore_tty() -> None:
    if not os.isatty(1):
        return
    subprocess.run("stty sane", shell=True, stderr=subprocess.DEVNULL)


# Brief: Displays a countdown timer and pauses execution
def sleep_countdown(t=10) -> None:
    for i in range(t, 0, -1):
        print(f"  {i} seconds remaining ...", end="\r")
        time.sleep(1)
    print("                           ") # clears the line


# Brief: Prints an art banner for the experiment
def print_banner() -> None:
    art = r"""

      .oooooo.   oooooooooo.   ooooo     ooo 
     d8P'  `Y8b  `888'   `Y8b  `888b.     `8' 
    888           888      888  8 `88b.    8  
    888           888      888  8   `88b.  8  
    888           888      888  8     `88b.8  
    `88b    ooo   888     d88'  8       `888  
     `Y8bood8P'  o888bood8P'   o8o        `8  

    ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
    
             DASH TOPOLOGY EXPERIMENT
    """
    print(art)


# Brief: Appends a line to events.log under the given directory
def append_event(rep_dir: Path, line: str) -> None:
    rep_dir.mkdir(parents=True, exist_ok=True)
    with (rep_dir / "events.log").open("a", encoding="utf-8") as f:
        f.write(line.rstrip() + "\n")
