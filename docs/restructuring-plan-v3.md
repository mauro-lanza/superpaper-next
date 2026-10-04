# Restructuring Plan — v3

This replaces `docs/restructuring-plan.md` (v2). It is a replacement rather than an
amendment because the ranking, the target structure and the sequencing all changed;
v2 is left untouched so the two can be compared. Delete v2 once this is accepted.

Written 2026-10-04 against `98ba753` plus the uncommitted WIP in
`superpaper/configuration_dialogs.py`.

---

## 0. How this was produced

- Read every module in `superpaper/` (in full for `data`, `wallpaper_processing`,
  `tray`, `cli`, `sp_*`, `profile_id`, `__main__`, and the controller/persistence paths
  of `gui` and `configuration_dialogs`), all tests and `conftest.py`, `pyproject.toml`,
  CI, pre-commit, the AppImage/PyInstaller tooling, and the history of PRs #8–#21.
- Ran the suite: 209 passed, 3 xfailed, 0.7 s. Measured statement coverage with a
  `sys.settrace` + `threading.settrace` tracer: **25.8 %** (v2's 24.6 % did not trace
  worker threads, which is why it reported `_change_wallpaper` as uncovered).
- **[run]** marks a claim reproduced by executing the code in an isolated `HOME`
  (snippets in Appendix A). **[read]** marks a claim established by following the
  code path end to end. Nothing below is inherited from v2 without one of those marks.

---

## 1. Verdict on v2

v2 is a diligent inventory. D2, D3, D6, D7, D8 and D11 are real, and its test-suite
audit is mostly right. It is wrong in ways that matter:

1. **It misses the two worst defects users hit today**, both introduced by the identity
   work in #19/#21: the editor's **Save fails after Apply or after any slideshow tick**,
   and **profiles that loaded in v2.3.2 now silently disappear**. Its decision to
   relocate that hardening "verbatim" would carry both forward.
2. **Its central sequencing claim is false for this codebase.** "A pure move with a
   re-export shim is near-zero-risk" does not hold when the code being moved
   communicates through rebound module globals (`NUM_DISPLAYS`, `RESOLUTION_ARRAY`,
   `G_ACTIVE_PROFILE`, `G_SET_COMMAND_STRING`, …). A shim copies those values at import
   time; readers and writers silently diverge, and 112 of the suite's 153 monkeypatch
   calls patch attributes of `superpaper` modules (mostly `wallpaper_processing`, `data`
   and `cli`). The globals have to go *before* the split. Once they are gone, the moves
   really are mechanical.
3. **The target structure is over-built** for 11k lines and one maintainer: seven
   packages, a `Notifier` port that none of the 27 back-end dialog sites actually needs,
   a `WallpaperApplier` protocol (the platform strategy hierarchy you explicitly reject),
   command classes, an `AppContext`, and an AST layering matrix. It also contradicts
   itself: `core/` is "stdlib only", yet it contains `perspective.py`, which imports
   numpy.
4. **Two of its "resolved" decisions don't hold up.** PEP 758 normalisation is reverted
   by the project's own `ruff format` [run]. The ProfileId 200→120 arithmetic pairs a
   Linux/macOS-only filename pattern with a Windows-only limit, measures it in the wrong
   unit, and the change would itself drop existing profiles.
5. **"Step 5 is a safe stopping point" — no.** At that point the shims, a `session/`
   package still holding the old racy timer code, a half-adopted Notifier, and the Save
   regression would all still be in place.

---

## 2. What hurts users today

Ranked by harm × likelihood, not by architectural depth. The "v2" column maps each
item to v2's defect list.

