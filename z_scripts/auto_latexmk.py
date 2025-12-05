#!/usr/bin/env python3

import multiprocessing
import os
import subprocess
import logging
import argparse
import shutil
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
import json


class ColoredFormatter(logging.Formatter):
    COLORS = {
        logging.DEBUG: "\033[34m",
        logging.INFO: "\033[0m",
        logging.WARNING: "\033[33m",
        logging.ERROR: "\033[31m",
    }
    RESET = "\033[0m"

    def format(self, record):
        color = self.COLORS.get(record.levelno, self.RESET)
        return f"{color}{super().format(record)}{self.RESET}"


def clean_all_aux_subdirs_if_exist(root_dir):
    for subdir, _, _ in os.walk(root_dir, topdown=True):
        aux_dir_path = os.path.join(subdir, ".aux").replace("\\", "/")
        if os.path.exists(aux_dir_path) and os.path.isdir(aux_dir_path):
            try:
                shutil.rmtree(aux_dir_path)
            except Exception as e:
                logging.error(f"Failed to delete {aux_dir_path}: {e}")


def run_single_compile_task(task):
    tex_file = task["tex_file"]
    subdir = task["subdir"]
    engine = task["engine"]

    out_dir = os.path.abspath(subdir).replace("\\", "/")
    aux_dir = os.path.abspath(os.path.join(subdir, ".aux")).replace("\\", "/")

    latex_full_command = [
        "latexmk",
        "-file-line-error",
        "-halt-on-error",
        "-interaction=nonstopmode",
        "-synctex=1",
        f"-{engine}",
        f"-auxdir={aux_dir}",
        f"-outdir={out_dir}",
        tex_file,
    ]

    logging.debug(f"Compiling {tex_file} ({engine})")
    logging.debug(f"Full command: {' '.join(latex_full_command)}")

    start_time = time.time()
    task_result = task.copy()
    try:
        result = subprocess.run(
            latex_full_command,
            cwd=subdir,
            capture_output=True,
            timeout=180,
        )

        if result.returncode == 0:
            logging.debug(f"Successfully compiled {tex_file}")
            task_result.update(
                {
                    "success": True,
                    "elapsed_time": time.time() - start_time,
                    "full_command": latex_full_command,
                }
            )

        else:
            logging.error(f"Failed to compile {tex_file}")
            task_result.update(
                {
                    "success": False,
                    "elapsed_time": time.time() - start_time,
                    "error_msg": result.stderr.decode("utf-8"),
                    "full_command": latex_full_command,
                }
            )

    except subprocess.TimeoutExpired:
        logging.error(f"Compilation of {tex_file} timed out.")
        task_result.update(
            {
                "success": False,
                "elapsed_time": time.time() - start_time,
                "error_msg": "Compilation timed out.",
                "full_command": latex_full_command,
            }
        )
    except Exception as e:
        logging.error(f"Error during compilation of {tex_file}: {e}")
        task_result.update(
            {
                "success": False,
                "elapsed_time": time.time() - start_time,
                "error_msg": f"{e}",
                "full_command": latex_full_command,
            }
        )

    return task_result


def run_compile_tasks(tasks, quiet_in_process):
    task_nums = len(tasks)
    task_cnt = 0
    task_results = []

    print(f"Processing {len(tasks)} tasks in parallel...")

    with ProcessPoolExecutor() as executor:
        futures = {
            executor.submit(run_single_compile_task, task): task for task in tasks
        }
        for future in as_completed(futures):
            try:
                task_result = future.result()
                task_results.append(task_result)

                show_current_compile_result(
                    task_result, task_nums, task_cnt, quiet_in_process
                )
            except Exception as e:
                logging.error(f"Error running task: {futures[future][0]} ({e})")

            task_cnt += 1

    return task_results


def is_main_tex_file(tex_file_path, only_include_mode: bool):
    """
    Detect if a .tex file is a main file and decide whether to compile based on comments and mode:
    - Default mode: Compile unless marked '% auto-latexmk exclude' or '% auto-latexmk skip'.
    - only_include mode: Compile only if marked '% auto-latexmk include'.
    """

    exclude_flag = False
    include_flag = False
    try:
        with open(tex_file_path, "r", encoding="utf-8") as f:
            for _ in range(3):  # only check first three lines
                line = f.readline()
                if not line:
                    break
                line_strip = line.strip().lower()
                if line_strip.startswith(r"% auto-latexmk"):
                    if "exclude" in line_strip or "skip" in line_strip:
                        exclude_flag = True

                if line_strip.startswith(r"% auto-latexmk"):
                    if "include" in line_strip:
                        include_flag = True

            f.seek(0)
            content = f.read()
            has_docclass = "\\documentclass" in content

        if not has_docclass:
            return False

        if only_include_mode:
            return include_flag
        else:
            return not exclude_flag

    except Exception as e:
        logging.error(f"Error reading {tex_file_path}: {e}")
        return False


