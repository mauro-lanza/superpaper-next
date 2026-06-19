#!/usr/bin/env bash
# Builds the host-isolated Superpaper AppImage. Single entry point:
#
#     ./release-tooling/appimage/build.sh
#         -> releases/Superpaper-<version>-x86_64.AppImage
#
# It runs in two phases, in different environments:
#   * Host phase (default): builds the Ubuntu 22.04 image and re-runs THIS
#     script inside the container.
#   * Container phase (`--in-container`, invoked automatically by the host
#     phase): the actual PyInstaller build, AppDir assembly, GTK staging and
#     packaging. Don't run this phase directly on the host -- it would bundle
#     the host's glibc/GTK and reintroduce the #170/#164/#169 version-skew bugs
#     the container exists to avoid.
#
# Docker access: if your user isn't in the `docker` group, run with sudo or set
#     DOCKER="sudo docker" ./release-tooling/appimage/build.sh
set -euo pipefail

IMAGE="superpaper-appimage-builder"

# ===========================================================================
# Container phase -- runs INSIDE the Ubuntu 22.04 build image (see Dockerfile).
#
# Produces a self-contained, host-isolated Superpaper AppImage:
#   1. PyInstaller --onedir build of the app (deps come from the image's venv).
#   2. Assemble an AppDir whose layout matches Superpaper's frozen resource
#      resolution (PATH = dirname(dirname(exe)) -> usr).
#   3. Stage the GTK runtime data (gsettings schemas, gdk-pixbuf loaders, a
#      fallback font) from THIS container so it matches the bundled libraries.
#   4. Package with appimagetool.
# ===========================================================================
if [ "${1:-}" = "--in-container" ]; then

VERSION="${2:?internal error: missing version (run build.sh with no args)}"
SRC=/src
WORK=/build
APPDIR="${WORK}/AppDir"
OUT=/out

echo "==> Preparing writable source copy"
rm -rf "${WORK}"
mkdir -p "${APPDIR}" "${OUT}" "${WORK}/src"
# Copy only what the build needs (the package + packaging metadata), not the
# whole repo -- avoids dragging releases/ (large AppImages), .git, snap and
# other artifacts into the container on every build.
for path in superpaper setup.py pyproject.toml README.md MANIFEST.in; do
    cp -a "${SRC}/${path}" "${WORK}/src/"
done
cd "${WORK}/src"

# The Python build venv (wxPython, runtime deps, PyInstaller) is baked into the
# image as a cached layer (see Dockerfile) and is already on PATH. Only the app
# changes between builds, so install just that here -- the expensive deps are
# already satisfied in the venv, so pip skips them and only adds the small
# remaining ones.
echo "==> Installing Superpaper into the prebuilt venv"
pip install .

echo "==> Running PyInstaller (onedir)"
# Exclude the unused Tk bindings to trim the bundle (the app is wxPython/GTK;
# nothing here uses tkinter). NOTE: do NOT add --strip -- stripping corrupts
# NumPy's bundled OpenBLAS (.so), producing an "ELF load command address/offset
# not page-aligned" ImportError at runtime.
pyinstaller --noconfirm --clean --onedir --name superpaper \
    --exclude-module tkinter --exclude-module _tkinter \
    --console superpaper/__main__.py

echo "==> Assembling AppDir"
mkdir -p \
    "${APPDIR}/usr/bin" \
    "${APPDIR}/usr/lib/gio/modules" \
    "${APPDIR}/usr/lib/gdk-pixbuf-2.0/2.10.0/loaders" \
    "${APPDIR}/usr/share/glib-2.0/schemas" \
    "${APPDIR}/usr/share/fonts" \
    "${APPDIR}/usr/share/icons"

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

echo "==> Installing AppRun and desktop entry"
# Reverse-DNS application id so the AppStream metainfo <id>, its <launchable>
# desktop-id, and the installed .desktop filename all match (AppStream/spec
# convention). The window app_id stays "Superpaper" via StartupWMClass.
APP_ID="io.github.hhannine.Superpaper"
cp "${SRC}/release-tooling/appimage/AppRun" "${APPDIR}/AppRun"
chmod +x "${APPDIR}/AppRun"
cp superpaper/resources/superpaper.desktop "${APPDIR}/${APP_ID}.desktop"
# Also place the entry where desktop-integration tools and compositors look.
mkdir -p "${APPDIR}/usr/share/applications"
cp superpaper/resources/superpaper.desktop "${APPDIR}/usr/share/applications/${APP_ID}.desktop"