| # | Defect | Evidence | v2 |
|---|---|---|---|
| **U1** | **Editor Save fails** with "Managed profile changed since it was loaded" after **Apply**, after **any slideshow tick** while the editor is open, and after a Save that clears a stale selection. This blocks the core edit → apply → save workflow. | [run] `gui.py:605` copies `source_identity` by value. Then `_write_selected` (`data.py:1260-1282`) rewrites the same file from onApply (`gui.py:1405-1408`), from a timer tick, or from `next_wallpaper_files(peek=True)` (`data.py:1213-1218`, called at `gui.py:1632` *after* the identity was copied at `:1626`). `save_managed_profile` requires an exact identity match (`data.py:724`). Introduced by #21. | — |
| **U2** | **Profiles that loaded in v2.3.2 silently vanish**. This covers: leaf symlinks (GNU stow, home-manager); a filename stem that differs from `name=` (for example a case-only rename on Windows); case-variant pairs on Linux (both are dropped); names containing `: ? * " < > \|` or reserved words (`con`, `cli`) that are legal on Linux; and NFD names (macOS HFS+). No message is shown. | [run] for symlinks; [read] for the rest. `list_profiles` only prompts for malformed content and drops every identity diagnostic (`data.py:503-521`). In v2.3.2, `list_profiles` was `os.listdir` + `open`. | — (v2 decision C would add 121–200-byte names to this list) |
| **U3** | KDE session without `dbus-python` crashes on every entry point at import, including `--help`. This affects the documented "recommended" pipx install (no `[linux]` extra) unless the distro's python-dbus happens to be installed. The AppImage is unaffected because it bundles dbus-python. | [run] `wallpaper_processing.py:57-61` | D11 (ranked last) |
| **U4** | Hotkeys activate **stale profile objects**, so a profile's hotkey applies its pre-edit settings. Its selection writes then fail silently, and the editor reopens the stale object, which feeds back into U1. Separately, changing a profile's hotkey raises mid-save (uncaught) when the old binding was never registered, for example because hotkeys are disabled. | [read] `tray.py:318,353` register the `ProfileData` object itself, and the binding is only re-registered if the key changed. `system_hotkey` invokes callbacks on its own thread (`thread_me`). `tray.py:349-350` use `self.hk2`/`seen_binding` outside the `try`; both exist only when hotkeys were enabled at startup. | D9, partially (no consequence named) |
| **U5** | Saving any profile makes it the running one. If it isn't a slideshow, the running slideshow just stops. `running_profile` is not updated, so a restart silently reverts. | [read] `gui.py:1610,1616` → `tray.rearm_active_timer` | D8 |
| **U6** | The UI freezes for the rest of any in-flight render. Profile switch, rearm after save, perspective save, system save and align test all call `refresh_display_data` on the UI thread. That publishes under `G_WALLPAPER_CHANGE_LOCK` (`wallpaper_processing.py:835`), which renders hold for their whole duration (`:2320`). | [read] — and pinned as intended by `tests/test_display_detection.py:133` | — |
| **U7** | Profile discovery enumerates and `realpath`s **every image of every profile**, on the UI thread, several times per action. It also shows one modal dialog per missing source directory per scan, including from the render thread. | [run] One scan of 4 profiles × 2 displays × 5,000 images takes 278 ms and makes 40,001 `realpath` calls on a local SSD. A GUI Save does ≥2 scans plus `test_save` listdirs. NAS sources multiply the cost. Dialog at `data.py:1327`. | D9 (framed as rescans only) |
| **U8** | The editor breaks when a profile's sources are unavailable (unmounted drive). Merely opening it also **erases the persisted selection**, because the "peek" writes. | [read] `next_wallpaper_files(peek=True)` clears and persists an invalid selection (`data.py:1215-1217`), then returns `[]` [run]. `preview_wallpaper([])` hits `image_list[0]` → `IndexError` inside `populate_fields`. From the tray menu, the window silently fails to open (logged). At start-up with "show help at start" (the default), the exception escapes `TaskBarIcon.__init__` (`tray.py:188` is unguarded). From the dropdown, the form is half-filled and `_loading` stays `True`, so Save never enables until another profile is loaded. | — |
| U9 | A folder of `*.JPG` cannot be saved as a source ("does not contain supported image files"), although the slideshow would accept it. | [run] `data.py:1797,1805` are case-sensitive; `Filehandler` is not | — |
| U10 | Source paths containing `=` are truncated on load, so the profile never works again. | [run] `data.py:992` `line.split("=")` | — |
| U11 | With logging enabled, every Settings/Help/Browse dialog adds a FileHandler + StreamHandler, and re-opens the log in `"w"` mode, truncating it. | [run] 3 constructions → 6 handlers; `sys.excepthook` replaced | D7 |
| U12 | The CLI exits 0 on 7 of its 8 error exits (`cli.py:103,109,135,144,158,165,172`), and `-o 1 2` alone prints nothing. Without wxPython installed, `superpaper` exits **silently with 0**: `configuration_dialogs.py:23` runs `sys.exit()` at import, before tray.py's error message can print. | [run] | partly (CLI xfail exists) |
| U13 | The post-change hook passes the source list as **one** Python-repr string, while the shipped `example-script` reads `sys.argv[2:]`. `python3` is usually not a working command on Windows. | [read] `wallpaper_processing.py:1448` | D10 calls this a security risk, but it is the user's own script; the real problem is this bug |
| U14 | The preview ignores EXIF orientation while the render applies it. The preview also re-decodes the full source on every zoom/pan slider tick and every keystroke in the display-size fields. | [read] `gui.py:2163` vs `wallpaper_processing.py:1179`; [run] 181 ms per tick for a 24 MP JPEG | partly (cache only) |
| U15 | The render cache is keyed by the editable label. Cleanup is a **substring** match: rendering `work` deletes `homework-b-crop-*`. Restore and KDE activity lookup use prefix matches. | [run] `:1695`; [read] `:2385`, `:2087` | D3 (missed the prefix sites) |
| U16 | First run crashes if `~/.config` or `~/.cache` doesn't exist. | [run] `sp_paths.py:102` `os.mkdir` | — |
| U17 | A timer tick can resurrect a stopped timer, and rearm discards pause. | strict xfails | D4 |

**Latent risks the restructuring itself could trigger:**

- **L1 — `display_systems.dat` / `<hash>.persp` are keyed by `str(hash(DisplaySystem))`**
  (`wallpaper_processing.py:569,712`): CPython's tuple hash over ints. It is stable across
  runs today [run: identical under three `PYTHONHASHSEED`s]. A refactor that lets any `str`
  (such as the monitor name) into `Display.__hash__`, for example via a dataclass `eq`,
  makes the key random per process. Every user's bezels, positions and perspectives would
  then be silently "lost" on every restart. DisplaySystem's persistence and layout methods
  have **0 % coverage**. v2 proposes rewriting this area into typed `DisplaySnapshot`
  models without pinning the key.
- **L2** — `Image.MAX_IMAGE_PIXELS = None` process-wide. Inputs are the user's own
  folders, so the risk is low; the realistic failure mode is an accidental gigantic image,
  not an attack.
- **L3** — the WIP perspective change can persist a poison value (§10).

---

## 3. Structural causes

These are what generate the defects above. Fixing a cause retires its U-items.

