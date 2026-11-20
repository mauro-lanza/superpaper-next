# Superpaper UX workflow

How Superpaper is expected to behave for every user interaction. This is the
specification to check the code against, not a description of the current code.
Every decision in §4 is decided; body text applies the chosen option, referenced as D-numbers.

## 1. Concepts and state

### 1.1 Terms

- **Render**: compose a profile's image(s) for a layout and set them on the desktop. Desktops that take one image per display (macOS, KDE, and any custom set command containing a per-display placeholder) get one piece per display; others get one spanned image. The user sees the same result either way.
- **Re-detect**: query the OS for the connected displays (count, resolution, physical size, order) and load LAY saved for that display set (its *key*). Happens at: app start, editor open, tray profile pick, profile hotkey, Apply, band Save, tests, and when the OS reports a display change (added, removed, resolution, arrangement) (D17). Not before every Next or slideshow tick. Where an OS cannot report changes, it also happens on manual Next.
- **Hot update**: the running profile's stored settings are replaced (Save, rename, Reload Profiles); RUN keeps running with the new settings without re-rendering (D13).
- **Running** = in RUN. **Active** = in ACT. **Loaded** (editor) = the profile in FORM.
- **Slideshow profile**: advances SEL every *delay* while running and not paused. A non-slideshow profile never advances on its own.
- **Valid layout**: no two displays overlap (bezels included). Positions, bezels and diagonals only produce valid layouts or are rejected (§1.3).

### 1.2 State items

| ID | State | Lives in | Changed only by |
| --- | --- | --- | --- |
| **PROF** | Stored profile: name, span mode, sources, slideshow (on, delay, sort), zoom/pan, manual offsets, span groups, perspective choice, hotkey | `<name>.profile` | Editor Save, Apply (implicit save, D1), Delete, Reload Profiles after outside edits |
| **SEL** | Profile selection: the ordered image list and the current position in it. Simple/advanced mode: one image for all displays (or one per span group). Multi-image mode: one current image **per display** (per source list). One SEL per stored profile | Profile cache, persisted | Apply (PICK), Next, slideshow change, Save with a PICK (D13), Delete (removed) |
| **RUN** | Running profile, slideshow deadline, *paused* | Memory | Apply, tray pick, profile hotkey, startup, Next/tick (deadline), Pause, hot update, Delete of running, Reload (file gone), Quit |
| **ACT** | Active profile: what runs at next start | Cache file | Every change of which profile runs, rename of the running profile, Delete of running |
| **LAY** | Saved layout for the current display set: positions, bezels, hand-entered diagonals, perspective definitions, perspectives on/off, default perspective | `display_systems.dat`, `<key>.persp` | Band Save (including staged perspective changes, D19), Apply "save displays" (D4) |
| **STG** | Staged layout: editor's copy of LAY with unsaved band edits | Editor memory | Band edits; reset to LAY on editor open, band Revert, band Save, display set change |
| **FORM** | Editor form: loaded profile (or *new*), edited values, *dirty* | Editor memory | Field edits, dropdown, New, Save, Revert, Delete |
| **PICK** | Image chosen by clicking a source row (in multi mode: per display) | Editor memory | Source row click; cleared on profile switch, New, Revert, Save, Apply, row removal |
| **PREV** | In-dialog preview of FORM + STG + (PICK or SEL) | Editor | Follows FORM, STG, PICK |
| **DESK** | What the desktop shows | OS | Renders of RUN, Apply, tests, CLI `--setimages` |
| **CACHE** | Last render per profile and per-display pieces | Render cache | Every render; read by startup restore |
| **GEN** | General settings: logging, hotkeys on/off, Next/Pause hotkeys, custom set command, large-image warning, help at start, browse start folder | `general_settings` | Settings Save, Help "show at start", Browse "Save/Clear as browse start" |

### 1.3 Invariants