# Validate the desktop entry early for a clearer message than the late failure
# appimagetool would emit (it validates too). Non-fatal: benign warnings must
# not break the build.
if command -v desktop-file-validate >/dev/null 2>&1; then
    desktop-file-validate "${APPDIR}/${APP_ID}.desktop" \
        || echo "warning: desktop-file-validate reported issues (continuing)"
fi

echo "==> Staging AppStream metainfo"
# Ships app metadata so app stores / AppImageHub can index it and appimagetool
# stops warning about its absence.
mkdir -p "${APPDIR}/usr/share/metainfo"
cp "${SRC}/release-tooling/appimage/${APP_ID}.metainfo.xml" \
    "${APPDIR}/usr/share/metainfo/${APP_ID}.metainfo.xml"

echo "==> Generating hicolor icon theme from the SVG master"
# Ship the SVG as the canonical scalable icon plus PNG buckets rendered natively
# from it (no upscaling). Window decorations, launchers and the taskbar each
# request a different size and resolve the icon by NAME through the hicolor theme
# (Icon=superpaper); SVG-capable toolkits use the scalable icon directly.
ICON_SVG="superpaper/resources/superpaper.svg"
SCALABLE_DIR="${APPDIR}/usr/share/icons/hicolor/scalable/apps"
mkdir -p "${SCALABLE_DIR}"
cp "${ICON_SVG}" "${SCALABLE_DIR}/superpaper.svg"
for size in 16 24 32 48 64 128 256; do
    ICON_DST_DIR="${APPDIR}/usr/share/icons/hicolor/${size}x${size}/apps"
    mkdir -p "${ICON_DST_DIR}"
    rsvg-convert -w "${size}" -h "${size}" "${ICON_SVG}" \
        -o "${ICON_DST_DIR}/superpaper.png"
done
# Root icon + .DirIcon (the AppImage file thumbnail): the spec recommends a
# 128/256 PNG here. appimagetool derives .DirIcon from this root icon.
cp "${APPDIR}/usr/share/icons/hicolor/256x256/apps/superpaper.png" "${APPDIR}/superpaper.png"

echo "==> Packaging AppImage"
export ARCH=x86_64
export APPIMAGE_EXTRACT_AND_RUN=1
appimagetool "${APPDIR}" "${OUT}/Superpaper-${VERSION}-x86_64.AppImage"

echo "==> Done: ${OUT}/Superpaper-${VERSION}-x86_64.AppImage"
exit 0
fi

# ===========================================================================
# Host phase (default) -- build the image, then re-run this script inside it.
# ===========================================================================
DOCKER="${DOCKER:-docker}"

# Repo root (this script lives in release-tooling/appimage/).
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${REPO_ROOT}"

VERSION="$(sed -n 's/^__version__ *= *"\(.*\)"/\1/p' superpaper/__version__.py)"
if [ -z "${VERSION}" ]; then
    echo "error: could not read version from superpaper/__version__.py" >&2
    exit 1
fi
echo "==> Building Superpaper ${VERSION} AppImage"

# Build context is the repo root (cd'd to above) so the image can bake in the
# Python deps from requirements_full_linux.txt. .dockerignore keeps the context
# small; the Dockerfile itself lives under release-tooling/appimage/.
${DOCKER} build -t "${IMAGE}" -f release-tooling/appimage/Dockerfile .

mkdir -p releases
${DOCKER} run --rm \
    -v "${REPO_ROOT}:/src:ro" \
    -v "${REPO_ROOT}/releases:/out" \
    "${IMAGE}" \
    bash /src/release-tooling/appimage/build.sh --in-container "${VERSION}"

echo "==> AppImage written to releases/Superpaper-${VERSION}-x86_64.AppImage"
