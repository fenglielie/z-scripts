#!/usr/bin/env python3

import os
import shutil
from datetime import datetime
import argparse
import random

HOME_DIR = os.path.expanduser("~")
TRASH_DIR = os.path.join(HOME_DIR, ".trash")
EXE_NAME = "rm2trash"


def ensure_trash_dir():
    """Ensure the main trash directory exists."""
    if not os.path.exists(TRASH_DIR):
        os.makedirs(TRASH_DIR)


def create_trash_subdir():
    """Create a subdirectory in trash based on date and time, avoiding name collisions."""
    date_dir = datetime.now().strftime("%Y%m%d")
    time_random_dir = datetime.now().strftime("%H%M%S") + f"-{random.randint(100, 999)}"
    full_path = os.path.join(TRASH_DIR, date_dir, time_random_dir)
    os.makedirs(full_path, exist_ok=True)
    return full_path


def log_operation(*, log_path, timestamp, cwd, command, moved_items):
    """Log the operation details to the log file."""
    with open(log_path, "a") as log_file:
        log_file.write(f"Timestamp: {timestamp}\n")
        log_file.write(f"Current Directory: {cwd}\n")
        log_file.write(f"Command: {command}\n")
        for original_path, target_path in moved_items:
            log_file.write(f"Moved '{original_path}' to '{target_path}'\n")
        log_file.write("\n")


def confirm_delete(file_path):
    response = input(f"Are you sure you want to move '{file_path}' to trash? (y/n): ")
    return response.lower() in ["y", "yes"]


def move_to_trash(
    file_path,
    trash_path,
    moved_items,
    recursive=False,
    interactive=False,
    quiet=False,
):
    # File or directory doesn't exist
    if not os.path.exists(file_path):
        print(f"{EXE_NAME}: cannot remove '{file_path}': No such file or directory.")
        return

    # Remove trailing '/' if directory
    if os.path.isdir(file_path):
        file_path = os.path.normpath(file_path)

    # Non-empty directory requires -r flag
    if os.path.isdir(file_path) and os.listdir(file_path):
        if not recursive:
            print(
                f"{EXE_NAME}: cannot remove '{file_path}': Directory not empty. Use -r to remove it."
            )
            return

    # Confirm deletion if interactive mode is enabled
    if interactive and not confirm_delete(file_path):  # Not confirmed
        print(f"Skipped '{file_path}'.")
        return

    try:
        target_path = os.path.join(trash_path, os.path.basename(file_path))
        if os.path.isdir(file_path):  # Directory handling
            shutil.copytree(file_path, target_path)
            shutil.rmtree(file_path)
        else:  # File or empty directory
            shutil.move(file_path, target_path)

        moved_items.append((file_path, target_path))
        if not quiet:
            print(f"{EXE_NAME}: Moved '{file_path}' to trash at '{target_path}'.")

    except Exception as e:
        print(f"{EXE_NAME}: Failed to move '{file_path}' to trash. Error: {e}")
        if os.path.isdir(trash_path) and not os.listdir(trash_path):
            os.rmdir(trash_path)


def main():
    parser = argparse.ArgumentParser(
        description="Move files and directories to ~/.trash instead of deleting them."
    )
    parser.add_argument(
        "files", nargs="+", help="Files or directories to move to trash."
    )
    parser.add_argument(
        "-i", "--interactive", action="store_true", help="Prompt before every removal."
    )
    parser.add_argument(
        "-r",
        "--recursive",
        action="store_true",
        help="Remove directories and their contents recursively.",
    )
    parser.add_argument(
        "-q", "--quiet", action="store_true", help="Suppress output for moved items."
    )

    args = parser.parse_args()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cwd = os.getcwd()
    command = " ".join([EXE_NAME] + args.files)
    log_file_path = os.path.join(
        TRASH_DIR, f"{datetime.now().strftime('%Y%m')}-trash.log"
    )

    ensure_trash_dir()
    trash_path = create_trash_subdir()
    moved_items = []

    for file in args.files:
        move_to_trash(
            file,
            trash_path=trash_path,
            moved_items=moved_items,
            recursive=args.recursive,
            interactive=args.interactive,
            quiet=args.quiet,
        )

    if moved_items:
        log_operation(
            log_path=log_file_path,
            timestamp=timestamp,
            cwd=cwd,
            command=command,
            moved_items=moved_items,
        )

    if os.path.isdir(trash_path) and not os.listdir(trash_path):
        os.rmdir(trash_path)


if __name__ == "__main__":
    main()
