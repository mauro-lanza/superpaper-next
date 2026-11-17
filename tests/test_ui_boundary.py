"""superpaper/ui does no file, process or thread work itself; helpers outside it do."""

import ast
from pathlib import Path

UI = Path(__file__).parent.parent / "superpaper" / "ui"

BANNED_MODULES = {"subprocess", "threading", "shutil", "tempfile", "glob", "pathlib", "io"}
BANNED_OS = {
    "listdir",
    "scandir",
    "walk",
    "stat",
    "remove",
    "unlink",
    "rename",
    "replace",
    "makedirs",
    "mkdir",
    "rmdir",
    "open",
    "system",
    "popen",
    "environ",
    "getenv",
}
BANNED_OS_PATH = {"exists", "isfile", "isdir", "islink", "realpath", "getmtime", "getsize", "expanduser", "abspath"}
BANNED_METHODS = {
    "exists",
    "is_file",
    "is_dir",
    "read_text",
    "write_text",
    "read_bytes",
    "write_bytes",
    "iterdir",
    "mkdir",
    "unlink",
    "LoadFile",
    "SaveFile",
}


def module_aliases(tree: ast.AST) -> dict[str, str]:
    """Local names bound to os or os.path, by import."""
    aliases = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in ("os", "os.path") and alias.asname:
                    aliases[alias.asname] = alias.name
        elif isinstance(node, ast.ImportFrom) and node.module == "os":
            for alias in node.names:
                if alias.name == "path":
                    aliases[alias.asname or "path"] = "os.path"
    return aliases


def violations(source: str) -> list[str]:
    found = []
    tree = ast.parse(source)
    aliases = module_aliases(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [alias.name for alias in node.names if alias.name.split(".")[0] in BANNED_MODULES]
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.split(".")[0] in BANNED_MODULES:
                found.append(node.module)
            elif node.module == "os":
                found += [f"os.{alias.name}" for alias in node.names if alias.name in BANNED_OS]
            elif node.module == "os.path":
                found += [f"os.path.{alias.name}" for alias in node.names if alias.name in BANNED_OS_PATH]
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == "open":
                found.append("open()")
            elif isinstance(func, ast.Attribute):
                head, _, rest = ast.unparse(func.value).partition(".")
                owner = aliases.get(head, head) + (f".{rest}" if rest else "")
                if owner == "os" and func.attr in BANNED_OS:
                    found.append(f"os.{func.attr}")
                elif owner == "os.path" and func.attr in BANNED_OS_PATH:
                    found.append(f"os.path.{func.attr}")
                elif func.attr in BANNED_METHODS or (owner.endswith("Image") and func.attr == "open"):
                    found.append(f"{owner}.{func.attr}")
    return found


def test_ui_modules_do_no_file_process_or_thread_work():
    problems = {
        path.name: found for path in sorted(UI.glob("*.py")) if (found := violations(path.read_text(encoding="utf-8")))
    }
    assert not problems


def test_the_scan_finds_what_it_bans():
    source = "import subprocess\nimport os\nos.path.isfile('x')\nopen('y')\nPath('z').read_text()\nImage.open('i')\n"
    assert violations(source) == ["subprocess", "os.path.isfile", "open()", "Path('z').read_text", "Image.open"]


def test_the_scan_follows_imported_names_and_aliases():
    assert violations("from os import listdir, getpid\nfrom os.path import isfile, basename\n") == [
        "os.listdir",
        "os.path.isfile",
    ]
    assert violations("import os as o\no.listdir('x')\no.getpid()\n") == ["os.listdir"]
    assert violations("import os.path as p\np.isfile('x')\np.basename('x')\n") == ["os.path.isfile"]
    assert violations("from os import path as p\np.exists('x')\n") == ["os.path.exists"]
    assert violations("import os as o\no.path.isdir('x')\n") == ["os.path.isdir"]
