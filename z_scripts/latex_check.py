#!/usr/bin/env python3
import os
import sys
import argparse
import logging
from abc import ABC, abstractmethod
import re


class ColorFormatter(logging.Formatter):
    COLORS = {
        logging.DEBUG: "\033[34m",
        logging.INFO: "\033[0m",
        logging.WARNING: "\033[33m",
        logging.ERROR: "\033[31m",
    }
    RESET = "\033[0m"

    def format(self, record):
        color = self.COLORS.get(record.levelno, self.RESET)
        record.levelname = f"{color}[{record.levelname}]{self.RESET}"
        record.msg = f"{color}{record.msg}{self.RESET}"
        return super().format(record)


def setup_logger(use_color=True, level=logging.WARNING):
    logger = logging.getLogger("latex_check")
    logger.setLevel(level)
    ch = logging.StreamHandler()
    ch.setLevel(level)
    formatter = (
        ColorFormatter("%(levelname)s %(message)s")
        if use_color
        else logging.Formatter("%(levelname)s %(message)s")
    )
    ch.setFormatter(formatter)
    logger.addHandler(ch)
    return logger


class Checker(ABC):
    name = "BaseChecker"

    @abstractmethod
    def check(self, file_path: str):
        """return a list of (line_number, column, message, level)"""
        pass


class DollarSignSpacingChecker(Checker):
    PUNCTUATIONS = " -_~.,!?:;()[]{}\\'。 、，！？：；（）\n"
    name = "DollarSignSpacing"

    def check(self, file_path: str):
        errors = []
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        for line_number, line_raw in enumerate(lines, start=1):
            line = line_raw.split("%", 1)[0]
            dollar_indices = [i for i, c in enumerate(line) if c == "$"]
            for idx, cur_idx in enumerate(dollar_indices):
                if idx % 2 == 0:
                    if (
                        cur_idx > 0
                        and line[cur_idx - 1]
                        not in DollarSignSpacingChecker.PUNCTUATIONS
                    ):
                        errors.append(
                            (line_number, cur_idx, "Missing space before '$'", "error")
                        )
                else:

                    if (
                        cur_idx < len(line) - 1
                        and line[cur_idx + 1]
                        not in DollarSignSpacingChecker.PUNCTUATIONS
                    ):
                        errors.append(
                            (line_number, cur_idx, "Missing space after '$'", "error")
                        )
        return errors


class ChinesePunctuationChecker(Checker):
    name = "ChinesePunctuation"
    CHINESE_PUNCTUATIONS = "。，、：；！？（）《》“”‘’"

    @staticmethod
    def is_chinese_document(lines, min_consecutive=5):
        for line in lines:
            content = line.split("%", 1)[0]
            count = 0
            for c in content:
                if "\u4e00" <= c <= "\u9fff":
                    count += 1
                    if count >= min_consecutive:
                        return True
                else:
                    count = 0
        return False

    def check(self, file_path: str):
        errors = []
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        if self.is_chinese_document(lines):
            return errors
        for line_number, line_raw in enumerate(lines, start=1):
            line = line_raw.split("%", 1)[0]
            for idx, c in enumerate(line):
                if c in ChinesePunctuationChecker.CHINESE_PUNCTUATIONS:
                    errors.append(
                        (line_number, idx, "Unexpected Chinese punctuation", "error")
                    )
        return errors


class ConsecutiveBlankLinesChecker(Checker):
    name = "ConsecutiveBlankLines"

    def __init__(self, threshold=4):
        self.threshold = threshold

    def check(self, file_path: str):
        errors = []
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        blank_count = 0
        start_line = None
        for line_number, line in enumerate(lines, start=1):
            if line.strip() == "":
                if blank_count == 0:
                    start_line = line_number
                blank_count += 1
            else:
                if blank_count > self.threshold:
                    errors.append(
                        (
                            start_line,
                            None,
                            f"{blank_count} consecutive blank lines",
                            "warning",
                        )
                    )
                blank_count = 0
                start_line = None
        if blank_count > self.threshold:
            errors.append(
                (start_line, None, f"{blank_count} consecutive blank lines", "warning")
            )
        return errors


