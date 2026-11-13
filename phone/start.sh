#!/system/bin/sh
set -eu
umask 077
cd /data/local/tmp/ths-sim
export HOME="$PWD" PYTHONHOME="$PWD/prefix" PYTHONPATH="$PWD" LD_LIBRARY_PATH="$PWD/prefix/lib"
export SSL_CERT_FILE="$PWD/ca.pem" PYTHONTZPATH="$PWD/zoneinfo" TZ=Asia/Shanghai
if [ "${1:-}" = manager ]; then exec ./python -u phone/manager.py; fi
exec ./python -u phone/local.py "$@"
