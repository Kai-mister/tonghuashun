#!/system/bin/sh
set -eu
cd /data/local/tmp/ths-sim
mkdir -p state
if test -s state/manager.key && test -f phone/manager.py; then
    if ! ss -lnt 2>/dev/null | grep -Fq '127.0.0.1:18735'; then
        setsid sh phone/start.sh manager >>state/manager.log 2>&1 </dev/null &
        echo $! >state/manager.pid
    fi
fi
if ! ss -lnt 2>/dev/null | grep -Fq '[::1]:9008'; then
    setsid env LD_PRELOAD="$PWD/loopback.so" CLASSPATH=/data/local/tmp/u2.jar \
        app_process / com.wetest.uia2.Main -p 9008 >state/ui.log 2>&1 </dev/null &
    sleep 2
    ss -lnt 2>/dev/null | grep -Fq '[::1]:9008' || exit 1
fi
if test -f state/worker.pid && test -r "/proc/$(cat state/worker.pid)/cmdline" &&
    tr '\000' ' ' <"/proc/$(cat state/worker.pid)/cmdline" | grep -Fq 'phone/local.py'; then
    exit 0
fi
setsid sh phone/start.sh >>state/worker.log 2>&1 </dev/null &
echo $! >state/worker.pid
