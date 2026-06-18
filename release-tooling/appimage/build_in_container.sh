#!/bin/bash
# Runs INSIDE the Ubuntu 22.04 build container (see Dockerfile).
#
# Produces a self-contained, host-isolated Superpaper AppImage:
#   1. PyInstaller --onedir build of the app (+ wxPython and deps).
#   2. Assemble an AppDir whose layout matches Superpaper's frozen resource
#      resolution (PATH = dirname(dirname(exe)) -> usr).
#   3. Stage the GTK runtime data (gsettings schemas, gdk-pixbuf loaders, a
#      fallback font) from THIS container so it matches the bundled libraries.
#   4. Package with appimagetool.
#
# Usage: build_in_container.sh <version>
set -euo pipefail

VERSION="${1:?usage: build_in_container.sh <version>}"
SRC=/src
WORK=/build
APPDIR="${WORK}/AppDir"
OUT=/out
# wxPython has no universal manylinux wheel; use the prebuilt Ubuntu 22.04 wheel.
WX_INDEX="https://extras.wxpython.org/wxPython4/extras/linux/gtk3/ubuntu-22.04"

echo "==> Preparing writable source copy"
rm -rf "${WORK}"
mkdir -p "${APPDIR}" "${OUT}" "${WORK}/src"
cp -a "${SRC}/." "${WORK}/src/"
cd "${WORK}/src"

echo "==> Creating build virtualenv"
python3 -m venv /opt/venv
# shellcheck disable=SC1091
. /opt/venv/bin/activate
pip install --upgrade pip wheel

echo "==> Installing wxPython + runtime deps + PyInstaller"
pip install -f "${WX_INDEX}" wxPython
pip install -r requirements_full_linux.txt
pip install pyinstaller
pip install .

echo "==> Running PyInstaller (onedir)"
pyinstaller --noconfirm --clean --onedir --name superpaper \
    --console superpaper/__main__.py

echo "==> Assembling AppDir"
mkdir -p \
    "${APPDIR}/usr/bin" \
    "${APPDIR}/usr/lib/gio/modules" \
    "${APPDIR}/usr/lib/gdk-pixbuf-2.0/2.10.0/loaders" \
    "${APPDIR}/usr/share/glib-2.0/schemas" \
    "${APPDIR}/usr/share/fonts" \
    "${APPDIR}/usr/share/icons" \
    "${APPDIR}/usr/share/icons/hicolor/256x256/apps"

# PyInstaller onedir output (exe + _internal) -> usr/bin. With the exe at
# usr/bin/superpaper, Superpaper's frozen PATH resolves to usr, so it looks for
# resources under usr/superpaper/resources (staged below).
cp -a dist/superpaper/. "${APPDIR}/usr/bin/"

echo "==> Staging application resources"
mkdir -p "${APPDIR}/usr/superpaper"
cp -a superpaper/resources "${APPDIR}/usr/superpaper/"
cp -a superpaper/profiles "${APPDIR}/usr/superpaper/" 2>/dev/null || true