| Cause | Retires | v2 |
|---|---|---|
| **S1 No owner for a profile.** A profile has three representations (`ProfileData`, `TempProfileData`, `CLIProfileData`) and N live objects at once (tray list, GUI list, `loaded_profile`, hotkey bindings, timer closure). Two writers do whole-file read-modify-write: selection persistence and the editor. There are two parsers (`parse_profile`, `_validate_profile_syntax`) and two validators that disagree. Parsing does filesystem I/O. | U1, U4, U7, U8, U9, U10 | D9, D1 (adjacent) |
| **S2 Runtime state is module globals and tray attributes, mutated from three threads** (UI, render, hotkey). `pause_timer` takes no lock. | U5, U6, U17 | D2, D4 |
| **S3 Import does work.** Paths are resolved and directories created, `dbus` is imported based on env vars, and the process calls `sys.exit` when wx is missing. | U3, U12 (silent exit), U16, the placebo test isolation | D6, D11 |
| **S4 The back end talks to the user.** There are 27 dialog calls in `data`/`wallpaper_processing`, some on worker threads. Validators show a dialog and then return `False`. | U7 (spam), wx called off the main thread | D5 |
| **S5 Renderers do everything.** They advance the selection, read globals, name cache files, apply the wallpaper and clean up. | U15, the D2 gate, preview/production drift (U14) | D2, D3 |
| **S6 The GUI is the controller.** It assigns tray internals, persists staged state through aliases, and busy-waits on threads. | U5, PerspectiveConfig staged-state leak | D8 |
| **S7 Persistence policy is disproportionate.** About 330 lines of `dir_fd`/`O_NOFOLLOW`/hard-link publication defend `~/.config` against a local attacker who already owns the account. They are coupled to whole-file identity, so the app's own selection writes register as conflicts. | U1 (with S1), U2 | D10 says "correct, keep"; I disagree, see Decision 2 |

---

## 4. Audit of v2, claim by claim