1. RUN is empty or a stored profile; an unsaved form never runs.
2. ACT = RUN whenever RUN is non-empty; ACT is cleared when the running profile is deleted.
3. Every render of RUN (Apply, Next, tick, tray pick, hotkey, startup) uses LAY for the displays detected at that moment. STG reaches the desktop only through tests (D7), never through RUN.
4. DESK shows RUN's SEL rendered with LAY, except after an explicit test or CLI `--setimages`. A test pauses RUN while shown (D8); the user leaves it with Next, Apply, unpause or tray pick.
5. Saving LAY while a profile runs re-renders RUN's current SEL (no advance), so DESK satisfies invariant 3 at once.
6. **Save never changes DESK** (D13). Changes saved to the running profile appear at its next change (Next, tick) or immediately with Apply.
7. Saving FORM never changes which profile runs; only Apply, tray pick, hotkey and startup do.
8. SEL survives Next, editor close, Reload Profiles and restart.
9. Editor state (FORM, STG, PICK, PREV) is discarded when the editor closes; only what was saved remains.
10. An invalid layout is never saved, rendered or kept as loaded: band edits that would overlap are rejected or rearranged (D20); a saved layout that loads invalid (corrupt, or displays changed size) is replaced in memory by the default arrangement with a one-time message, and LAY on disk is untouched until the user saves (D22).
11. Ticks always render the **stored** profile; edits, PICK and STG never affect a tick. Apply restarts the timer; a tick due during a render runs after it.
12. The tray menu reflects RUN and *paused* each time it opens. Expected states: **Profiles** submenu lists stored profiles, running one checked (empty submenu shows a disabled "(no profiles)"); **Next Wallpaper** disabled when nothing runs; **Pause Timer** checked iff paused, disabled unless a slideshow profile runs.
13. One editor and one settings window at most; reopening raises the existing one.

## 2. Interaction catalogue

Unlisted state is unchanged. Unlisted errors show one modal naming the problem; state unchanged.

### 2.1 Editor window

#### E1 Open editor (tray left-click, "Wallpaper Configuration")
- Already open: raise; nothing else.
- Re-detect. STG := LAY (default arrangement + message if invalid, inv. 10).
- FORM: RUN if any, else the profile last loaded or saved in the editor this app session (kept in memory only), else *new* (also when that profile was deleted) (D18). Dropdown (read-only list of stored profiles + "Create a new profile") marks the running one "(running)".
- PICK empty. PREV: SEL with STG; *new*: empty display outlines.
- Edge: no displays detected → error; editor opens on the last known layout with band Save disabled. Missing images → outlines and a note.

#### E2 Pick a profile in the dropdown
- FORM dirty → Save / Discard / Cancel (D5). Cancel re-selects the previous entry; Save = E9, continues only on success.
- FORM := picked, clean; PICK cleared; PREV: its SEL with STG. STG unchanged; no re-detect (D23).

#### E3 New profile
Same prompt as E2; FORM := blank defaults, clean; PICK cleared; PREV outlines.

#### E4 Profile fields
Name; span mode radio (simple / advanced / multi-image); slideshow checkbox, delay (minimum 5 s), sort; zoom slider, pan X/Y sliders, zoom Reset; manual offsets checkbox and per-display x/y fields; span groups checkbox and per-display group combos; perspective combo; hotkey checkbox and binding field.
- FORM dirty iff values differ from loaded (editing back clears it). Save/Revert enabled only while dirty. PREV updates live.
- Slideshow on: zoom/pan reset and disabled; a sort is selected if none. Off: zoom/pan enabled.
- Advanced-only controls (offsets, span groups, perspective, Positions) shown only in advanced mode.
- Span mode change converts sources (one list ↔ one per display); if sources would be lost, confirm; Cancel keeps the old mode.
- Span groups: each display's combo assigns it to a group; source lists follow the group count. Single display: span groups and per-display controls disabled (one entry).
- Perspective combo lists "default", LAY's named perspectives, "disabled"; the combo is disabled when LAY has perspectives off.
- Hotkey field: when GEN hotkeys are off (default on macOS), the field stays editable and saved but shows "Hotkeys are off in Settings" (D24).
- Invalid values (delay < 5 s / non-number, non-integer offsets, unparsable or clashing hotkey) are reported on Save/Apply, all at once.