def get_tex_engine(tex_file_path, default_engine):
    try:
        # check shebang
        with open(tex_file_path, "r", encoding="utf-8") as f:
            first_line = f.readline().strip()
            if first_line.startswith("% !TEX"):
                first_line = first_line.strip()
                if "xelatex" in first_line:
                    return ("xelatex", first_line)
                elif "pdflatex" in first_line:
                    return ("pdflatex", first_line)
                elif "lualatex" in first_line:
                    return ("lualatex", first_line)

        # use xelatex if found ctex or ctex* before \begin{document}
        with open(tex_file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if r"\begin{document}" in line:
                    break
                if "ctex" in line:
                    return ("xelatex", line)

    except Exception as e:
        logging.error(f"Error reading {tex_file_path}: {e}")
        return (default_engine, None)

    return (default_engine, None)


def generate_compile_tasks(root_dir, default_engine, only_include_mode: bool):
    tasks = []
    SKIP_DIRS = [".git", ".aux"]
    for subdir, dirs, files in os.walk(root_dir, topdown=True):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]

        tex_file_list = [f for f in files if f.endswith(".tex")]  # *.tex
        for tex_file_item in tex_file_list:
            tex_file = os.path.abspath(os.path.join(subdir, tex_file_item)).replace(
                "\\", "/"
            )
            if is_main_tex_file(tex_file, only_include_mode):
                engine, append_info = get_tex_engine(tex_file, default_engine)
                if engine == "pdflatex":
                    engine = "pdf"

                tasks.append(
                    {
                        "tex_file": tex_file,  # full path
                        "subdir": subdir.replace("\\", "/"),
                        "engine": engine,
                        "append_info": append_info,
                    }
                )
    return tasks


def show_current_compile_result(task_result, task_nums, task_cnt, quiet_in_process):
    tex_file = task_result["tex_file"]
    engine = task_result["engine"]
    elapsed_time = task_result["elapsed_time"]

    width = len(str(task_nums))
    counter = f"{task_cnt+1:>{width}}/{task_nums}"
    if not task_result["success"]:  # failed
        print(
            f"\033[31m [x] ({counter}) {tex_file} ({engine}) ({elapsed_time:.2f}s)\033[0m"
        )
        print(f"\033[35mfull_command:\n{task_result['full_command']}\033[0m")
        print(f"\033[35merror_msg:\n{task_result['error_msg']}\033[0m")
    elif not quiet_in_process:  # success and not quiet
        print(
            f"\033[32m [✓] ({counter}) {tex_file} ({engine}) ({elapsed_time:.2f}s)\033[0m"
        )
    else:
        # do nothing
        pass


def show_compile_results(tasks_results):
    sucess_cnt = 0
    failed_cnt = 0

    for task_result in tasks_results:
        if task_result["success"]:
            sucess_cnt += 1
        else:
            failed_cnt += 1

    print(f"Succeeded: {sucess_cnt}   Failed: {failed_cnt}")

    if failed_cnt == 0:
        return

    print("Failed tasks:")
    for task_result in tasks_results:
        if not task_result["success"]:
            print(
                f"\033[31m [x] {task_result['tex_file']} ({task_result['engine']})\033[0m"
            )
            print(f"\033[35mfull_command:\n{task_result['full_command']}\033[0m")
            print(f"\033[35merror_msg:\n{task_result['error_msg']}\033[0m")


def output_to_json_logfile(tasks_results):
    try:
        with open("auto-latexmk.log", "w", encoding="utf-8") as f:
            for task_result in tasks_results:
                json.dump(task_result, f, ensure_ascii=False, indent=4)
                f.write("\n")
        logging.debug("Compilation results successfully written to auto-latexmk.log")
    except Exception as e:
        logging.error(f"Error writing to log file: {e}")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Compile or clean .tex files in the given directory."
    )
    parser.add_argument(
        "root_dir",
        nargs="?",
        default=os.getcwd(),
        type=str,
        help="Root directory to search for .tex files (default: current working directory).",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose output"
    )
    parser.add_argument(
        "-q", "--quiet", action="store_true", help="Quiet mode: only show errors."
    )

    parser.add_argument(
        "--engine",
        type=str,
        choices=["xelatex", "pdflatex", "lualatex"],
        default="xelatex",
        help="Set the default LaTeX engine (default: xelatex).",
    )

    parser.add_argument(
        "--pre-clean",
        action="store_true",
        help="Clean .aux/ directories before compiling.",
    )
    parser.add_argument(
        "--no-compile",
        action="store_true",
        help="Do not compile .tex files.",
    )
    parser.add_argument(
        "--only-include",
        action="store_true",
        help="If set, only compile files explicitly marked with '%% auto-latexmk include'.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show which .tex tasks would be compiled, without actually running compilation.",
    )

    return parser.parse_args()


def main():
    args = parse_args()

    handler = logging.StreamHandler()
    handler.setFormatter(ColoredFormatter("%(message)s"))
    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(logging.DEBUG if args.verbose else logging.INFO)

    logging.debug(f"Root directory: {args.root_dir}")
    logging.debug(f"Default engine: {args.engine}")
    logging.debug(f"Only include mode: {args.only_include}")

    if args.dry_run:
        tasks = generate_compile_tasks(
            root_dir=args.root_dir,
            default_engine=args.engine,
            only_include_mode=args.only_include,
        )
        task_nums = len(tasks)
        print(f"[Dry-run] {task_nums} tasks detected:")
        width = len(str(task_nums))
        for task_cnt, task in enumerate(tasks, 0):
            counter = f"{task_cnt+1:>{width}}/{task_nums}"
            tex = task["tex_file"]
            engine = task["engine"]
            print(f"  ({counter}) {tex}  ({engine})")

        print("Dry-run finished. No compilation or pre-clean executed.")
        return

    if args.pre_clean:
        clean_all_aux_subdirs_if_exist(args.root_dir)
        print("Pre-clean completed.")

    if not args.no_compile:
        tasks = generate_compile_tasks(
            root_dir=args.root_dir,
            default_engine=args.engine,
            only_include_mode=args.only_include,
        )
        tasks_results = run_compile_tasks(tasks, quiet_in_process=args.quiet)
        show_compile_results(tasks_results)

        if args.verbose:
            output_to_json_logfile(tasks_results)
    else:
        print("Compilation skipped.")


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
