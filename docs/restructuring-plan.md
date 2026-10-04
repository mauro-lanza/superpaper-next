# Restructuring Plan

This replaces an earlier draft of this plan (referred to below as **the first
draft**), which has been removed. Several of its rules were correct and are
carried forward here verbatim; §5 records what was changed and why, so the
rejected options stay auditable without keeping the superseded document around.

---

## 0. How this document was produced

Every file in `superpaper/` was read in full (11 169 lines), plus all 14 test
files, `conftest.py`, `pyproject.toml`, `sp_paths` import behaviour, the CI
workflow, and the PyInstaller/AppImage tooling. The test suite was executed and
line-level coverage was measured with a `sys.settrace` tracer (the `coverage`
package is not installed).

Every claim below that could be checked was checked. Where a statement in the
first draft turned out to be stale or wrong, it is corrected explicitly rather
than quietly rewritten.

---

## 1. Corrections to the first draft's baseline

| First-draft statement | Reality (2026-08-28) |
|---|---|
| "The current suite has 44 passing tests." | **212 collected: 209 passed, 3 xfailed.** Off by 165. |
| "Persistent writes are direct truncating writes rather than atomic replaces." | Half-true. `.profile` files and `running_profile` now use `_atomic_write_regular` with fsync + hardlink/replace publication. `general_settings`, `display_systems.dat` and `*.persp` are still plain truncating `open(..., "w")`. |
| "Detect external edit conflicts with a lightweight revision/content token." | **Already implemented.** `data.FileIdentity` = (dev, ino, size, mtime_ns, sha256). Nothing further is needed here. |
| Phase 1 / Phase 2 are separate phases | They were merged in practice (PR #21 shipped profile identity *and* atomic persistence *and* transactional rename together). The phase boundary did not survive contact. |
| "Before the first nested package is added, setuptools must move to constrained package discovery." | Still true and still not done: `pyproject.toml:67` is `packages = ["superpaper"]`. |

**Work completed against that plan so far:** Phase 0 (partial), Phase 1 item 1 (profile
identity/path containment, `profile_id.py`), and most of Phase 2 restricted to
profile files. Phase 1 items 2–3 (delete lifecycle, timer generation semantics)
are *not* done — both are still open as strict xfails.

---

## 2. What the program actually does

Module boundaries should follow the program's real jobs, not an architecture
diagram. Superpaper does seven things:

1. **Discover the display system** — enumerate monitors, then apply user
   corrections (manual diagonals, bezel thickness, physical offsets, perspective
   angles) to produce a *physical* layout.
2. **Remember profiles** — image sources per display/group, span mode, slideshow
   delay, sort mode, hotkey, zoom/pan, chosen perspective.
3. **Choose the next image(s)** — shuffle/alphabetical/date-seeded ordering,
   cross-monitor de-duplication, persistent "current selection".
4. **Compose one desktop-sized image** from the chosen images and the layout
   (four render modes: simple span, PPI/bezel-corrected span, per-display multi,
   perspective-corrected).
5. **Hand that image to the OS** — 8 Linux desktop families, Windows, macOS,
   plus a user-supplied command escape hatch and a post-change hook.
6. **Do 3–5 on a trigger** — timer tick, hotkey, tray click, GUI button, CLI.
7. **Let the user edit 1 and 2** with a live preview.

Seven jobs. The current code has **two** modules holding jobs 1–5 (2 433 + 1 816
lines) and **two** holding jobs 6–7 (3 015 + 1 545 lines, plus `tray.py` which is
also the composition root). That mismatch *is* the problem statement.

---

## 3. As-built inventory

Import graph (acyclic — the problem is not cycles):

```
sp_platform
  └ sp_paths ──(import-time side effects: mkdir ×3, copy example profiles)
      └ sp_logging
profile_id            (pure, zero deps — already a model module)
perspective           (pure math + sp_logging — already a model module)
message_dialog        (imports wx)  ◄── inverted: core modules depend on this
      ▲
      ├── wallpaper_processing   (2433 L)  ── jobs 1,3-partial,4,5
      │       └ data             (1816 L)  ── jobs 2,3
      │             ├ configuration_dialogs (1545 L)
      │             │     └ gui  (3015 L)          ── job 7
      │             │           └ tray (667 L)     ── job 6 + composition root
      │             └ cli (181 L) ─lazy→ tray
      └ sni_tray (423 L)
__main__ ─ spanmode
```

### 3.1 What each module actually owns

| Module | Lines | Real responsibilities (count) |
|---|---:|---|
| `gui.py` | 3015 | wx layout; profile form↔domain mapping; dirty-state engine; profile file persistence orchestration; tray mutation; render driving; preview geometry; Pillow rendering; drag-and-drop; bezel/position config state machines. **≈9** |
| `wallpaper_processing.py` | 2433 | display detection; display persistence (`.dat`/`.persp` codecs); PPI/bezel/offset geometry; 4 render modes; artifact cache; slideshow timer; render locking/threading; 11 platform setters; KDE activities + DBus + JS generation; subprocess execution; dialogs; `sys.exit`. **≈12** |
| `data.py` | 1816 | TOCTOU-hardened managed-file IO (≈350 L); profile discovery/diagnostics; profile parsing; profile domain state; image enumeration; selection planning; selection persistence; settings parsing; **logging configuration + `sys.excepthook` installation**; validation with modal dialogs; `sys.exit`. **≈11** |
| `configuration_dialogs.py` | 1545 | 8 wx classes; settings-file writes from a file picker; perspective CRUD; display-system persistence; render triggering; cross-dialog widget reads. **≈6** |
| `tray.py` | 667 | wx tray view; hotkey registry; slideshow timer owner; **application controller**; composition root; `sys.exit` on missing wx. **≈6** |
| `sni_tray.py` | 423 | D-Bus SNI protocol + menu model. Self-contained. **1** |
| `perspective.py` | 429 | Pure 3-D back-projection math. **1** |
| `cli.py` | 181 | argparse + dispatch + one-shot render. **2** |
| `profile_id.py` | 168 | Portable identity + path containment. **1** |
| `sp_paths.py` | 135 | Path computation **+ directory creation + first-run seeding at import time**. **2** |
| `sp_platform.py` | 110 | OS constants + AppImage env restoration. **2** |
| `spanmode.py` | 90 | OS span-mode configuration. **1** |
| `wallpaper_windows.py` | 68 | Win32 wallpaper setter. **1** |
| `message_dialog.py` | 24 | wx dialog with a print fallback. **1** |
| `sp_logging.py` | 32 | Logger globals. **1** |

The five modules at the bottom of that table are already correctly factored.
The five at the top are the entire restructuring problem.

---

## 4. The structural defects that actually generate bugs

Ranked by observed bug production, not by abstract badness. Each has file:line
evidence.

### D1 — Parsed profiles are a function of the live display count

`ProfileData.__init__` reads `wpproc.NUM_DISPLAYS` and `wpproc.RESOLUTION_ARRAY`
at parse time (`data.py:954, 957, 1121, 1133, 1181, 1223`) and **calls
`sys.exit()` if no displays are published** (`data.py:940-944`) after showing a
modal dialog.

Consequences: the same `.profile` file yields different objects on different
machines; a profile cannot be parsed headlessly; display hotplug (issue #25)
cannot be implemented without re-parsing every profile; renderer tests must
pre-seed three globals (`conftest.py:25-27`, ~120 test cases).

This is the deepest defect and the first draft does not name it.

### D2 — Wallpaper application is gated on a mutable display label

`if profile.name == G_ACTIVE_PROFILE or force` appears at
`wallpaper_processing.py:1191, 1345, 1390, 1497, 2217`. The gate compares an
*editable* string against a module global that four different tray methods
assign (`tray.py:157, 475, 494, 548, 562`) and that `gui.py:1616` triggers
indirectly.

Consequences: a rename silently blocks every subsequent slideshow tick until
`rearm_active_timer` resyncs it (the comment at `tray.py:490-493` documents
exactly this bug being patched, not fixed); the GUI's Apply builds a temp profile
carrying the *typed* name and passes `force=True`, so an unsaved draft renders
under the saved profile's identity.

### D3 — The render artifact cache is keyed by that same mutable label

`alternating_outputfile(profile.name)` → `TEMP_PATH/<name>-a.png`
(`wallpaper_processing.py:1142-1159, 1189, 1343, 1388`).

- GUI Apply overwrites the *saved* profile's cache with an unsaved draft and
  deletes its alternate (`gui.py:1396` → `alternating_outputfile`), poisoning
  `quick_profile_job`'s startup restore.
- `remove_old_temp_files` matches by **substring**
  (`wallpaper_processing.py:1695`: `if match_string in temp_file`). Verified:
  rendering profile `work` deletes `homework-b-crop-*.png` and
  `network-b-crop-*.png`. Cross-profile cache destruction on KDE/XFCE/macOS.
- Renaming a profile orphans its cache forever.

### D4 — There is no owner of the active session

Active profile state exists in three independently updated places
(`TaskBarIcon.active_profile`, `wpproc.G_ACTIVE_PROFILE`, the `running_profile`
file); display state in four more globals. The first draft identified this correctly.
Two consequences are currently *known-broken and untested-as-correct*:

- `RepeatedTimer._run` calls `self.start()` unconditionally before invoking the
  callback (`wallpaper_processing.py:109-112`), so a dispatched tick resurrects a
  stopped timer — `tests/test_repeated_timer.py:34`, strict xfail.
- `rearm_active_timer` rebuilds the timer via `run_profile_job(startup=True)`,
  whose `RepeatedTimer.__init__` calls `start()` (`:107`), discarding
  `is_paused` — `tests/test_tray_lifecycle.py:193`, strict xfail.

### D5 — Core modules depend on wx and terminate the process

`data.py` and `wallpaper_processing.py` both import `message_dialog` (which
imports wx) and both call `sys.exit()`:

- 24 `show_message_dialog` call sites in `data.py`, 3 in `wallpaper_processing.py`.
- `sys.exit()` in `data.py:944`; `sys.exit(1)` in `wallpaper_processing.py:1597,
  1609`.
- `show_message_dialog` is **not thread-safe** and is reachable from the render
  thread (`data.py:1327` inside `Filehandler.__init__`).

This is why `tests/conftest.py:85-128` must inject five fake modules into
`sys.modules` and force-reload `superpaper.tray` just to test five controller
methods.

### D6 — Paths are import-time global constants with side effects

`sp_paths.py:123-135` runs `setup_config_path()`, `setup_cache_path()`,
`os.mkdir` ×3 and `shutil.copy` of the example profiles **at import**. `data.py:30`
then binds `CONFIG_PATH`/`TEMP_PATH` *by value*.

Verified consequence: the autouse `isolated_paths` fixture is a placebo — after a
full run, `sp_paths.CONFIG_PATH` still points at the *first* test's tmp dir, and
all 211 later tests share it. Tests compensate with ~60 hand-written monkeypatch
sites across **three different aliases** for the same logical path (`data.CONFIG_PATH`,
`data.sp_paths.PROFILES_PATH`, `wpproc.TEMP_PATH`). Any path-ownership refactor
breaks all of them.

### D7 — Reading settings has global side effects, and it is done 10 times

`GeneralSettingsData.parse_settings` (`data.py:792-873`) additionally: sets
`sp_logging.LOGGING/DEBUG/G_LOGGER`, installs `sys.excepthook`, creates a
`logging.FileHandler` on `TEMP_PATH/log`, attaches a `StreamHandler`, and writes
`wpproc.G_SET_COMMAND_STRING`.

`GeneralSettingsData()` is constructed at `gui.py:88`,
`configuration_dialogs.py:233, 241, 590, 1311, 1326, 1378, 1445, 1451`,
`tray.py:111, 383`. With logging enabled, opening the settings dialog twice
attaches duplicate handlers and reopens the log file in `"w"` mode.

### D8 — The GUI is the controller, and it reaches everywhere

- `gui.py` **assigns** `parent_tray_obj.active_profile` (`:1610`, `:1722`) and
  calls `reload_profiles`, `update_hotkey`, `rearm_active_timer`.
- Saving *any* profile makes it the active profile and re-arms its timer
  (`gui.py:1610, 1616`) — saving a non-running profile silently switches the daemon.
- `onApply`, documented as leaving disk untouched (`gui.py:1371-1375`), writes
  `selected=` into the stored `.profile` (`gui.py:1405-1408`).
- `PerspectiveConfig` aliases the panel's *staged* `DisplaySystem`
  (`configuration_dialogs.py:586-587`) and calls `save_system()` on it
  (`:906, 999, 1016`), persisting unsaved bezel/position/diagonal edits and
  republishing four globals — while the panel's Save/Revert buttons remain
  unaware.
- Two `parent.parent` chains (`configuration_dialogs.py:469, 495`), and
  `HelpPopup` navigates `parent.frame` (`:1472`) where `frame` means three
  different classes in three different files.
- Three handlers busy-wait on the render thread with
  `while thrd.is_alive(): wx.YieldIfNeeded(); time.sleep(...)`
  (`gui.py:1398-1400, 1768-1770`, `configuration_dialogs.py:1105-1106` — the last
  without pumping events at all).

### D9 — Every profile operation rescans and reparses everything

`discover_profile_inventory()` opens, reads, decodes, syntax-checks and
**constructs a full `ProfileData`** (including a `Filehandler` that `os.listdir`s
every configured image directory) for every `.profile` on every call.

One GUI Save does: `test_save` (listdir of every source dir) → `save_managed_profile`
(`iterdir`) → `reload_profiles` → `list_profiles` (**full scan #1**) →
`open_profile` (**full scan #2** + re-read) → `next_wallpaper_files(peek=True)`
which may rewrite the file. There is no identity map, so "which `ProfileData`
object is the live one" is answered differently in `tray.list_of_profiles`,
`gui.list_of_profiles`, `gui.loaded_profile` and `tray.active_profile`.

### D11 — A core module's importability depends on environment variables

`wallpaper_processing.py:57-61` calls `running_kde()` — which reads
`DESKTOP_SESSION`, `KDE_FULL_SESSION` and `XDG_SESSION_DESKTOP` — **at import
time**, and conditionally executes a bare `import dbus`.

Verified on the maintainer's own machine (KDE session, `dbus-python` not
installed):

```
$ python -c "import superpaper.wallpaper_processing"
ModuleNotFoundError: No module named 'dbus'
$ env -u KDE_FULL_SESSION -u XDG_SESSION_DESKTOP python -c "import superpaper.wallpaper_processing"
import OK
```

The application cannot start. `dbus-python` builds from source and requires
system `libdbus`/`glib` headers (`docs/installation-linux.md`), so "KDE without
dbus-python" is a likely install state, not an exotic one. `sni_tray.py:28-31`
already guards its own dbus import with `try/except ImportError`;
`wallpaper_processing.py` does not.

The test suite cannot detect this because `tests/conftest.py:16-17` deletes all
three variables in an autouse fixture. **A fixture is masking a startup crash.**

### D10 — Effort is inverted relative to actual risk

`data.py` contains ~350 lines and 20 tests defending against local
symlink/inode-reuse races on `~/.config/superpaper/profiles` — an attacker who
can win that race can already edit the user's dotfiles. Meanwhile, in the same
process:

- `Image.MAX_IMAGE_PIXELS = None` disables the decompression-bomb guard
  process-wide (`wallpaper_processing.py:33`), and images come from arbitrary
  user directories.
- `set_wallpaper` executes `python3 <CONFIG_PATH>/run-after-wp-change.py` with no
  validation (`wallpaper_processing.py:1446-1448`) — zero tests.
- KDE JavaScript is assembled by string concatenation with a hand-rolled escaper
  (`_escape_js_string`, `:1699`) — zero tests.

The hardening is *correct and worth keeping*. The point is that it was applied
**inside a god module before that module had been split**, growing `data.py` by
~80 %, and its tests reach into eight private functions
(`tests/test_temp_profile_validation.py`, 12 injection points), which makes the
eventual extraction more expensive than it would have been if done in the other
order.

---

## 5. Review of the first draft

### 5.1 What the first draft got right — carried forward unchanged

- The state-ownership findings are accurate and remain the core
  problem statement.
- Its architectural rules on wx isolation, exit codes, immutable render inputs,
  single session ownership, selection commit, platform adapters, queue semantics
  and bounded broad-catches are correct and are
  restated in §7.3.
- The selection-commit ordering: plan → render → apply → commit.
- One serial render worker with generation-based staleness rejection.
- Preview/production sharing geometry and crop planning.
- Renderers must not mutate profiles, advance cursors, read globals, set
  wallpapers, or show dialogs.
- "Do not combine GUI decomposition with a visual redesign".
- The platform-evidence requirement in PR gates.

### 5.2 Where the first draft was wrong or misordered

**(a) The phase order attacks durability before ownership.**
Phases 1–2 harden persistence *inside* the god modules; structural extraction
starts at Phase 4. The one time this was executed (PR #19/#21) it produced
+874 lines in `data.py` and 20 tests bound to private functions. Repeating that
pattern for `general_settings`, `display_systems.dat` and `*.persp` would inflate
`wallpaper_processing.py` the same way. **v2 moves file-format code into its own
package *and* makes its writes atomic in the same PR, instead of doing atomicity
as a separate cross-cutting phase.**

**(b) It deferred file moves behind typed models.**
Phase 3 (typed models, "Large") and Phase 4 (repositories) precede any real
decomposition. But a *pure move with a re-export shim* is a near-zero-risk,
same-day change that immediately makes the repository navigable — which is the
user's stated goal. Typing 2 400 lines while they are still in one file is
strictly harder than typing them after they are in six files of 400.
**v2 moves first, types second.**

**(c) Layer names are not enforceable.**
"domain / application / infrastructure / presentation" has no
objective membership test, so drift is undetectable. **v2 defines each package by
its *allowed import set* and enforces it with a test** (§7.2). Same shape,
mechanically checkable.

**(d) The proposed layout is already contradicted by the code.**
`profile_id.py` — the single most correct module in the repo — does not appear
anywhere in that layout. `perspective.py` is listed as future `domain/perspective.py`
although it already qualifies today at zero risk.

**(e) Nine open-ended phases, three of them "Large", with no exit criteria.**
There is no defined point at which the restructuring is *done*, and no
"acceptable to stop here" line. For a small-team fork this is how plans get
abandoned half-applied — which is precisely the failure mode the user described
in the original codebase. **v2 has 8 bounded steps, each with explicit exit
criteria, and marks Step 5 as a legitimate stopping point.**

**(f) Its Phase 0 rule about xfails was violated, with no detection for it.**
The draft required known-incorrect behaviour to be a linked strict xfail. But
`tests/test_cli.py:85-97` asserts `calls == ["spanmode", "cli"]` with
`argv = ["superpaper", "--help"]` — i.e. it *locks in* the fact that
`superpaper --help` writes the Windows registry / runs `gsettings`
(`__main__.py:18` runs `set_spanmode()` before argv inspection). A
characterization test now defends a bug. None of the three existing xfails has an
issue link either, which that same rule required.

**(g) Its packaging gate was over-weight in one respect and missing in another.**
Switching `packages = ["superpaper"]` to `find:` is three lines. But the draft never
mentions that `release-tooling/make-pyinstaller-build.py` uses plain
`pyinstaller --onefile` with **no `--hidden-import` and no spec file**: any module
that becomes lazily imported (e.g. a per-desktop platform adapter selected at
runtime) silently disappears from the frozen binary and the AppImage. That is the
real packaging risk.

### 5.3 What the first draft missed entirely

Defects **D1, D2, D3, D6, D7, D9** from §4 did not appear in the first draft in
any form.
D1 (display-coupled parsing) and D6 (import-time path side effects) are the two
cheapest high-leverage fixes in the repository and both are prerequisites for
almost everything else that plan wanted to do.

Also missing:

- `remove_old_temp_files` substring collision (verified cross-profile deletion).
- Duplicate logging handlers from repeated `GeneralSettingsData()` construction.
- `SetMaxLength(14)` on the profile-name field (`gui.py:205`) versus
  `ProfileId`'s 200-byte limit — the draft mentioned removing the limit but not
  that the two limits currently disagree.
- Three call sites `join()`/busy-wait on the `Thread` returned by
  `change_wallpaper_job` (`cli.py:180`, `gui.py:1398`, `configuration_dialogs.py:1105`).
  a serial worker must therefore return a *handle*, not `None`.
- `Image.open` is never context-managed in the preview path (`gui.py:2163`);
  descriptors accumulate until GC.
- The preview has **no decoded-image cache**: every zoom tick, resize, or bezel
  keystroke re-opens and re-scales the source file on the UI thread.

---

## 6. Non-goals

Stated up front so scope cannot creep:

- No visual redesign, no new render modes, no new platform support.
- No change to any on-disk format. `.profile`, `general_settings`,
  `display_systems.dat`, `<hash>.persp`, `running_profile` and
  `kde_desktop_mapping.json` stay byte-compatible. New behaviour goes in new
  optional keys only.
- No async/await, no dependency-injection framework, no plugin system, no ORM.
- No rewrite of `perspective.py`, `sni_tray.py`, or `wallpaper_windows.py`.
- No revert of the managed-file hardening. It is correct; it is being *relocated*.

---

## 7. Target structure

### 7.1 Packages

```text
superpaper/
  app/                     entry points and composition roots ONLY
    __main__.py            argv dispatch
    cli.py                 argparse -> Command -> exit code
    tray_app.py            wx App + TaskBarIcon wiring (was tray.py's __init__)
    context.py             AppContext: paths, settings, notifier, session

  core/                    pure. stdlib only. no Pillow, no wx, no screeninfo.
    ids.py                 ProfileId, ManagedPathError      (from profile_id.py)
    profile.py             WallpaperProfile, SlideshowSettings, Selection
    layout.py              DisplaySnapshot, canvas/crop geometry
    perspective.py         unchanged 3-D math
    selection.py           batch planner (from Filehandler._plan_batch)
    results.py             OperationResult / failure taxonomy

  store/                   file formats. stdlib only.
    paths.py               AppPaths dataclass + factory. NO import side effects.
    atomic.py              managed-file IO, moved verbatim from data.py
    profile_file.py        .profile codec + ProfileStore (identity map)
    settings_file.py       general_settings codec + SettingsStore
    display_file.py        display_systems.dat + *.persp codecs
    pointer_file.py        running_profile

  render/                  needs Pillow.
    request.py             RenderRequest / RenderResult
    plan.py                mode -> crop plan (pure; shared with preview)
    compose.py             simple / advanced / grouped / multi / perspective
    cache.py               artifact naming keyed by ProfileId + generation

  hostplatform/            needs subprocess / dbus / win32 / AppKit.
    applier.py             WallpaperApplier protocol + selection
    process.py             run(): env, timeout, returncode, stderr
    detect.py              screeninfo enumeration -> raw monitors
    linux.py kde.py xfce.py windows.py macos.py
    spanmode.py

  session/                 the single owner of runtime state. no wx.
    session.py             active profile, selection, generation, pause
    worker.py              one serial worker + coalescing + bounded shutdown
    commands.py            Activate / Next / Pause / ApplyDraft / Refresh / Shutdown
    notify.py              Notifier protocol (log-only default)

  ui/                      wx only.
    tray_icon.py  sni.py
    editor/ profile_form.py display_form.py perspective_form.py preview.py
    dialogs.py  message.py
```

`hostplatform/` rather than `platform/` because `platform` is a stdlib module and
shadowing it inside a package is a recurring source of confusion in frozen builds.

### 7.2 The rule that replaces "layers"

Each package declares the set of third-party/optional imports it may use. A test
walks the AST of every module and fails on violation.

| Package | May import | Must NOT import |
|---|---|---|
| `core` | stdlib | Pillow, screeninfo, wx, dbus, win32, AppKit, `store`, `render`, `hostplatform`, `session`, `ui` |
| `store` | stdlib, `core` | Pillow, wx, dbus, subprocess, `render`, `session`, `ui` |
| `render` | stdlib, `core`, Pillow | wx, dbus, subprocess, `store`, `session`, `ui` |
| `hostplatform` | stdlib, `core`, subprocess, dbus/win32/AppKit | wx, Pillow, `store`, `session`, `ui` |
| `session` | stdlib, `core`, `store`, `render`, `hostplatform` | wx |
| `ui` | everything except `app` | — |
| `app` | everything | — |

This is objective, cheap to enforce, and it is the *only* structural rule that
cannot silently rot. It also encodes the practical property that matters most
here: **`core` + `store` import in milliseconds with no display, no GUI toolkit
and no image library**, so profile logic, geometry and selection become fast and
trivially testable.

### 7.3 Behavioural rules (carried forward, plus additions)

1. `core`, `store`, `render`, `hostplatform` and `session` never import wx and
   never show dialogs. User-visible messages go through `session.notify.Notifier`.
2. Only `app/*` converts failures into process exit codes. No `sys.exit()`
   anywhere else.
3. Persistent writes are atomic same-directory replacements. All persistence paths
   are owned by `store` and containment-checked.
4. Render operations receive one immutable request; they never read mutable
   globals, never mutate profiles, never advance cursors, never set wallpaper.
5. The active session has exactly one owner. Saving an inactive profile must not
   activate it.
6. Selection advances only after a successful render **and** a successful platform
   apply. Positional batches are all-or-nothing.
7. Platform effects are behind adapters returning structured results, including
   the subprocess return code.
8. Every command carries an activation generation and a display generation; stale
   completions cannot apply or commit.
9. **New:** parsing a profile must not require display data. (fixes D1)
10. **New:** cache artifacts and the active-profile pointer are keyed by
    `ProfileId`, never by the editable label. (fixes D2, D3)
11. **New:** `store` and `core` have no import-time side effects. Directory
    creation and first-run seeding happen in `app`. (fixes D6)
12. **New:** reading configuration never configures logging, never installs an
    excepthook, and never writes another module's global. (fixes D7)
13. Broad `except Exception` only at named app/thread/event-loop boundaries.
14. New or moved public functions carry complete annotations.

---

## 8. Roadmap

Eight steps. Each is independently shippable and independently revertible.
"Exit" is the objective condition for calling the step done.

---

### Step 1 — Explicit paths (fixes D6)

**Size:** small. **Behaviour change:** none intended.

- `store/paths.py` exposes `AppPaths` (frozen dataclass: `config`, `cache`,
  `temp`, `profiles`, `resources`, `tray_icon`) and `resolve_paths(env=os.environ)`.
- Directory creation and example-profile seeding move to an explicit
  `ensure_layout(paths)` called from `app/__main__.py` only.
- `superpaper/sp_paths.py` remains as a shim re-exporting the module-level
  constants for one release so nothing breaks at once.
- `conftest.py` gains a real `app_paths` fixture; the ~60 ad-hoc monkeypatch
  sites migrate to it incrementally (not all in this PR).

**Exit:** importing `superpaper.store.paths` creates no directories and copies no
files; `tests/` contains one path fixture; the placebo `isolated_paths` autouse
fixture is replaced.

**Why first:** it is the cheapest change with the widest unblocking effect. Every
later step needs injectable paths, and today's test isolation is provably fake.

---

### Step 2 — Notifier port and no process exits in the backend (fixes D5)

**Size:** small/medium. **Behaviour change:** message *routing*, not content.

- `session/notify.py`: `Notifier` protocol (`info`, `error`, `confirm`) with a
  `LoggingNotifier` default and a `WxNotifier` in `ui/message.py`.
- Replace all 27 `show_message_dialog` call sites in `data.py` /
  `wallpaper_processing.py` with either a returned failure or `notifier.*`.
- Replace `data.py:944`, `wallpaper_processing.py:1597, 1609` with raised typed
  errors; the composition roots map them to exit codes.
- `Filehandler`'s missing-path dialog (`data.py:1327`) becomes a returned
  diagnostic — it currently runs on the render thread.

**Exit:** `rg "show_message_dialog|sys\.exit" superpaper/{core,store,render,hostplatform,session}` is
empty; `conftest.py` no longer needs to fake `superpaper.message_dialog`;
`import superpaper.data` succeeds with wx absent (it already does, but for the
wrong reason — `message_dialog` swallows the ImportError).

---

### Step 3 — Move, don't rewrite (fixes the god modules; the user's stated goal)

**Size:** medium ×4 PRs. **Behaviour change:** none. Pure relocation.

Each PR moves code with `git mv`-quality fidelity and leaves the old module as a
re-export shim. No logic edits, no renames, no reformatting.

- **3a** `perspective.py` → `core/perspective.py`; `profile_id.py` → `core/ids.py`.
  Zero risk; both already qualify.
- **3b** `wallpaper_processing.py` → split:
  `hostplatform/detect.py` (Display, DisplaySystem detection),
  `store/display_file.py` (`save/load_system`, `save/load_perspectives`,
  `list_to_str`, `str_to_list`),
  `core/layout.py` (canvas/crop/centre geometry, `compute_working_canvas`),
  `render/compose.py` (four renderers + `resize_to_fill`),
  `render/cache.py` (`alternating_outputfile`, `remove_old_temp_files`,
  `special_image_cropper`),
  `hostplatform/{linux,kde,xfce,windows,macos}.py`,
  `session/worker.py` (`RepeatedTimer`, `change_wallpaper_job`, `run_profile_job`,
  `quick_profile_job` — temporarily, unchanged).
  **In the same PR**, `display_systems.dat` / `*.persp` writes become atomic
  (they are moving into `store` anyway; doing it later means touching the file
  twice).
- **3c** `data.py` → split:
  `store/atomic.py` (the ~350 hardened lines, verbatim),
  `store/profile_file.py` (discovery, diagnostics, parse, serialize, save/delete),
  `store/settings_file.py` (`GeneralSettingsData`, minus the logging side effects
  — see Step 4),
  `core/selection.py` (`Filehandler` + `ImageList`),
  `core/profile.py` (`ProfileData` for now; typed in Step 6).
  **In the same PR**, `general_settings` writes become atomic.
- **3d** `configuration_dialogs.py` + `gui.py` → `ui/` with one file per dialog.
  Still wx-coupled, still controllers — only the file boundaries change.
  This PR also fixes the `frame` naming collision (rename to `settings_panel`,
  `preview_panel`, `config_frame`) because it is the precondition for Step 7.

**Exit:** no module over 600 lines except `ui/editor/profile_form.py`;
`pyproject.toml` uses constrained discovery; a wheel is built, imported from a
clean venv, and an AppImage smoke build passes; `make-pyinstaller-build.py` gains
a `.spec` file with explicit `hiddenimports` for the platform adapters.

**Why "move, don't rewrite":** it is the change with the highest ratio of
navigability gained to risk taken, and it is exactly what "separate the code into
modules" means. Every subsequent step becomes a small local edit instead of a
1 000-line surgery.

---

### Step 4 — Configuration reading has no side effects (fixes D7)

**Size:** small.

- `store/settings_file.py` returns a frozen `Settings` value. It does not touch
  `sp_logging`, `sys.excepthook`, logging handlers or `wpproc.G_SET_COMMAND_STRING`.
- `app/context.py` calls `configure_logging(settings)` exactly once at startup.
- `G_SET_COMMAND_STRING` becomes a field on the platform applier, passed in.

**Exit:** constructing `Settings` twice adds no logging handlers; `rg "G_SET_COMMAND_STRING"`
returns only `hostplatform/linux.py`.

---

### Step 5 — Display-independent profiles and identity-keyed artifacts (fixes D1, D2, D3, D9)

**Size:** medium/large — the highest-value correctness step.

- `core/profile.py` parses a `.profile` into a `WallpaperProfile` **without**
  reading any display state. Per-display arrays become "as configured"; the
  reconciliation against the live display count moves into
  `render/plan.py` / `session`.
- `ProfileData.__init__`'s `sys.exit()` disappears (already covered by Step 2, but
  this removes the reason it existed).
- `store/profile_file.py` gains an identity map: one `WallpaperProfile` instance
  per `ProfileId` per load generation. `open_profile` stops triggering a second
  full inventory scan.
- `render/cache.py` keys artifacts by `ProfileId` plus a render generation.
  Preview/draft renders use a distinct `preview/` namespace and can never
  overwrite a saved profile's cache.
- `remove_old_temp_files`'s substring match becomes an exact prefix+suffix match.
- The `profile.name == G_ACTIVE_PROFILE` gate is replaced by an explicit
  `apply: bool` on the render request, decided by the caller.

**Exit:** `core` imports with `screeninfo` uninstalled; `tests/test_render_*` no
longer monkeypatch `NUM_DISPLAYS` / `RESOLUTION_ARRAY` / `DISPLAY_OFFSET_ARRAY`;
a regression test proves rendering profile `work` does not delete `homework`'s
cache; `rg "G_ACTIVE_PROFILE" superpaper/` returns nothing outside `session/`.

> **This is a legitimate stopping point.** After Step 5 the repository is
> navigable, the backend is headless and testable, the two worst correctness
> defects are gone, and no further work is required for the project to be
> materially easier to maintain than it is today. Steps 6–8 are improvements, not
> prerequisites.

---

### Step 6 — Typed models and results

**Size:** medium, one PR per concept.

Immutable `WallpaperProfile`, `SlideshowSettings`, `Selection`, `DisplaySnapshot`,
`DisplaySettings`, `PerspectiveSettings`, `RenderRequest`, `RenderResult`,
`SessionSnapshot`. Field-level parse diagnostics separated from UI strings.
`CLIProfileData` and `TempProfileData` are replaced by a `ProfileDraft` builder
plus `WallpaperProfile.from_images(...)`.

Typing is deliberately *after* the moves: each concept now lives in a ~200-line
module, so annotating it is a local, reviewable change instead of a diff across
1 800 lines.

**Exit:** `ty` strict mode enabled for `core/` and `store/`.

---

### Step 7 — Session owner and serial worker (fixes D4, D8)

**Size:** large. Depends on Steps 1–6.

- `session/session.py` owns: active `ProfileId`, loaded revision, current
  selection, slideshow timer, pause state, display snapshot, activation
  generation.
- `session/worker.py`: one long-lived serial worker. `submit(command) -> Handle`
  (**the handle is required** — `cli.py:180`, `gui.py:1398` and
  `configuration_dialogs.py:1105` currently `join()` a raw `Thread`). User actions
  queue FIFO; slideshow ticks coalesce; stale generations are discarded;
  shutdown rejects new work and joins with a 5 s bound.
- `RepeatedTimer` is replaced: stop is final for its generation, and pause
  survives save/rearm. **The two strict xfails become passing tests.**
- Saving an inactive profile no longer activates it (`gui.py:1610, 1616` removed).
- CLI one-shot runs inline and imports neither `ui` nor wx.

**Exit:** six deterministic scenarios pass —

- manual actions queue FIFO;
- repeated slideshow ticks coalesce to one pending tick;
- profile activation takes effect before later manual actions;
- stale generations cannot apply or commit a selection;
- shutdown rejects new submissions and joins within five seconds;
- a blocked adapter cannot rearm timers during shutdown;

`ui/` performs no filesystem, timer, render or subprocess operation directly; no
`wx.YieldIfNeeded` busy-wait remains.

---

### Step 8 — Editor decomposition and ratchets

**Size:** several medium PRs. Ongoing.

- Extract form state + controllers from the wx views (`ProfileFormState`,
  `DisplayFormState`), then split the views.
- Fix the staged-`DisplaySystem` leak: `PerspectiveConfig` operates on its own
  copy and returns a result; only the owning panel commits.
- Preview gains a decoded-image cache and context-managed `Image.open`.
- `SetMaxLength(14)` removed (or `ProfileId` limit lowered) so the two agree.
- Enable `B905`, `BLE`, annotation rules; forbid new `Any`, `# type: ignore`,
  and backend `sys.exit()` via the import-rule test.

---

## 9. Test strategy changes

The suite is strong in two narrow places (identity/paths: 62 cases at 95 %
coverage; persistence transactions) and thin exactly where the risk is. Overall
in-process statement coverage is **24.6 %**; `gui.py`, `configuration_dialogs.py`
and `wallpaper_windows.py` are at **0 %**.

Changes, in order:

1. **Add `[tool.pytest.ini_options]`** — `xfail_strict = true`,
   `--strict-markers`, `filterwarnings = ["error"]`, `testpaths = ["tests"]`.
   None of these exist today.
2. **Add the import-rule test** (§7.2) in the same PR as Step 3a. It is ~40 lines
   of `ast` walking and it is the only thing that keeps the structure from rotting.
3. **Replace the three defective assertions** now, while they are cheap:
   - `tests/test_profile_discovery.py:173` — `assert editable_name == "../outside"`
     compares a local to itself; the traversal scenario is never exercised.
   - `tests/test_profile_discovery.py:108` — passes because the literal is NFD,
     not because plain `str` is rejected; `open_profile` does accept NFC `str`.
   - `tests/test_cli.py:82` — asserts only `returncode != 0`, which is also true
     when display detection fails on a headless runner. Assert stderr content.
4. **Convert `tests/test_cli.py:85` to a strict xfail** — it currently locks in
   "`--help` mutates system desktop settings". Move `set_spanmode()` out of
   `__main__.main()` into the actual apply path.
5. **Link the three existing xfails to `ISSUES.md` entries.** The first draft
   required this; none of them do it.
6. **Cover the three dark P0 surfaces before touching them:** `_change_wallpaper`
   (0/25 statements — *the* render dispatcher), `set_wallpaper` including the
   `run-after-wp-change.py` hook (0/12), and shutdown end-to-end (0 %).
7. **Retire white-box tests as their subject moves.** These will break by design
   and must be rewritten, not migrated:
   `test_repeated_timer.py:82-88` (asserts the exact `RepeatedTimer(...)` arg
   tuple), `test_cli.py:148,193` (asserts `CLIProfileData`'s 5-positional
   signature — a class Step 6 deletes), `test_display_detection.py:63,83,101`
   (uses `is` on globals, forbidding a rebuilt-but-equal list),
   `test_filehandler.py:22,76,121` (private cursors), `test_tray_lifecycle.py:24-31`
   (bypasses `__init__` and hand-sets 5 of ~15 attributes — adding a required
   attribute breaks all 15 tests with `AttributeError`).
8. **Keep the golden-pixel render tests** (`test_render_characterization.py`) —
   they are the correct instrument for Step 5 parity — but pin the Pillow version
   in a comment and add a note that a bump is a deliberate re-baseline.

---

## 10. Decisions

Adopted unless you object:

| # | Decision | Rationale |
|---|---|---|
| 1 | Package boundaries are defined by allowed imports and enforced by a test. | Only structural rule that cannot silently rot. |
| 2 | Move files before typing them. | Moves are near-zero-risk and deliver the stated goal immediately. |
| 3 | Atomic writes for the remaining three formats happen **inside** the move PR, not as a separate phase. | Avoids touching the same code twice and repeating the `data.py` inflation. |
| 4 | The existing TOCTOU hardening is relocated verbatim, not reverted. | It is correct and tested. Its placement, not its content, is the problem. |
| 5 | No further hardening of local filesystem races until the decompression-bomb guard and the `run-after-wp-change.py` hook have tests. | Effort should track risk (D10). |
| 6 | `ProfileId` is the key for the active pointer, the identity map **and** the artifact cache. | Fixes D2 and D3 with one concept. |
| 7 | Profile parsing becomes display-independent; display reconciliation moves to render/session. | Prerequisite for hotplug (#25), headless tests, and renderer extraction. |
| 8 | `session` owns runtime state; the GUI emits commands and renders state. | Carried forward unchanged. |
| 9 | Step 5 is an acceptable stopping point. | The plan must be safe to abandon partway without leaving the repo worse. |
| 10 | The package is named `hostplatform`, not `platform`. | Avoids shadowing a stdlib module in frozen builds. |

Needing your input — **resolved 2026-08-28**:

- **A. Portable config on Windows/macOS — keep for now; make paths overridable.**
  Step 1 is behaviour-preserving on all three platforms. It adds
  `SUPERPAPER_CONFIG_HOME` / `SUPERPAPER_CACHE_HOME` overrides as a *new*
  capability, which also subsumes the purpose of `sp_paths.test_git_path`
  (a `"github\\superpaper" in path.lower()` developer-machine hack shipped in
  production code, 0 % covered) — that function is deleted.
  The macOS branch (`sp_paths.py:48`) writes config **into the installed package
  directory** and is a genuine bug (ISSUES #113), but changing a platform path
  without a macOS machine to verify on would violate this plan's own PR gate.
  It is scheduled as its own change, gated on macOS evidence.

- **B. `Image.MAX_IMAGE_PIXELS` — replace `None` with an explicit 1e9-pixel cap.**
  The current setting disables the guard process-wide, including for preview
  decoding on the wx UI thread. Pillow's default (~89 Mpx) is genuinely too low
  for this application — a 5×8K wall is ~166 Mpx — so `None` was a real fix to a
  real problem, just an over-broad one. 1e9 px (~3 GB RGB) is far above any
  legitimate wallpaper and far below an OOM kill. `DecompressionBombError`
  becomes a structured failure. Lands with **Step 2**, which is when there is
  somewhere to report it to.

- **C. Profile-name length — `ProfileId` becomes the single authority.**
  `gui.py:205`'s `SetMaxLength(14)` is deleted: it provides no safety (it does not
  apply to `ChangeValue`, so a 30-character profile loaded from disk sits happily
  in the field) and it contradicts `ProfileId`'s 200-byte limit.
  `_MAX_PROFILE_ID_BYTES` drops 200 → **120**, because derived cache filenames
  (`<name>-b-crop-99.png`) plus a Windows `%LOCALAPPDATA%\Superpaper\temp\`
  prefix exceed `MAX_PATH` at 200. Lands with **Step 5**, which is when the
  derived-filename budget is actually decided.

- **D. PEP 758 bare `except A, B:` — normalise to parenthesised tuples.**
  The syntax has no functional benefit and costs two characters, but it makes
  four of the five largest files a hard `SyntaxError` for any tool not running on
  3.14 — editors, external linters, and the AST-walking import-rule test this
  plan asks contributors to run. Mechanical, fully covered by the existing suite,
  and shipped as its **own** PR so it never pollutes a review diff.

---

## 11. What changed from the first draft

| Aspect | First draft | This plan | Reason |
|---|---|---|---|
| Structure metaphor | 4 abstract layers (domain/application/infrastructure/presentation) | 7 packages defined by **allowed imports**, enforced by a test | Objective and mechanically checkable; prevents drift |
| First work | Phase 0 characterization, then persistence hardening | Explicit paths (Step 1), then Notifier (Step 2) | Both are prerequisites for *all* testing; the first draft omitted them entirely |
| File moves | Phase 4+, after typed models and repositories | Step 3, before typing | Moves are cheap and reversible; typing 1 800-line files is not |
| Atomic writes for settings/display files | Own phase (Phase 2) | Folded into the move PR that relocates each format | Avoids the `data.py` inflation pattern that already happened once |
| Display-coupled profile parsing (D1) | Not mentioned | Step 5, called the deepest defect | Blocks hotplug, headless tests and renderer extraction |
| Name-keyed apply gate (D2) | Not mentioned | Step 5, rule 10 | Direct cause of the rename/slideshow bug already patched in `tray.py:490` |
| Name-keyed artifact cache (D3) | Cache "ownership by ProfileId" mentioned in passing | Step 5, with a verified cross-profile deletion bug | Real data loss on KDE/XFCE/macOS |
| Import-time path side effects (D6) | Not mentioned | Step 1 | Proven to make the autouse isolation fixture a placebo |
| Settings read = logging config (D7) | Not mentioned | Step 4 | Duplicate handlers; 10 construction sites |
| Repeated full inventory scans (D9) | Not mentioned | Step 5 (identity map) | 2–3 full parse+listdir sweeps per GUI save |
| Serial worker return value | "one long-lived serial worker" | …**returning a handle** | Three existing call sites `join()` the current `Thread` |
| Phase count / termination | 9 phases, 3 "Large", no exit criteria | 8 steps, each with exit criteria, Step 5 marked as a valid stop | A plan that cannot be stopped safely will be abandoned unsafely |
| Packaging gate | Full ceremony before first nested package | Folded into Step 3's exit criteria, **plus** a PyInstaller `.spec` with explicit `hiddenimports` | The real freeze risk is lazy imports vanishing, not `packages = [...]` |
| xfail discipline | Rule stated | Rule stated **plus** `xfail_strict`, issue links, and the `--help` regression converted | The rule was already violated and nothing detected it |
| Test suite | "44 passing tests" | 212 cases, 24.6 % coverage, 8 named defects, retirement list for white-box tests | That baseline was stale by 165 tests |
| Effort/risk balance | Uniform rigor | Explicit decision (#5) to stop hardening filesystem races until the code-execution paths have tests | 350 lines defending inode races; 0 tests on `subprocess.run(["python3", user_script])` |

Rules and contracts carried forward **unchanged**: state-ownership
findings, selection-commit ordering, render purity, preview/production geometry
sharing, generation-based staleness rejection, bounded shutdown, platform
evidence in PR gates, and "no visual redesign during decomposition".

---

## 12. Sequenced PRs

### PR 1 — Trustworthy test gate (Step 0)

Goal: the suite must stop lying before anything is moved. Fixes the startup
crash (D11) that a fixture was masking.

1. `wallpaper_processing.py:57-61` — guard the KDE `dbus` import; drop the
   import-time `running_kde()` call; fail at *use* time with an actionable
   message.
2. `tests/` — subprocess regression test importing the module with KDE env set
   and `dbus` absent. Document why `isolated_paths` strips the desktop variables.
3. `pyproject.toml` — add `[tool.pytest.ini_options]`: `testpaths`,
   `xfail_strict`, `--strict-markers`, `--strict-config`,
   `filterwarnings = ["error"]` (verified already clean).
4. Fix the three defective assertions (§9.3).
5. `ISSUES.md` — entries for the three existing xfails plus D11; link them.
6. New strict xfail: `superpaper --help` must not run `set_spanmode`.
7. `docs/restructuring-plan.md` — superseded-by header.

### PR 2 — Normalise PEP 758 syntax (decision D)

Mechanical, its own PR, no other changes.

### PR 3 — Step 1: explicit paths

`store/paths.py`, `AppPaths`, `ensure_layout`, env overrides, `app_paths`
fixture, `sp_paths` shim.

### Then

Step 2 (Notifier + decision B) → Step 3a (`perspective`, `ids`) with the
import-rule test → Steps 3b–3d.
