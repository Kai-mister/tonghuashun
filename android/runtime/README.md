# Android CPython runtime

ARM64 CPython 3.14 runtime repackaged from the existing deployed Android distribution; no user data is included. `runtime.zip` contains the standard library, CA certificates, Asia/Shanghai timezone and native-library link map. `native.zip` contains only ELF runtime libraries and the Python executable, installed by Android into the read-only APK native library directory.

Python license: `runtime.zip:prefix/lib/python3.14/LICENSE.txt`. Runtime files are kept separate from backend source updates. Build requires both ZIP files. Regenerate with `scripts/package-android-runtime.py PREFIX PYTHON CA_PEM ZONEINFO OUTPUT_DIR` using a trusted Android ARM64 distribution.