class MathFontChecker(Checker):
    """
    error: \\mathbb{abc123}, \\mathcal{abc123}, \\mathfrak{abc123}
    warning: \\mathrm{x}, \\mathit{x}, \\mathbf{x}, \\mathsf{x}, \\mathtt{x},
            where x = Delta / delta / varDelta / vardelta
    """

    name = "MathFontChecker"

    FORBIDDEN_FONTS = (r"\\mathbb", r"\\mathcal", r"\\mathfrak")
    WARN_FONTS = (r"\\mathrm", r"\\mathit", r"\\mathbf", r"\\mathsf", r"\\mathtt")

    _re_lower = re.compile(r"[a-z]")
    _re_digit = re.compile(r"[0-9]")

    _GREEK_CAPITALS = "Gamma|Delta|Theta|Lambda|Xi|Pi|Sigma|Upsilon|Phi|Psi|Omega"

    _GREEK_NAMES = (
        "alpha|beta|gamma|delta|epsilon|zeta|eta|theta|iota|kappa|"
        "lambda|mu|nu|xi|pi|rho|sigma|tau|upsilon|phi|chi|psi|omega|"
        "varepsilon|vartheta|varpi|varrho|varsigma|varphi|"
        "Gamma|Delta|Theta|Lambda|Xi|Pi|Sigma|Upsilon|Phi|Psi|Omega"
    )

    _re_greek_any = re.compile(r"\b\\(?:" + _GREEK_NAMES + r")\b")

    # group(1) = cmd, group(2) = content
    _pattern_template = r"({font})\{{([^}}]*)\}}"

    def check(self, file_path: str):
        results = []

        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        for lineno, raw in enumerate(lines, start=1):
            line = raw.split("%", 1)[0]
            if not line:
                continue

            # ---- forbidden cases ----
            for font in self.FORBIDDEN_FONTS:
                pattern = re.compile(self._pattern_template.format(font=font))
                for m in pattern.finditer(line):
                    cmd = m.group(1)
                    content = m.group(2)

                    col = m.start(1)

                    if self._re_lower.search(content):
                        msg = f"Forbidden: {cmd} used on lowercase letter inside '{{...}}' (content: {content})"
                        results.append((lineno, col, msg, "error"))

                    if self._re_digit.search(content):
                        msg = f"Forbidden: {cmd} used on digit inside '{{...}}' (content: {content})"
                        results.append((lineno, col, msg, "error"))

                    if re.search(r"\\(?:" + self._GREEK_CAPITALS + r")\b", content):
                        msg = f"Forbidden: {cmd} used on uppercase Greek letter inside '{{...}}' (content: {content})"
                        results.append((lineno, col, msg, "error"))

            # ---- warn cases ----
            for font in self.WARN_FONTS:
                pattern = re.compile(self._pattern_template.format(font=font))
                for m in pattern.finditer(line):
                    cmd = m.group(1)
                    content = m.group(2)
                    col = m.start(1)

                    if self._re_greek_any.search(content):
                        msg = f"Suspicious: {cmd} applied to Greek letter inside '{{...}}' (content: {content})"
                        results.append((lineno, col, msg, "warning"))

        return results


def collect_tex_files(root="."):
    tex_files = []
    for dirpath, _, files in os.walk(root):
        for f in files:
            if f.endswith(".tex"):
                tex_files.append(os.path.join(dirpath, f).replace("\\", "/"))
    return tex_files


def run_checkers_on_single_file(file_path, checkers):
    file_errors = []
    for checker in checkers:
        file_errors.extend(checker.check(file_path))
    return file_errors


def main():
    parser = argparse.ArgumentParser(
        description="Check LaTeX files for formatting issues"
    )
    parser.add_argument(
        "--no-color", action="store_true", help="Disable colored output"
    )
    parser.add_argument(
        "--debug", action="store_true", help="Set log level to DEBUG (default: INFO)"
    )
    args = parser.parse_args()
    if args.debug:
        log_level = logging.DEBUG
    else:
        log_level = logging.INFO

    checkers = [
        DollarSignSpacingChecker(),
        ChinesePunctuationChecker(),
        ConsecutiveBlankLinesChecker(),
        MathFontChecker(),
    ]

    logger = setup_logger(use_color=not args.no_color, level=log_level)
    if args.debug:
        logger.debug("Enabled checkers:")
        for chk in checkers:
            logger.debug(f"  - {chk.name}")

    total_errors = 0
    total_warnings = 0
    MAX_FILE_NUM_TO_SHOW = 20

    tex_files = collect_tex_files()
    logger.info(f"Found {len(tex_files)} .tex files to check")
    for file in tex_files:
        logger.debug(f"Checking: {file}")
        file_errors = run_checkers_on_single_file(file, checkers)
        if file_errors:
            logger.error(f"Check failed: {file}")
        else:
            logger.debug(f"Check passed: {file}")
        for idx, e in enumerate(file_errors, start=1):
            if idx > MAX_FILE_NUM_TO_SHOW and not args.debug:
                logger.warning("... too many issues, suppressing further output ...")
                break

            line, col, msg, level = e
            loc = f"{line}" + (f":{col}" if col is not None else "")
            if level == "error":
                logger.error(f"{msg} at {file}:{loc}")
                total_errors += 1
            else:
                logger.warning(f"{msg} at {file}:{loc}")
                total_warnings += 1

    if total_errors == 0 and total_warnings == 0:
        logger.info("latex-check: pass")
    else:
        logger.error(
            f"latex-check: {total_errors} error(s), {total_warnings} warning(s)"
        )

    sys.exit(total_errors)


if __name__ == "__main__":
    main()
