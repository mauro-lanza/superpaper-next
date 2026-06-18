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
        wget ca-certificates file desktop-file-utils zsync \
        # GTK 3 stack + the auxiliary data/tools we stage into the AppDir
        libgtk-3-0 libgtk-3-bin \
        libglib2.0-0 libglib2.0-bin \
        gsettings-desktop-schemas \
        librsvg2-common libgdk-pixbuf-2.0-0 libgdk-pixbuf2.0-bin \
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

# appimagetool packages the finished AppDir into a single-file AppImage.
# APPIMAGE_EXTRACT_AND_RUN lets it run without FUSE inside the container.
RUN wget -q -O /usr/local/bin/appimagetool \
        "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage" \
    && chmod +x /usr/local/bin/appimagetool

WORKDIR /build