#### E5 Sources: Browse dialog and Remove selected source
Browse dialog (modal):
- "Show hidden files" toggles hidden entries in the file tree.
- Display/Group radio (multi mode or span groups only): which display/group the next Add targets.
- The dialog opens empty. **Add source**: adds the selected file/folder to the dialog's list (to the chosen target); duplicates ignored. **Remove source** (dialog): removes the selected row from the dialog's list.
- **Save as browse start** / **Clear browse start**: change GEN immediately (even if the dialog is cancelled).
- **Ok**: adds the dialog's paths to the editor's sources, ignoring duplicates; FORM dirty if sources changed. **Cancel**: nothing changes except browse start.
Editor **Remove selected source**: removes the selected row; none selected → no-op; clears PICK if it was that row; FORM dirty.

#### E6 Click a source row
- PICK := that file, or for a folder the first image in the profile's sort order (D12a). Multi mode: PICK for that row's display only; other displays show SEL (D12b).
- PREV shows FORM with PICK and STG. FORM not dirtied.
- Empty folder / missing file → PREV unchanged, note shown; PICK unchanged.

#### E7 Apply
Apply shows the selected image on the desktop and makes this profile the running one.
1. FORM valid (E9 rules); if dirty or *new*, it is saved first (D1); failure stops here.
2. If STG ≠ LAY: prompt "Displays have unsaved changes" — **Save displays and apply** / **Apply with saved displays** / **Cancel** (D4). STG invalid → only the last two options.
3. Order: layout save (if chosen) → SEL := PICK, else current SEL (D3) → RUN := profile, *paused* := false, timer from now (D2) → ACT := profile → one render with LAY.
- Already running: same; shows the selected image, not the next (decided).
- FORM clean, PICK cleared, dropdown/tray mark it running.
- No images found → error before any change. Render fails → tray "Last change failed: …"; RUN/ACT still set.

#### E8 Try without applying
Field edits, clicks, band edits only change FORM, PICK, STG, PREV. Close with Discard leaves PROF, SEL, RUN, ACT, LAY, DESK as before the editor opened.

#### E9 Save (profile)
- Valid FORM: non-empty name, unique (case-insensitive where the OS requires), legal file name; at least one source; every source exists and yields ≥ 1 image (empty folder → error naming it); E4 values valid; hotkey not used elsewhere.
- PROF := form. SEL: unchanged; with a PICK, SEL := PICK (stored, shown at the next change) (D13). New profile: SEL at the first image of the sort order.
- Running: hot update; DESK unchanged (inv. 6); timer and pause unchanged.
- Rename: file renamed, SEL/hotkey/RUN/ACT follow; no copy left (D14).
- STG ≠ LAY: Save does not save the layout; the band keeps its unsaved marker (D25).
- FORM clean, PICK cleared, PREV shows the saved SEL.
- Write fails → error, FORM stays dirty.

#### E10 Revert (profile)
Enabled while dirty. FORM := stored version reloaded from disk; *new* → blank. PICK cleared.

#### E11 Delete
Stored profile only; confirm. PROF, SEL, CACHE entry removed; hotkey unbound. Running: RUN empty, ACT cleared (D6), DESK keeps the last wallpaper. FORM := *new*.

#### E12 Close (button or window close)
- FORM dirty and/or STG ≠ LAY → one prompt listing what is unsaved: Save / Discard / Cancel (D5). Save saves both; any failure (invalid form, invalid layout, write error) keeps the editor open with the error shown.
- Otherwise closes. State as E8.

#### E13 Align Test
- Renders the test image with FORM's offsets/perspective and **STG** (to check unsaved bezels/positions) (D7). STG invalid → refused with the overlap message.
- RUN paused while shown (inv. 4); tray shows Pause checked. PROF, SEL, ACT, LAY, FORM unchanged.

#### E14 Perspectives dialog (modal)
Controls: perspective combo (stored perspectives + New), name field, New / Save / Delete, "Use perspective corrections", "Default for this display setup", central display combo, viewer offset fields, per-display swivel-axis combo and rotation fields, Help buttons, Align test, Pick image (file dialog; Cancel keeps the previous image), Test image, OK, Close.
- Field and combo edits are dialog-local.
- Save / Delete / corrections checkbox / default checkbox / OK: stage the change into STG with the display band; the band's Save writes it to LAY (D19). Validation errors, large-image confirmation as dialogs.
- Close: discards unsaved dialog edits; staged changes stay in STG.
- Align test / Test image: stage the perspective, then test as E13 with the picked image (Test image without a picked image: tells the user to pick one).
- Deleted perspective chosen by the loaded form → form falls back to "default" and is dirty. After band Save, a running profile using a changed/deleted perspective is re-rendered with its current SEL (inv. 5).
- Single display: dialog shows one row; perspectives still allowed.