echo "==> Bundling gsettings schemas"
cp -a /usr/share/glib-2.0/schemas/*.xml "${APPDIR}/usr/share/glib-2.0/schemas/" 2>/dev/null || true
cp -a /usr/share/glib-2.0/schemas/*.gschema.override "${APPDIR}/usr/share/glib-2.0/schemas/" 2>/dev/null || true
glib-compile-schemas "${APPDIR}/usr/share/glib-2.0/schemas"

echo "==> Bundling gdk-pixbuf loaders + librsvg (SVG theme icons / combo arrows)"
GP_HOST="/usr/lib/x86_64-linux-gnu/gdk-pixbuf-2.0"
INTERNAL="${APPDIR}/usr/bin/_internal"
cp -a "${GP_HOST}/2.10.0/loaders/." "${APPDIR}/usr/lib/gdk-pixbuf-2.0/2.10.0/loaders/"

# The SVG loader (used for GTK symbolic icons such as the combo-box dropdown
# arrow) needs librsvg and its non-glibc deps. PyInstaller doesn't bundle them
# because nothing links them directly -- the loader is dlopened at runtime -- so
# copy them next to the other bundled libs, where the loader resolves them via
# PyInstaller's existing search path. glibc / dynamic-loader libs are skipped on
# purpose so the bundle keeps using the host's matching ones.
SKIP_RE='^(libc|libpthread|libdl|libm|librt|libresolv|libutil|ld-linux)'
bundle_deps() {
    ldd "$1" 2>/dev/null | awk '{print $3}' | grep '^/' | while read -r dep; do
        base="$(basename "${dep}")"
        echo "${base}" | grep -qE "${SKIP_RE}" && continue
        [ -e "${INTERNAL}/${base}" ] && continue
        cp -aL "${dep}" "${INTERNAL}/"
    done
}
RSVG="$(ldconfig -p | awk '/librsvg-2\.so\.2 /{print $NF; exit}')"
[ -n "${RSVG}" ] && cp -aL "${RSVG}" "${INTERNAL}/"
# A few passes so transitive deps (e.g. librsvg -> libxml2 -> liblzma) get pulled.
for _pass in 1 2 3; do
    for so in "${APPDIR}"/usr/lib/gdk-pixbuf-2.0/2.10.0/loaders/*.so \
              "${INTERNAL}"/librsvg-2.so.2 "${INTERNAL}"/libxml2.so.2; do
        [ -e "${so}" ] && bundle_deps "${so}"
    done
done

# Relocatable loader cache: built against the bundled loaders, with the build
# time AppDir prefix replaced by the @APPDIR@ token that AppRun rewrites at
# launch (the cache stores absolute loader paths). Built-in png/jpeg keep working
# regardless of the cache contents.
GP_QUERY="${GP_HOST}/gdk-pixbuf-query-loaders"
[ -x "${GP_QUERY}" ] || GP_QUERY="$(command -v gdk-pixbuf-query-loaders)"
"${GP_QUERY}" "${APPDIR}"/usr/lib/gdk-pixbuf-2.0/2.10.0/loaders/*.so \
    | sed "s|${APPDIR}|@APPDIR@|g" \
    > "${APPDIR}/usr/lib/gdk-pixbuf-2.0/2.10.0/loaders.cache"

echo "==> Bundling fallback font + icon themes + mime database"
cp -a /usr/share/fonts/truetype/dejavu "${APPDIR}/usr/share/fonts/" 2>/dev/null || true
cp -a /usr/share/icons/hicolor "${APPDIR}/usr/share/icons/" 2>/dev/null || true
cp -a /usr/share/icons/Adwaita "${APPDIR}/usr/share/icons/" 2>/dev/null || true
cp -a /usr/share/mime "${APPDIR}/usr/share/" 2>/dev/null || true

# usr/lib/gio/modules is intentionally left EMPTY: with GIO_MODULE_DIR pointed
# here, GLib loads no host gio modules (the #170 undefined-symbol trigger).

echo "==> Installing AppRun, desktop entry and icon"
cp "${SRC}/release-tooling/appimage/AppRun" "${APPDIR}/AppRun"
chmod +x "${APPDIR}/AppRun"
cp superpaper/resources/superpaper.desktop "${APPDIR}/superpaper.desktop"
cp superpaper/resources/superpaper.png "${APPDIR}/superpaper.png"
cp superpaper/resources/superpaper.png "${APPDIR}/usr/share/icons/hicolor/256x256/apps/superpaper.png"

echo "==> Packaging AppImage"
export ARCH=x86_64
export APPIMAGE_EXTRACT_AND_RUN=1
appimagetool "${APPDIR}" "${OUT}/Superpaper-${VERSION}-x86_64.AppImage"

echo "==> Done: ${OUT}/Superpaper-${VERSION}-x86_64.AppImage"