| v2 says | Verdict | Evidence |
|---|---|---|
| D1 is "the deepest defect", ranked first | **Overstated.** The coupling is real (`data.py:954-957,1055,1121-1133,1181-1192`). But the `sys.exit()` at `:940-944` is unreachable in production: every entry point publishes displays first, and a detection failure raises earlier. No fixed bug traces to parse-time coupling. Its real costs are test seeding and hotplug readiness. Display *globals* did produce bugs (#16), but that is S2, not D1. | [read], git log #16 |
| D5: `wallpaper_processing.py:1597,1609` "terminate the process" | **Wrong.** Both run on render threads, where `sys.exit` silently ends the thread and the app continues. v2 lists tray.py's missing-wx exit, but `configuration_dialogs.py:23` fires first, silently, with status 0 (U12). The conftest wx fakes exist because tray.py is a wx class that holds controller logic (S6), not because of D5. | [run] |
| D8: "Two `parent.parent` chains (`:469,:495`)" | Minor: these are `self.parent.frame` chains. | [read] |
| D9 is about repeated scans | **Mis-framed.** Its worst effects are correctness (U1, U4), and the per-image `realpath` cost is the real performance problem. | [run] |
| D10: the hardening is "correct and worth keeping" | **Disagree.** As integrated, it produces U1-class conflicts with the app's own writes and causes U2. The hook "executes with no validation" is not a risk (the user's own script in the user's own config dir); its argv format is the bug (U13). | [run] |
| D11 | **Correct, mis-ranked.** It belongs near the top. | [run] |
| §3: perspective.py is "pure math … already a model module" | **No.** It imports numpy and `sp_logging` → `sp_paths`, so importing it creates directories. | [run] |
| §5.2(b) "A pure move with a re-export shim is a near-zero-risk, same-day change" | **False here** (see §1.2). Shims also buy nothing: nothing outside `superpaper/` and `tests/` imports these modules (`example-script` runs as a subprocess). | [read] |
| §5.2(c)/§7.2 Enforce package membership with an AST import-matrix test | **Bureaucracy for this size.** The properties that actually broke are "imports without optional deps and env-dependence" and "import has no side effects". A behavioural subprocess test checks those directly (§8). | — |
| §5.2(g) "Lazily imported modules silently disappear from the frozen binary"; requires a `.spec` with `hiddenimports` | **False.** PyInstaller scans function bodies. The shipping AppImage already lazy-imports `superpaper.tray` and `superpaper.cli` inside `main()`, and it works. The real prerequisite is replacing `packages = ["superpaper"]` with package discovery before the first subpackage, which v2 also lists. | [read] `__main__.py:20-26`, build.sh |
| §7.1 seven packages; §7.3 Notifier, adapters, commands, context | **Over-built** (§5). | — |
| §7.2 "`core` + `store` import in milliseconds with … no image library" with `perspective` in `core` | **Self-contradictory** (numpy). | — |
| Step 3b: make `display_systems.dat`/`*.persp` writes atomic in the move PR | **Riskiest edit in the plan.** That code has 0 % coverage and holds the most hand-tuned user data. It must be characterised first, and L1 pinned. | coverage run |
| Step 5 is a safe stopping point | **No** (§1.5). | — |
| Step 7 "submit() must return a handle — three call sites `join()` a raw Thread" | Only if callers keep blocking. Remove the blocking instead: the CLI runs inline and the UI uses a completion callback. If a waitable is ever needed, use `concurrent.futures.Future`. | [read] |
| §9: `_change_wallpaper` has 0/25 statements covered | **Wrong** — it runs on a thread; v2's tracer ignored threads. Minor. | coverage run |
| §9.3: three defective assertions | **All confirmed.** `test_profile_discovery.py:108` uses an NFD literal [run]; `:173` compares a local to itself; `test_cli.py:82` also passes when display detection fails. | [run]/[read] |
| §9.4: convert `test_cli.py:85` to a strict xfail | Just fix it: move `set_spanmode()` after argv parsing, 3 lines. | — |
| Decision B: 1e9-pixel cap | Reasonable, low priority. Better as a size check inside one `open_source_image()` shared by render and preview (§7 C2). | — |
| Decision C: ProfileId 200→120 bytes | **Wrong arithmetic** (§9, Decision 4). | — |
| Decision D: normalise PEP 758 `except A, B:` | **Unworkable.** `ruff format` (target py314, run by pre-commit) rewrites `except (A, B):` back to `except A, B:` [run]. The "AST test can't parse it" argument does not apply, because the test runs on the project's own 3.14. Drop it. | [run] |
| `hostplatform/` name | Reasoning fine; `desktop/` names the subject better. | — |

---

## 5. Target structure

### 5.1 Layout

Two packages, each justified by a real, checkable boundary that also maps onto an
optional dependency set:

- **`ui/`** is the only place `wx` is imported (the `gui` extra).
- **`desktop/`** is the only place that spawns processes or touches dbus, AppKit or win32
  (the platform deps).

Everything else stays flat, one subject per module.

```text
superpaper/
  __main__.py        argv → cli or tray; spanmode only on the apply path.
  cli.py             Parse CLI args, run one apply inline, map the outcome to an exit code.
  paths.py           Where Superpaper's files live: AppPaths, resolve_paths(environ), ensure_dirs().
  settings.py        The general_settings format: read → Settings value, write; no side effects.
  logs.py            configure_logging(settings, paths) — called once, at startup.
  files.py           Durable replacement of our own files (tempfile + fsync + os.replace).
  profile_id.py      Profile identity and path containment (exists; policy per Decision 1).
  profiles.py        The .profile format: one Profile value; parse, serialize, validate → problems.
  profile_store.py   The profiles directory: discover, load, save/rename/delete, active pointer;
                     one live record per ProfileId.
  selection.py       Which image(s) come next: source enumeration (lazy) + batch planner.
  displays.py        Display layout: detection + PPI/bezel/offset/diagonal geometry.
  display_store.py   display_systems.dat + <hash>.persp formats (atomic; key pinned).
  perspective.py     3-D back-projection math (unchanged).
  render.py          Compose one desktop image: open_source_image(), resize_to_fill(),
                     canvas/crop geometry, simple/advanced/perspective/multi. Pure.
  render_cache.py    Rendered files on disk: naming, a/b alternation, pieces, exact cleanup.
  session.py         The runtime: active profile, slideshow deadline, pause, one worker thread.
  desktop/
    __init__.py      set_wallpaper(image, pieces, ...) -> result; DE dispatch; run(); post-hook.
    linux.py         gsettings families, XFCE, LXQt, feh, custom command.
    kde.py           Plasma scripting over DBus, activities (one JS template).
    macos.py  windows.py  spanmode.py
  ui/
    tray.py  sni_tray.py  message.py
    editor.py         Profile form ↔ Profile, Save/Revert/Apply via ProfileStore/Session.
    display_band.py   The "display system settings" band (diagonals, bezels, Save/Revert).
    preview.py        WallpaperPreviewPanel (cached decoded sources).
    layout_editor.py  Drag-to-position and bezel popups (split from preview if it stays >600 L).
    browse_dialog.py  positions_dialog.py  perspective_dialog.py  settings_dialog.py  help.py
```

The seven jobs map to modules like this:

| Job | Modules |
|---|---|
| 1. Discover displays + corrections | `displays`, `display_store`, `perspective` |
| 2. Remember profiles | `profile_id`, `profiles`, `profile_store`, `files` |
| 3. Choose the next images | `selection` |
| 4. Compose the desktop image | `render`, `render_cache` |
| 5. Hand the image to the OS | `desktop/` |
| 6. Do it on a trigger | `session` (sources: `ui/tray`, `cli`, hotkeys) |
| 7. Edit with a live preview | `ui/` |

Estimated sizes: largest non-UI modules are `displays` ~500 lines, `perspective` 430,
`render` ~400, `profiles` ~350, `session` ~350. In `ui/`, `editor` is ~900 lines and
everything else is under 700.

### 5.2 What is deliberately not introduced

| Not introduced | Instead |
|---|---|
| `Notifier` protocol | Back-end functions return problems/results; the caller decides how to show them (§5.3). One plain `on_status: Callable` handed to `Session` for background failures, which the tray marshals with `wx.CallAfter`. |
| `WallpaperApplier` protocol / per-DE adapters | One dispatch function + one `run()` helper (env, timeout, return code, stderr). KDE, GNOME and feh keep their genuinely different shapes. |
| Command classes (Activate/Next/Pause/…) | `Session.activate(id)`, `.next()`, `.toggle_pause()`, `.apply_draft(...)`, `.shutdown()`. |
| `AppContext` | `__main__` builds `paths`, `settings`, `store`, `session` and passes them explicitly. |
| `request.py`/`results.py` modules, `ProfileDraft` builder | Render functions take arguments. `profile_from_images(...)` is a function. |
| `core/` vs `store/` split | A format and its persistence are sibling modules named after their subject. They change for different reasons; layer names add nothing. |
| AST import matrix | One behavioural import test (§8). |
| Re-export shims | Callers and tests are updated in the same PR; there are no external importers. |
| Typed-model rewrite as a phase | Annotations come with each carve-out. `ty` already passes. |
| PyInstaller `.spec` with hidden imports | Not needed; never use `importlib.import_module(dynamic_name)`. |

### 5.3 Why no Notifier: every back-end dialog site has a natural owner

| Sites (27 total) | Replacement |
|---|---|
| 19 in `TempProfileData.test_save` / `is_list_*`, 2 in `TempProfileData.save` | `validate(profile) -> list[Problem]`; the editor shows them. |
| 1 malformed-profile delete prompt (`data.py:532`) | Discovery already returns diagnostics. The UI asks, then calls `store.delete(id)`. |
| 1 "monitor data missing" (`data.py:942`) | Unreachable. Delete. |
| 1 missing source (`data.py:1327`, render thread) | `selection` returns the missing paths; the editor shows them inline; the session logs them. |
| 1 physical-size detection failed (`:309`) | `Display.phys_size_failed` already exists; the UI shows the hint. |
| 1 negative bezel (`:509`) | Already validated by the GUI popup; becomes a `ValueError` for programmer error. |
| 1 unknown DE (`:1608`, render thread) | `set_wallpaper` returns a failure result. |

---

## 6. Rules

1. `wx` is imported only in `ui/`. Process spawning, dbus, AppKit and win32 live only in
   `desktop/`.
2. Importing a module only defines names: no I/O, no env-dependent imports, no `sys.exit`.
3. Only `__main__`, `cli` and `ui` decide process exit.
4. Expected failures are values (problem lists, a small result dataclass). Exceptions are
   for programmer errors and genuinely unexpected I/O.
5. One live record per profile. The editor, tray and hotkeys hold `ProfileId`s, not
   objects.
6. Runtime state belongs to `Session`, which runs one worker thread. The UI never waits
   on it.
7. Render functions are pure: their inputs are paths, `Profile` and display layout; their
   output is a PIL image. No selection advance, no wallpaper setting, no file naming.
8. Our files are replaced atomically. On-disk formats stay read-compatible forever.
   Writes stay readable by v2.3.2 unless a recorded decision says otherwise.
9. The `display_systems.dat` key derivation never changes. A test pins it.
10. Carved-out modules log via `logging.getLogger(__name__)`; `logs.configure_logging`
    runs once.

Non-goals, unchanged from v2: no visual redesign, no new render modes or platforms, no
async, no DI framework, no plugin system.

---

## 7. Roadmap

Every step leaves the suite green, has no shims, and leaves every module name true to its
contents. **Each phase boundary is a genuine stopping point.**

### Phase A — Fix what users hit now

In place, in small PRs, each with a regression test where the code is headless. This is
not restructuring. It comes first because these fixes are cheap, user-visible, and each
one documents the structural cause it came from.

- **A0 Trustworthy test gate.**
  - `[tool.pytest.ini_options]`: `testpaths`, `xfail_strict`, `--strict-markers`,
    `--strict-config`.
  - Add the **headless-import test** (§8). It fails today and pins U3.
  - Fix U3: import dbus at use, inside the KDE path.
  - Fix the three defective assertions.
  - Link each xfail to an `ISSUES.md` entry.
- **A1 U1 — editor save conflicts.** Compare a digest of the profile's *configuration*
  (all lines except `selected=`) instead of whole-file identity. Carry the current
  on-disk selection through the save unless the editor supplies one. About 20 lines in
  `data.py`, plus tests for the three U1 scenarios (Apply, tick, and a Save that clears a
  stale selection). This is format-neutral. The root fix is Decision 3.
- **A2 U2 — stop silently dropping existing profiles**, according to Decision 1. At
  minimum, surface identity diagnostics; recommended, restore loading.
- **A3 U4 — hotkeys by id.** Register `profile_id` instead of the object, resolve it at
  activation, and guard the `hk2` attribute. A few lines in `tray.py`.
- **A4 U5 — Save does not change the running profile.** Rearm only if the saved profile
  *is* the active one.
- **A5 Small fixes, one test each:**
  - U9: case-insensitive extension check.
  - U10: `split("=", 1)`.
  - U12: non-zero CLI exits, messages at WARNING, and a clear "wxPython is required"
    message plus exit 1.
  - U13: pass sources as separate argv entries and keep arg 1.
  - U16: `os.makedirs(exist_ok=True)`.
  - `--help` no longer calls `set_spanmode`.
  - U14a: `exif_transpose` in the preview.
- **A6 Delete verified dead code:**
  - `compute_crop_tuples` and its five helpers;
  - `compute_ppi_corrected_res_array`;
  - `compute_relative_densities` with `ppi_array_relative_density`;
  - the stored-but-never-read `bezel_px_offsets` attribute;
  - `XYPlaneRectangle.corners_2d`.

  Keep `ppi_array` and `compute_bezel_px_offsets`' effect on `manual_offsets`: legacy
  profiles with `bezels=` still depend on it. Characterise it first.

**Exit:** U1–U5, U9, U10, U12, U13 and U16 have regression tests or are verified by hand
on KDE. The headless-import test passes.

### Phase B — Make state explicit

In place; no file moves.

- **B1 Paths (S3).**
  - Characterise every branch of the current resolution first: Snap; XDG set, unset, or
    set to a non-directory (falls back to `~/.config`); Windows writable vs. not; macOS
    package dir.
  - `AppPaths` (frozen dataclass), `resolve_paths(environ, platform)`, `ensure_dirs(paths)`
    called from `__main__`. Importing creates nothing.
  - Consumers receive paths explicitly. `ProfileStore` holds its directory; functions take
    a `Path`. Don't pass the whole `AppPaths` bag where one directory suffices.
  - One `app_paths` fixture. **All** path monkeypatches migrate in this PR. Running two
    mechanisms side by side is the very confusion we're removing.
  - Delete `test_git_path`. Add `SUPERPAPER_CONFIG_HOME`/`SUPERPAPER_CACHE_HOME` overrides
    if you still want them (v2 decision A).
- **B2 Settings (U11).**
  - `read_settings(path) -> Settings` and `write_settings(path, Settings)`, which writes
    atomically.
  - `logs.configure_logging()` is called once.
  - `set_command` is passed to the setter, which deletes `G_SET_COMMAND_STRING`.
- **B3 Characterise before touching.** This must land before B4/C2/C3.
  - `display_systems.dat` and `.persp` fixtures in the v2.3.2 format: load → fields, and
    save → byte-identical output.
  - The key for a fixed monitor set, pinned to a literal (L1).
  - Golden renders for advanced (bezels, offsets, span groups) and a small perspective
    case. This code is 0 % covered today.
  - Legacy profile keys (`ppi`, `diagonal_inches`, `bezels`, `offsets`) → effective
    offsets.
- **B4 Display layout is passed, not read from globals (S2, D1).**
  - Renderers, `special_image_cropper`, profiles, the CLI and the UI widget counts take or
    derive the layout from a `DisplaySystem` argument.
  - Profiles store per-display values *as configured*; reconciliation with the live
    display count happens at render time.
  - Delete `_change_wallpaper`'s swap-the-globals block.

**Exit:** `rg "NUM_DISPLAYS|RESOLUTION_ARRAY|DISPLAY_OFFSET_ARRAY|G_ACTIVE_DISPLAYSYSTEM|G_SET_COMMAND_STRING" superpaper/`
is empty. Renderer tests build a layout instead of patching globals. The import test
also asserts that no files are created.

### Phase C — Split by subject

Once Phase B is done, no *rebound* module global is read across the new module
boundaries. The locks are shared objects that are never rebound, so they move freely.
`G_ACTIVE_PROFILE` stays with the job code until Phase D, and setters receive the
profile name as an argument. Each PR is two commits:

1. **A pure `git mv`** plus import and test-path updates, green.
2. **The interface fix for that subject**, green.

There are no shims, and each subject is finished when its PR merges.

- **C0** `[tool.setuptools.packages.find] include = ["superpaper*"]`, keeping package-data.
  Smoke-test a wheel from a clean venv. Rebuild the AppImage once.
- **C1 `desktop/`.**
  - Setters take explicit arguments and **return results**; every spawn goes through one
    `run()` (host env, timeout, return code, stderr).
  - No `sys.exit`, no dialogs.
  - The two ~80-line KDE JS programs (`:1939-2024`, `:2117-2192`), which duplicate the
    screen ordering, become one template fed a JSON desktop→images map. `json.dumps`
    replaces the hand-rolled `_escape_js_string`.
  - The "apply only if active" gate moves to the caller (interim: the job compares the
    active `ProfileId`).
- **C2 `render.py` + `render_cache.py`.**
  - Renderers are pure.
  - `open_source_image(path)` (EXIF, size cap, RGB) is shared by render and preview.
  - Cache images are written atomically.
  - Names are keyed by `ProfileId` with **exact** matching, drafts go in `preview/`, and a
    startup sweep removes files for ids that no longer exist (U15).
- **C3 `displays.py` + `display_store.py`.** Atomic writes; key and format pinned by B3.
- **C4 `profiles.py` + `profile_store.py` + `selection.py` + `files.py` (S1, S7).**
  - One `Profile` value replaces `ProfileData`/`TempProfileData`/`CLIProfileData`; one
    parser; `validate` returns problems; `_validate_profile_syntax` is deleted.
  - Image enumeration is lazy, so discovery never touches source directories (U7). It
    runs only for the profile being rendered or previewed, off the UI thread.
  - `ProfileStore` keeps one record per id.
  - Persistence follows Decision 2 and selection storage follows Decision 3.

**Exit:** `wallpaper_processing.py` and `data.py` no longer exist. Every module's subject
can be stated in one sentence. No module outside `ui/` exceeds ~600 lines.

### Phase D — Session owner (S2)

`session.py` has one worker thread consuming a `queue.Queue`.

- **Timer.** The slideshow deadline is the queue's `get(timeout=…)`, so there is no
  `threading.Timer`. That makes resurrection impossible by construction (U17). Pause means
  "no deadline". `next()` means "run now, reset the deadline".
- **Activation.** Activation and display refresh run on the worker. Everything is serial
  on one thread, so a completion can never be applied after a later activation, and no
  generation counters are needed. Checking the queue before applying, to skip a
  superseded render, is an optional optimisation.
- **Callers.** Tray, SNI, hotkey and editor calls only post messages: the UI never blocks
  (U6) and the hotkey thread never touches state.
- **Draft apply.** `apply_draft(profile, layout, on_done)` replaces the busy-waits.
- **Restore and shutdown.** Quick restore at startup runs on the worker. `shutdown()`
  rejects new work and joins with a 5 s bound.
- **Gate.** `G_ACTIVE_PROFILE` and the name gate are deleted (D2).

**Exit:** both timer xfails pass. Deterministic tests, without wx and with a fake clock,
cover:

- manual actions run in FIFO order;
- ticks never queue more than one;
- activation precedes later actions;
- pause survives save and rearm;
- shutdown is bounded and rejects work;
- a blocked `desktop` call cannot rearm after shutdown.

### Phase E — UI on the new API (S6)

- The tray becomes a thin view over `Session`.
- The editor talks only to `ProfileStore`/`Session`.
- Split `gui.py`/`configuration_dialogs.py` along the seams in §5.1. No visual redesign.
- `PerspectiveConfig` edits a copy and returns it; only the band commits.
- Add an LRU of decoded, downscaled preview sources (U14b).
- Remove `SetMaxLength(14)` (Decision 4).
- Delete the three busy-waits.

**Exit:** `ui/` performs no file I/O, subprocess or thread management directly, and
`wx.YieldIfNeeded` is gone.

### Phase F — Ratchets (optional, ongoing)

Enable B905 (several `zip`s pair display lists that can differ in length). Tighten `ty`
per module as each is carved out.

---

## 8. Test strategy

- **The one structural test** runs in a fresh subprocess:
  - `HOME` and XDG dirs point at an empty tmp;
  - `DESKTOP_SESSION=plasma`, `KDE_FULL_SESSION=true`;
  - `sys.modules["wx"] = sys.modules["dbus"] = None`;
  - then import every module outside `ui/` and `desktop/{kde,macos,windows}`.

  It asserts success and that the tmp tree is still empty. Together with a 5-line grep for
  `import wx` outside `ui/`, it guards the properties that actually broke (U3, S3, S4) in
  about 25 lines.
- **Characterise before every move** (B3). Golden-pixel renders stay; note the Pillow
  version, and treat a bump as a deliberate re-baseline.
- **Tests follow their subject.** Each C-step rewrites its subject's tests against the new
  arguments. Monkeypatching module globals is a smell to delete, not migrate.
- **Retire white-box tests with their subject:**
  - the `RepeatedTimer` argument tuple;
  - the `CLIProfileData` signature;
  - `is` identity on display globals;
  - Filehandler cursors;
  - the `object.__new__(TaskBarIcon)` controllers, which are replaced by `Session` tests;
  - the TOCTOU private-function tests, if Decision 2 removes them.
- **No GUI test harness.** wx is not in the venv, and building one would cost more than it
  returns. After Phase E the logic worth testing lives outside `ui/`. UI changes carry a
  manual checklist in the PR: KDE Wayland, GNOME, Windows when available.

---

## 9. Decisions for you

1. **Profile-loading compatibility (U2).** Recommended:
   - Apply ProfileId's *portability* rules only when creating or renaming in the GUI.
   - Apply *safety* rules (no separators, NUL or `.`/`..`) always.
   - Follow leaf symlinks.
   - On a name/filename mismatch, the filename is the identity and the internal `name=` is
     corrected on the next save.

   This restores everything v2.3.2 loaded without bringing back the dual-identity bugs.
   The alternative is to keep #21's strict policy and only surface the dropped files.
2. **Persistence hardening (S7).** Recommended: replace the ~330 lines with `files.py`:
   - same-dir tempfile + fsync + `os.replace`;
   - `ProfileId` containment;
   - the configuration-digest conflict check from A1;
   - for a symlinked leaf, write to the **resolved target**, so the dotfile link survives
     (`os.replace` on the link itself would destroy it).

   This deletes ~20 private-function tests. You lose protection against a local attacker
   racing symlinks inside your own `~/.config`, an attacker who can already edit your
   shell rc. Keeping it costs ongoing coupling and is where U1/U2 came from.
3. **Where the slideshow selection lives.** It is runtime state written on every tick into
   a config file. Recommended:
   - Store it next to `running_profile` in the cache dir.
   - Read legacy `selected=` as a fallback and stop writing it.

   The profile file then has one writer, the editor. #21's identity check becomes correct
   as designed, and dotfile repos stop churning every minute. The cost: downgrading to
   v2.3.2 restarts selections from the first image. Alternatively keep it in `.profile`,
   in which case A1's semantic check stays permanent.
4. **Profile-name length.** Keep ProfileId at 200 UTF-8 bytes / 200 UTF-16 units. v2's 120
   rests on `<name>-b-crop-99.png`, but crop files are produced only on KDE and macOS;
   Windows writes `<name>-a.jpg`. Windows `MAX_PATH` counts UTF-16 units, not UTF-8 bytes,
   so 120 bytes would cap CJK names at 40 characters for no Windows benefit. And lowering
   the cap makes existing 121–200-byte profiles invalid, which is U2 again. If Windows
   cache paths matter, bound the *cache stem* in `render_cache` (for example the first 48
   characters plus a 12-hex-digit hash when longer than 64) without touching identity.
   Replace the GUI's `SetMaxLength(14)` with a 64-character soft limit, or none.
5. **Image size cap.** Recommended: a `max_pixels` check inside `open_source_image()` with
   a user-readable error (header-only `Image.open` gives the size before decoding). Leave
   Pillow's global alone. 250 Mpx is generous for wallpapers; you choose the number.
6. **KDE activity matching.** It maps activities to profiles *by name* and guesses
   desktop→activity via a cache file. Keep it as is (behind the single JS template), or
   simplify it. I'd keep it; #96 users rely on it.
7. **Module renames.** `sp_paths` → `paths` and the like happen during the carve-outs
   anyway. Don't rename modules that aren't being carved out.

---

## 10. The uncommitted WIP in `PerspectiveConfig.populate_fields`

It guards a `KeyError` when `default_perspective` names a perspective missing from the
dict. Four problems:

- **It mutates shared state in a read path.** `self.persp_dict` *is* the editor's staged
  `DisplaySystem.perspective_dict` (`configuration_dialogs.py:587`). Merely opening the
  dialog inserts a phantom entry.
- **The phantom can be persisted.** `save_perspectives()` writes the whole dict, so saving
  *any other* perspective persists the phantom. Its viewer distance is 0, which bypasses
  `onSave`'s `dist > 0` validation. If it is the default and perspective is enabled, the
  back-projection yields NaN coefficients [run: `RuntimeWarning: invalid value encountered
  in scalar divide`] and the render produces garbage.
- **It sizes the lists from `wpproc.NUM_DISPLAYS`**, not from the dialog's own
  `self.display_sys`.
- **It fails `ruff format --check`** (missing trailing comma).

**Suggested shape.** Use `persd = self.persp_dict.get(persp_name)`. If it is `None`, call
`onCreateNewProfile(None)` and prefill the name, inserting nothing. Separately, find out
how the default came to dangle. Candidates:

- `display_systems.dat` and `.persp` are written as two non-atomic files;
- `onSave` temporarily sets the default to the `"\0validation"` scratch name, and an
  exception inside `check_for_large_image_size` would leave it there.

---

## 11. What changed from v2

| Aspect | v2 | v3 | Why |
|---|---|---|---|
| Ranking | By structural depth; D1 first, D11 last | By user harm; U1 (Save regression) and U2 (silent profile loss) first, neither of which v2 lists | §2; both verified by execution |
| First work | Paths, then Notifier | Phase A: user-visible fixes + test gate, then paths | They're cheap and live; v2's Step 5 stopping point leaves U1/U2 unfixed |
| Order of state vs. moves | Move (with shims), then fix globals (Step 5) | Remove rebound globals (B4), then pure moves (C) | Shims can't carry rebound globals; most monkeypatches target them |
| Shims | One release | None | No external importers; avoids a second migration |
| Characterisation | Not required before Step 3b | B3 pins `display_systems.dat`/`.persp`, the hash key, and advanced/perspective renders before anything touches them | 0 % coverage on the most hand-tuned user data; L1 |
| Packages | 7 (`app/core/store/render/hostplatform/session/ui`) | 2 (`ui/`, `desktop/`), the rest flat | Same findability with fewer concepts; both boundaries map to optional deps |
| Drift protection | AST import matrix | One behavioural subprocess import test | Tests the properties that broke, including D11 |
| User messages | `Notifier` port (info/error/confirm) | Problems/results returned; one `on_status` callable | All 27 sites map to a return value (§5.3) |
| Platform setters | `WallpaperApplier` protocol | Dispatch function + `run()` helper | Your worked example; KDE/GNOME/feh differ in shape |
| Session | `session/` package with commands, handle, generations | One `session.py`: one thread, deadline-in-queue | Serial processing removes the races by construction; no handle type needed |
| Persistence hardening | Relocate verbatim | Decision 2 (recommended: replace with atomic replace + semantic conflict check) | It caused U1/U2; threat model is the user's own account |
| Selection storage | Unchanged | Decision 3 (recommended: move out of `.profile`) | Removes the second writer to config files |
| ProfileId limit | 200 → 120 bytes | Keep 200 | v2's arithmetic was wrong, and lowering it drops existing profiles |
| PEP 758 | Normalise in its own PR | Dropped | `ruff format` reverts it |
| PyInstaller `.spec` | Required | Not needed | Function-level imports are already bundled |
| Typed models | Step 6, a phase | Annotations alongside each carve-out | No bug requires immutable models; DisplaySystem rewrite is the L1 risk |
| Stopping points | After Step 5 | After every phase | Each phase leaves no shims and truthful module names |
| Kept from v2 | — | Seven-jobs framing; D2/D3/D6/D7/D8/D11 findings; pytest strictness; fixing the 3 defective assertions; packaging discovery before subpackages; golden-pixel tests; no visual redesign during decomposition | Verified correct |

---

## Appendix A — Reproductions

All runs use `env -u KDE_FULL_SESSION -u XDG_SESSION_DESKTOP -u DESKTOP_SESSION` (except
U3) with `HOME`, `XDG_CONFIG_HOME` and `XDG_CACHE_HOME` pointing at a scratch directory,
and `wpproc.NUM_DISPLAYS`/`RESOLUTION_ARRAY`/`DISPLAY_OFFSET_ARRAY` seeded as the tray
does.

**U1** — what the editor does, minus wx:

```python
prof = data.list_profiles()[0]; expected = prof.source_identity   # populate_fields
prof.set_selected_wallpaper([str(img_b)], persist=True)           # onApply
data.save_managed_profile(tmp, current_profile_id=ProfileId("Work"),
                          expected_source_identity=expected)      # onSave
# -> ProfileTransactionError: ... source verification: Managed profile changed since it was loaded
# Same result when prof.advance_wallpaper() (a slideshow tick) replaces set_selected_wallpaper.
```

**U2:**

```python
(profiles / "work.profile").symlink_to(dotfiles / "work.profile")
data.list_profiles()                       # -> only the non-symlinked profiles
data.discover_profile_inventory().diagnostics   # -> [('work.profile', 'SYMLINK')], never shown
```

**U3:**

```sh
python -m superpaper --help    # in a KDE session without dbus-python: ModuleNotFoundError: dbus
```

**U7:** 4 profiles × 2 displays × 5,000 empty `*.jpg` → `discover_profile_inventory()`
takes 278 ms and makes 40,001 `os.path.realpath` calls.

**U9, U10, U11, U15:**

- `TempProfileData.test_save` on a folder of `IMG_0001.JPG` → `False` plus a dialog.
- `display0paths=/x/eq=dir` → `paths_array == [['/x/eq']]`.
- `GeneralSettingsData()` ×3 with `logging=true` → 6 handlers.
- `remove_old_temp_files(".../work-a.png")` deletes `homework-b-crop-0.png` and
  `network-b-crop-0.png`.

**U12:**

| Command | Exit code |
|---|---|
| `-s /nonexistent.png` | 0 |
| `-o 1 2` | 0, no output |
| `-p ../x` | 0 |
| `-p missing` | 1 |
| `superpaper` without wx | 0, no output |

**L1:** `hash(tuple(displays))` is identical under `PYTHONHASHSEED` 0, 1 and 12345; it
would differ if a `str` were included.

**PEP 758:** writing `except (ValueError, TypeError):` and running `ruff format` with the
project config produces `except ValueError, TypeError:`.

**Placebo isolation:** after a full run, `sp_paths.CONFIG_PATH` for the *last* test is
`.../test_active_profile_round_trip0/config/superpaper`.
