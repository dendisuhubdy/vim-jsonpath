#!/usr/bin/env python3

from __future__ import print_function
import sys
import re

# open() doesn't support encoding in python2, but codecs.open does
if (sys.version_info < (3, 0)):
    from codecs import open

def scan_stream(stream, path=[], line=-1, column=-1, verbose=False):
    """
    Scans the given stream (CountingStream instance) for a given path, or
    line/column offset.

    If a path is specified the function will search for it, returning (line,
    column) of where the value is declared if found.

    If a positive line and column is provided the function will instead return
    the path (as a list) at that offset.
    """
    searching = len(path) > 0

    if not searching and (line < 0 or column < 0):
        raise ValueError("Must provide a non-empty 'path' or 'line' and 'column' >=0")

    # Parser state
    in_key = False
    quoted = False
    key = "" # using a string array seems to perform worse
    stack = [] # contains path components (strings), indices (ints), and -1 for unvisited objects
    stack_strings = [] # stringified path components for quick equality checking with `path`

    while True:
        # 0 = unchanged, 1 = added/modified, 2 = removed
        stack_modified = 0
        char = stream.read()

        if char == "":
            break

        if verbose:
            print("%d:%d %c  quoted=%s in_key=%s key=%s",
                stream.lnum,
                stream.cnum,
                char,
                quoted,
                in_key,
                key)

        if char == "\\":
            decoded = read_escape(stream)
            if in_key:
                key += decoded

        elif quoted and in_key and char != '"':
            key += char

        elif char == '"':
            if in_key and not quoted:
                key = ""
            quoted = not quoted

        elif char == ":":
            stack[-1] = key
            stack_strings[-1] = key
            stack_modified = 1
            in_key = False

        elif char == "{":
            stack.append(-1)
            stack_strings.append("")
            in_key = True

        elif char == "[":
            stack.append(0)
            stack_strings.append("0")
            stack_modified = 1
            in_key = False
            
        elif char == "]" or char == "}":
            stack.pop()
            stack_strings.pop()
            stack_modified = -1
        
        elif char == ",":
            # If currently within array
            if isinstance(stack[-1], int) and stack[-1] >= 0:
                stack[-1] = stack[-1] + 1
                stack_strings[-1] = str(stack[-1])
                stack_modified = 1
            else:
                in_key = True
        
        if stack_modified != 0:
            if verbose:
                print("%d:%d %c %c %s" % (
                    stream.lnum,
                    stream.cnum,
                    char,
                    "+" if stack_modified > 0 else "-",
                    ".".join(stack_strings)))

            if stack_modified == 1 and searching and stack_strings == path:
                stream.skip_spaces()
                return (stream.lnum, stream.cnum)

        # Stop parsing when target line/column is reached
        if (
            not searching and not in_key and stream.lnum >= line and
            (stream.lnum > line or stream.cnum >= column)
        ):
            if len(stack) > 0 and stack[-1] == -1:
                stack.pop() # clean up temporary stack entry
                stack_strings.pop()
            return stack

    return None


ESCAPE_MAP = {"n":"\n","t":"\t","r":"\r","b":"\b","f":"\f"}

def read_escape(stream):
    """
    Reads a escape code from stream, returning the decoded character.
    """
    char = stream.read()
    mapped = ESCAPE_MAP.get(char, None)
    if mapped is not None:
        return mapped
    elif char != "u":
        return char
    # Decode escaped unicode (\u1234)
    sv = 12
    r = 0
    for _ in range(0, 4):
        r |= int(stream.read(), 16) << sv
        sv -= 4
    return unichr(r)


class CountingStream:
    """
    Wraps a readable text stream accessible one character at a time.
    Keeps track of current line (lnum) and column number (cnum).
    """
    def __init__(self):
        self.lnum = 1
        self.cnum = 1

    def _read(self):
        raise TypeError("Use a CountingStream subclass implementing _read()")

    def read(self, advance=True):
        char = self._read()
        if advance is True or (callable(advance) and advance(char)):
            if char == "\n":
                self.lnum += 1
                self.cnum = 1
            elif char != "":
                self.cnum += 1
        return char

    def skip_spaces(self):
        char = True
        while char:
            char = self.read(lambda c: c.isspace())
            if not char.isspace():
                break
        return char


class CountingLines(CountingStream):
    """
    CountingStream for streams accessible via line lists.
    """
    def __init__(self, lines):
        CountingStream.__init__(self)
        self.lines = lines
        self.line_count = len(self.lines)

    def _read(self):
        if self.lnum >= self.line_count:
            return ""
        line = self.lines[self.lnum - 1]
        if self.cnum > len(line):
            return "\n"
        return line[self.cnum - 1]


class CountingFile(CountingStream):
    """
    CountingStream for file objects (returned via `open()`).
    """
    def __init__(self, file):
        CountingStream.__init__(self)
        self.file = file

    def _read(self):
        return self.file.read(1)


def main(args):
    """
    Entrypoint for CLI usage.
    """
    file = sys.stdin
    if args.file != "-":
        file = open(args.file, "r", buffering=2048, encoding="utf-8")
    stream = CountingFile(file)
    output = None
    if args.line == True:
        parts = re.split("[,.:/-]", args.target)
        line = int(parts[0])
        column = 1 if len(parts) == 1 else int(parts[1])
        res = scan_stream(stream, line=line, column=column, verbose=args.verbose)
        if res:
            output = args.delimeter.join(str(x) for x in res)
    else:
        path = args.target.split(args.delimeter)
        res = scan_stream(stream, path=path, verbose=args.verbose)
        if res:
            output = ":".join(str(x) for x in res)
    if output:
        print(output)
    else:
        print("'%s' not found" % (args.target), file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "file",
        default="-",
        help="json to parse")

    parser.add_argument(
        "-l",
        "--line-mode",
        action="store_true",
        dest="line",
        help="output path for the given line[:offset] instead of searching for path")

    parser.add_argument(
        "-d",
        "--delimeter",
        dest="delimeter",
        default=".",
        help="path delimeter")

    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        dest="verbose",
        help="verbose output")

    parser.add_argument(
        "target",
        help="target path or line[:offset] (in line mode)")

    main(parser.parse_args())