#### E15 Help
Editor Help (bottom row), preview Help, hotkey/span-group/bezel/position Help: popups or the Help window only. Help window "Show this help at start" changes GEN.

### 2.2 Display band ("Display system settings (apply to all profiles)")

Band edits change STG and PREV only. Band Save/Revert enabled while STG ≠ LAY; a "Displays: unsaved" marker shows meanwhile. Profile controls are disabled while Positions or Bezels mode is open.

| ID | Interaction | Expected effect |
| --- | --- | --- |
| B1 | Expand/collapse | Layout only. |
| B2 | "Input display sizes manually" on/off; type a diagonal | Valid input: a number 1–1000 inches per display (decimal point or comma). Partial/invalid text: field marked red, STG unchanged, Save disabled while any field is invalid. Valid: STG diagonals updated; positions handled per D20 so STG stays valid. Off: detected sizes, typed values remembered for turning back on. |
| B3 | Bezels: Configure → per-edge buttons (right/bottom of each display) open a popup: value field (mm, ≥ 0; Enter = Apply), Apply, Cancel → Done / Cancel | Popup Apply stages the edge into the in-progress bezels (neighbours shift so no overlap); invalid value → field marked, nothing staged. Done: STG bezels := in-progress. Cancel: back to before Configure. |
| B4 | Positions (advanced mode): drag, Reset (default arrangement), Exact entry → Done / Cancel | Drags and Reset are in-progress. Exact entry dialog: per-display x/y fields (Enter or Preview redraws), "Use pixels (exact)" converts units, **Apply** copies values into the in-progress positions and closes, Cancel closes without change. Overlapping result → Done refused with message. Done stages into STG; the inner button is labelled "Done" (D10). Cancel restores. FORM never dirtied. Help: popup. |
| B5 | Band Revert | STG := LAY. |
| B6 | Band Save | STG valid required. LAY := STG for the current key. Running profile re-rendered (inv. 5), timer/pause unchanged. Write failure → error, STG stays unsaved. |

### 2.3 Tray

| ID | Interaction | Expected effect |
| --- | --- | --- |
| T1 | Left-click icon | E1 (KDE without native tray: editor opens at start instead). |
| T1m | Middle-click (native tray, Linux) | T4. |
| T2 | Profiles ▸ *not running* | Re-detect; RUN := it, unpaused, timer from now; render its current SEL; ACT := it. |
| T3 | Profiles ▸ *running* | Idempotent: if paused, unpause and restart the timer; DESK unchanged, no advance (D2b). |
| T4 | Next Wallpaper | Enabled only when RUN non-empty. No re-detect, except on an OS that cannot report display changes (D17). SEL advances (multi mode: every display); render; timer from now; *paused* unchanged. Non-slideshow profile with > 1 image: advances (D15). |
| T5 | Pause Timer (check) | Enabled only for a running slideshow. Toggles *paused*; resume restarts the timer. Not persisted (D16). |
| T6 / T7 | Wallpaper Configuration / Settings | E1 / S1. |
| T8 | Reload Profiles | Re-read PROF; malformed → ask delete or ignore. RUN hot-updated (inv. 6); RUN's file gone → as E11 running. Open editor refreshes the dropdown; dirty FORM kept; clean FORM reloaded. |
| T9 / T10 | Open Config Folder / About | Open folder (error if it fails) / dialog. |
| T11 | Exit | Q1. |
| T12 | "Last change failed: …" | Shown first, disabled, while the last change failed; gone after the next success. |

### 2.4 Settings dialog
| ID | Interaction | Expected effect |
| --- | --- | --- |
| S1 | Open | Shows GEN; one instance. |
| S2 | Save | Invalid hotkey → error, nothing saved. GEN := fields. Next/Pause hotkeys rebound now if on. Hotkeys on/off and logging: after restart (message says so). Set command / large-image warning: used from the next render; DESK not re-rendered. |
| S3 | Close | Discards unsaved fields. |

