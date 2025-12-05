#!/usr/bin/env python3

import subprocess
import argparse
from pathlib import Path


class Colors:
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    RED = "\033[31m"
    RED_BG = "\033[41m"
    CYAN = "\033[36m"
    MAGENTA = "\033[35m"
    RESET = "\033[0m"


def colorize(text, color_code, use_color: bool):
    if use_color:
        return f"{color_code}{text}{Colors.RESET}"
    else:
        return text


def run_git_command(repo_path, args, verbosity: int, use_color: bool):
    """Run git command in the given repository directory"""
    cmd = ["git"] + args
    if verbosity >= 3:
        print(
            colorize(
                f"[DEBUG] Running command: {' '.join(cmd)}",
                Colors.YELLOW,
                use_color,
            )
        )
    try:
        result = subprocess.run(
            cmd, cwd=repo_path, text=True, capture_output=True, check=True
        )
        return result.stdout.rstrip()
    except subprocess.CalledProcessError as e:
        return f"[ERROR] {e.stderr.strip()}"


def get_git_config(repo_path: Path, key: str):
    """Return (value:str or None, source:str)"""
    for scope in ["--local", "--global"]:
        cmd = ["git", "config", scope, "--get", key]
        try:
            result = subprocess.run(
                cmd, cwd=repo_path, text=True, capture_output=True, check=True
            )
            value = result.stdout.strip()
            if value:
                return value, "local" if scope == "--local" else "global"
        except subprocess.CalledProcessError:
            continue
    return None, "not set"


def check_sync_status(repo_path: Path, verbosity: int, do_fetch: bool, use_color: bool):
    """Check sync status for all local branches with aligned output"""
    branches = run_git_command(repo_path, ["branch"], verbosity, use_color).splitlines()
    branches = [b.strip().lstrip("* ").strip() for b in branches]

    if do_fetch:
        fetch_result = run_git_command(
            repo_path, ["fetch", "--quiet"], verbosity, use_color
        )
        if "[ERROR]" in fetch_result or "fatal" in fetch_result.lower():
            print(
                colorize(
                    f"[WARNING] git fetch failed for {repo_path.name}",
                    Colors.YELLOW,
                    use_color,
                )
            )

    if not branches:
        print(colorize("No local branches found.", Colors.YELLOW, use_color))
        return

    max_len = max(len(branch) for branch in branches)

    for branch in branches:
        branch_display = f"{f'{branch}':<{max_len}}"

        behind_ahead = run_git_command(
            repo_path,
            ["rev-list", "--left-right", "--count", f"origin/{branch}...{branch}"],
            verbosity,
            use_color,
        )
        try:
            behind, ahead = map(int, behind_ahead.split())
            status = []
            if ahead == 0 and behind == 0:
                status.append(
                    colorize("Up-to-date with remote", Colors.GREEN, use_color)
                )
            else:
                if ahead > 0:
                    status.append(
                        colorize(f"Ahead by {ahead}", Colors.YELLOW, use_color)
                    )
                if behind > 0:
                    status.append(
                        colorize(f"Behind by {behind}", Colors.RED, use_color)
                    )
            print(f"Branch {branch_display}  {' | '.join(status)}")
        except Exception:
            print(
                f"Branch {branch_display}  "
                + colorize(
                    "Cannot determine sync with remote (maybe no upstream set)",
                    Colors.YELLOW,
                    use_color,
                )
            )


