# Reproducible build environment for the Superpaper Linux AppImage.
#
# Why a container on an OLD base (Ubuntu 22.04, glibc 2.35):
#   An AppImage bakes in the build machine's glibc and bundles the GTK/glib/
#   fontconfig shared libraries present at build time. Building on a bleeding
#   edge host (e.g. CachyOS/Arch, glibc 2.4x) produces an AppImage that refuses
#   to start on anything older, and whose bundled libraries clash with newer
#   *host* gio modules / gsettings schemas / fontconfig configs at runtime --
#   exactly the failures reported in issues #170, #164 and #169.
#
#   Building on Ubuntu 22.04 gives a low glibc floor (wide compatibility) AND a
#   single, internally consistent GTK stack: the libraries PyInstaller bundles
#   and the schemas / pixbuf loaders / fonts we stage into the AppDir all come
#   from the same distro release, so they match each other. The AppRun then
#   isolates the app from the host so version skew can never break it again.
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
        # Python + build toolchain (some deps like dbus-python build from sdist)
        python3 python3-venv python3-dev python3-pip \
        build-essential pkg-config \
        libglib2.0-dev libdbus-1-dev libdbus-glib-1-dev \
        wget ca-certificates file desktop-file-utils \
        # GTK 3 stack + the auxiliary data/tools we stage into the AppDir
        libgtk-3-0 libgtk-3-bin \
        libglib2.0-0 libglib2.0-bin \
        gsettings-desktop-schemas \
        # librsvg2-bin provides rsvg-convert, used to render the SVG icon
        # master into the hicolor PNG buckets at build time.
        librsvg2-common librsvg2-bin libgdk-pixbuf-2.0-0 libgdk-pixbuf2.0-bin \
        fontconfig fonts-dejavu-core \
        shared-mime-info hicolor-icon-theme adwaita-icon-theme \
        # wxPython / Superpaper runtime shared libraries (so PyInstaller can
        # follow and bundle them)
        libnotify4 libsdl2-2.0-0 libgl1 libglu1-mesa \
        libpng16-16 libjpeg-turbo8 libtiff5 libwebp7 \
        libsecret-1-0 libcurl4 \
        libpango-1.0-0 libpangocairo-1.0-0 libcairo2 \
        libdbus-1-3 libdbus-glib-1-2 \
        libxcb1 libxcb-render0 libxcb-shm0 \
        libx11-6 libxext6 libxtst6 libxi6 libsm6 libice6 libxrandr2 libxinerama1 \
    && rm -rf /var/lib/apt/lists/*

# --- Python build environment (cached image layer) -------------------------
# Install the heavy Python build/runtime dependencies into a venv at IMAGE
# BUILD time so they live in a cached layer instead of being rebuilt on every
# container run (wxPython, numpy and dbus-python-from-sdist are expensive).
# The container phase of build.sh then only (re)installs the app itself, which
# is the only thing that changes between builds. Putting the venv on PATH means
# later layers and the runtime build use it without an explicit `activate`.
#
# wxPython has no universal manylinux wheel; it comes from the prebuilt Ubuntu
# 22.04 wheel index, pinned to the runtime-verified 4.2.5.
#
# The runtime dependencies come from the project's pyproject.toml [linux] extra
# (the single source of truth). Only the packaging metadata + the (stable)
# bundled resources are COPYied here -- not the app's .py source -- so this
# heavy layer stays cached across source edits and rebuilds only when the
# declared dependencies (or version/resources) change; the real app is
# installed in build.sh. wxPython is installed first and is in the `gui` extra,
# not `linux`, so the metadata install below leaves the pinned 4.2.5 untouched.
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="${VIRTUAL_ENV}/bin:${PATH}"
COPY pyproject.toml README.md LICENSE /tmp/superpaper-deps/
COPY superpaper/__init__.py superpaper/__version__.py /tmp/superpaper-deps/superpaper/
COPY superpaper/resources /tmp/superpaper-deps/superpaper/resources
COPY superpaper/profiles /tmp/superpaper-deps/superpaper/profiles
RUN python3 -m venv "${VIRTUAL_ENV}" \
    && pip install --no-cache-dir --upgrade pip wheel \
    && pip install --no-cache-dir \
        -f "https://extras.wxpython.org/wxPython4/extras/linux/gtk3/ubuntu-22.04" \
        "wxPython==4.2.5" \
    && pip install --no-cache-dir "/tmp/superpaper-deps[linux]" \
    && pip install --no-cache-dir pyinstaller

# appimagetool packages the finished AppDir into a single-file AppImage.
# APPIMAGE_EXTRACT_AND_RUN lets it run without FUSE inside the container.
#
# AppImage only publishes a rolling "continuous" tag, so we pin by SHA256
# instead of a version: the build fails if the fetched asset ever differs from
# the reviewed one, guarding against a silently changed/compromised upstream.
# To upgrade, download the new asset, verify it, and update APPIMAGETOOL_SHA256.
ARG APPIMAGETOOL_SHA256=a6d71e2b6cd66f8e8d16c37ad164658985e0cf5fcaa950c90a482890cb9d13e0
RUN wget -q -O /usr/local/bin/appimagetool \
        "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage" \
    && echo "${APPIMAGETOOL_SHA256}  /usr/local/bin/appimagetool" | sha256sum -c - \
    && chmod +x /usr/local/bin/appimagetool

WORKDIR /build