### 2.5 Hotkeys
H1 Next = T4. H2 Pause = T5. H3 profile hotkey = T2/T3; deleted profile → nothing. All inactive while GEN hotkeys are off.

### 2.6 Startup, quit, CLI

| ID | Interaction | Expected effect |
| --- | --- | --- |
| Q0 | Start | Re-detect. ACT names a stored profile → RUN := it, unpaused; DESK: CACHE render if it matches LAY and SEL, else render; timer gets a full delay. Otherwise nothing runs, DESK untouched. Help at start → editor + Help. One-time messages: cannot set wallpapers here; display sizes unknown; saved layout invalid (inv. 10). |
| Q0p | `superpaper --profile NAME [-d]` | Invalid name → print "Invalid profile name: …", exit 1. Displays undetectable or saved layout unreadable → message, exit 1. Unknown name → "No profile was found by the given name: … Valid profile names are: […]", exit 1, no tray. Else start as Q0 but run NAME as T2. |
| Q0d | `superpaper -d` | Start as Q0 with debug logging to the console. |
| Q1 | Exit | Editor open with unsaved changes → E12 prompt; Cancel or a failed Save aborts the quit. Then stop timer, wait briefly for a change in progress, remove icon. ACT unchanged. |
| C1 | `-s IMG… [-a] [--perspective P] [--spangroups G…] [-o X Y…] [-c CMD] [-d]` | Sets those images once with LAY (re-detected), exits 0; no tray; PROF/RUN/ACT unchanged; a running tray app is unaffected until its next change. Errors (exit 1, message): odd or non-integer offsets, offsets/perspective/spangroups without `-a`, unknown perspective, bad span groups, missing image, no displays, unreadable layout. |
| C2 | `--help` / unknown option | Usage / argparse error; nothing created or changed. |

### 2.7 Display changes and render failures

| ID | Event | Expected effect |
| --- | --- | --- |
| X1 | Display set changes | Noticed when the OS reports it (D17); on an OS that cannot, at the next manual Next, tray pick or editor open. LAY := saved layout for the new key, else default arrangement. RUN continues; next render fits. Open editor at its next re-detect point: STG reloads (dirty STG → ask first); PICK/sources for a vanished display are kept in FORM but not previewed; PREV redrawn. Per-display sources whose count no longer matches → shown with a warning, Save/Apply ask to fix. |
| X2 | Return to a known set | Its LAY returns unchanged. |
| X3 | Single display | Positions/span groups/per-display controls show one entry; Positions disabled. |
| X4 | Source missing at render | D21. |
| X5 | Corrupt `display_systems.dat` / `.persp` | D22. |

## 3. User journeys

**J1 First run**
1. Start → tray icon; editor + Help open; DESK unchanged; Next/Pause disabled; Profiles submenu "(no profiles)".
2. Close Help with "show at start" unticked → not shown again.

**J2 Create, try, apply**
1. Blank editor → name, Browse a folder, Ok → preview first image; Save enabled.
2. Click a row → preview that image; DESK unchanged.
3. Zoom → preview updates; DESK unchanged.
4. Close → prompt → Discard → nothing saved; no profile in tray.
5. Repeat 1–3, Apply → profile saved; DESK shows the clicked image; tray: profile checked; editor "(running)".
6. One delay later → next image.

**J3 Edit the running profile**
1. Open editor → running profile, preview current image.
2. Change delay, Save → DESK unchanged; timer and pause unchanged; next change uses the new delay (inv. 6).
3. Click another image, Save → DESK unchanged; Next shows the clicked image (D13).
4. Click another image, change zoom, Apply → DESK shows it with the new zoom; timer restarts.
5. Edit, Close → Discard → PROF, DESK unchanged (E8).

**J4 Edit a non-running profile while A runs**
1. Dropdown B → B in preview; DESK still A.
2. Edit B, Save → B stored; DESK and tray still A.
3. Apply on B → DESK B's image; B checked; A stops with its SEL kept.