def show_repo_info(repo_path: Path, verbosity: int, do_fetch: bool, use_color: bool):
    repo_path = repo_path.resolve()

    if not (repo_path / ".git").exists():
        print(
            colorize(
                f"[ERROR] {repo_path} is not a git repository", Colors.RED_BG, use_color
            )
        )
        return

    print(f"{colorize('Repository:', Colors.CYAN, use_color)} {repo_path}")

    for key in ["user.name", "user.email"]:
        value, source = get_git_config(repo_path, key)
        if value:
            display_color = Colors.GREEN
        else:
            display_color = Colors.RED

        print(
            f"{colorize(key + ':', Colors.CYAN, use_color)} "
            f"{colorize(value, display_color, use_color)} ({source})"
        )

    branch = run_git_command(
        repo_path, ["rev-parse", "--abbrev-ref", "HEAD"], verbosity, use_color
    )
    print(
        f"{colorize('Current branch:', Colors.CYAN, use_color)} {colorize(branch, Colors.GREEN, use_color)}"
    )

    status = run_git_command(repo_path, ["status", "-s"], verbosity, use_color)
    print(f"{colorize('Working tree: ', Colors.CYAN, use_color)}", end="")
    if not status:
        print(colorize("clean", Colors.GREEN, use_color))
    else:
        print(colorize("uncommitted changes present", Colors.YELLOW, use_color))
        print(colorize(status, Colors.YELLOW, use_color))

    check_sync_status(repo_path, verbosity, do_fetch, use_color)

    if verbosity >= 1:
        last_commit = run_git_command(
            repo_path,
            ["log", "-1", "--pretty=format:%h | %an <%ae> | %ar | %s"],
            verbosity,
            use_color,
        )
        print(f"{colorize('Last commit:', Colors.CYAN, use_color)} {last_commit}")

        remotes = run_git_command(repo_path, ["remote", "-v"], verbosity, use_color)
        print(f"{colorize('Remotes:', Colors.CYAN, use_color)}")
        print(remotes if remotes else colorize("  (none)", Colors.YELLOW, use_color))

    if verbosity >= 2:
        branches = run_git_command(repo_path, ["branch", "-vv"], verbosity, use_color)
        print(f"{colorize('Local branches:', Colors.CYAN, use_color)}")
        print(branches if branches else colorize("  (none)", Colors.YELLOW, use_color))

        remote_branches = run_git_command(
            repo_path, ["branch", "-r"], verbosity, use_color
        )
        print(f"{colorize('Remote branches:', Colors.CYAN, use_color)}")
        print(
            remote_branches
            if remote_branches
            else colorize("  (none)", Colors.YELLOW, use_color)
        )


def args_parse():

    def str2bool(v):
        if isinstance(v, bool):
            return v
        if v.lower() in ("yes", "true", "t", "1"):
            return True
        elif v.lower() in ("no", "false", "f", "0"):
            return False
        else:
            raise argparse.ArgumentTypeError("Boolean value expected.")

    parser = argparse.ArgumentParser(
        description="Show information about one or more Git repositories."
    )
    parser.add_argument(
        "repos",
        nargs="*",
        type=Path,
        help="Paths to Git repositories (must specify at least one)",
    )
    parser.add_argument(
        "-c",
        "--config",
        type=Path,
        default=None,
        help="Path to config file listing repositories (one per line)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase verbosity (-v for detailed, -vv for very detailed, -vvv for debugging)",
    )
    parser.add_argument(
        "--color",
        type=str2bool,
        default=True,
        help="Enable or disable colored output (default: True). Use --color=False to disable.",
    )
    parser.add_argument(
        "-f",
        "--fetch",
        action="store_true",
        help="Run 'git fetch' before checking branch sync status (default: False)",
    )

    return parser.parse_args()


def main():
    args = args_parse()

    if args.repos and args.config:
        print("[ERROR] Cannot specify both repository paths and --config option.")
        return

    repos = args.repos

    if not repos:
        config_path = args.config or Path.home() / ".config/git-check/repos.txt"

        if config_path.exists():
            with config_path.open("r", encoding="utf-8") as f:
                repos = [
                    Path(line.strip())
                    for line in f
                    if line.strip() and not line.strip().startswith("#")
                ]

            if repos:
                print(f"[INFO] Using config file {config_path}")
            else:
                print(f"[WARNING] Config file {config_path} is empty.")

        else:
            if args.verbose >= 1:
                print(
                    f"[INFO] No repositories specified and config file not found at {config_path}"
                )

    if not repos:
        current = Path.cwd()
        if (current / ".git").exists():
            repos = [current]
            if args.verbose >= 1:
                print(f"[INFO] Using current directory: {current}")
        else:
            print(
                "[ERROR] No repositories specified, config file not found, and current directory is not a git repo."
            )
            return

    repo_count = len(repos)
    if repo_count == 1:
        show_repo_info(
            repos[0],
            verbosity=args.verbose,
            do_fetch=args.fetch,
            use_color=args.color,
        )
    else:
        for idx, repo in enumerate(repos, start=1):
            print("\n" + "=" * 60)
            print(f"[{idx}/{len(repos)}]", end=" ")
            show_repo_info(
                repo,
                verbosity=args.verbose,
                do_fetch=args.fetch,
                use_color=args.color,
            )


if __name__ == "__main__":
    main()