**J5 Display layout (reported bug path)**
1. Advanced mode, type diagonals → preview densities change; any overlap handled per D20 (no overlapping preview); band "unsaved"; band Save enabled.
2. Positions → drag → **Done** → preview shows positions; band still unsaved; profile Save **not** enabled by this.
3. Bezels → Configure → set edges → Done → preview updated.
4. Profile Save alone → profile saved; band still shows "Displays: unsaved"; LAY not written (D25).
5. Close → prompt lists "display layout"; **Save** → LAY written; DESK re-rendered with the new layout.
6. Tray Next → next image with saved positions/bezels/diagonals.
7. Reopen → band shows the saved values, band Save disabled.
8. Exit, start → same layout on DESK and in the band.
- Variant 5′: band Save before Close → same as 5, no prompt.
- Variant 5″: Apply instead → "Displays have unsaved changes" → Save displays and apply → LAY written, profile running, one render.
- Variant 5‴: Close → Discard → LAY unchanged; Next renders the old layout.

**J6 Rename**
1. Running A, name → C, Save → dropdown C (running); tray C checked, A gone; DESK unchanged; hotkey works.
2. Restart → C runs. 3. Rename to an existing name → error, nothing changes.

**J7 Delete running**
1. Delete A, confirm → gone from dropdown/tray; DESK keeps last wallpaper; Next/Pause disabled; editor *new*.
2. Restart → nothing runs.

**J8 Switch from tray**
1. A running, tray ▸ B → DESK B's current image; B checked; unpaused.
2. Tray ▸ B again → nothing visible changes (unpauses if paused).
3. Restart → B resumes.

**J9 Pause / Next**
1. Pause → checked; DESK stays. 2. Next → next image; still paused.
3. Unpause → next change one delay later. 4. Restart while paused → runs unpaused.

**J10 Unplug / replug**
1. Unplug → OS reports the change; Next → image fits remaining displays with that set's layout (default if never saved).
2. Open editor → band shows that set. 3. Replug, Next → original layout again.

**J11 Quit and restart**
1. Exit with unsaved edits → prompt; Save fails (invalid) → stays open; Discard → quits.
2. Start → last running profile, its current image, fresh delay.

## 4. Decisions

### Decided
| ID | Decision | Chosen |
| --- | --- | --- |
| D1 | How Apply guarantees a stored profile | Implicit save with Save's validation |
| D2 | Apply on the running profile | Restart timer, unpause; shows the selected image, not the next |
| D2b | Tray pick of the running profile | Idempotent: unpause only |
| D3 | Apply with no image clicked | Current SEL |
| D4 | Apply with unsaved layout | Prompt: Save displays and apply / Apply with saved / Cancel |
| D5 | Unsaved changes on Close / switch / New / Exit | Save / Discard / Cancel |
| D6 | Delete running | Stop, clear ACT, wallpaper stays |
| D7 | Test layout | STG (refused if invalid) |
| D8 | Tests and the slideshow | A test pauses RUN while shown (inv. 4) |
| D10 | Positions/Bezels inner button | "Done" stages into STG; does not write LAY |
| D11 | Running marker | Tray check and "(running)" in the dropdown |
| D12a | Clicking a folder row | First image in sort order |
| D12b | Click in multi mode | That display only, others show SEL |
| D13 | May Save change the desktop? | Never; saved changes and PICK show at next change, or Apply |
| D14 | Name change on Save | Rename |
| D15 | Next on non-slideshow | Advances |
| D16 | Pause across restart | Not kept |
| D17 | Display change detection | On OS display-change notification (per OS, see investigation), plus tray pick and editor open; where an OS cannot notify: manual Next, tray pick, editor open |
| D18 | Editor opens on | Running profile, else the profile last loaded or saved this app session (memory only); if deleted, new |
| D19 | Perspectives model | Staged with the band, written by band Save |
| D20 | Diagonal/density edit would overlap | Shift only overlapping displays; fall back to re-arranging all with a message |
| D21 | Source file missing at render | Skip to next image with tray notice; stop only if no image is left |
| D22 | Corrupt or invalid saved layout on load | Default arrangement in memory + message; file untouched until Save |
| D23 | Re-detect on dropdown switch | No |
| D24 | Profile hotkey field while hotkeys are off | Editable + note |
| D25 | Profile Save while the band is unsaved | Saves the profile only; band marker stays |
