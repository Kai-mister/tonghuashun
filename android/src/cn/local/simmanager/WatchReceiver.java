package cn.local.simmanager;

import android.content.*;
import android.os.PowerManager;

public class WatchReceiver extends BroadcastReceiver {
    @Override public void onReceive(Context context,Intent intent){
        String action=intent.getAction();
        if(Intent.ACTION_SHUTDOWN.equals(action)){BootRestore.shutdown(context);return;}
        if(Intent.ACTION_BOOT_COMPLETED.equals(action))BootRestore.boot(context);
        boolean test="cn.local.simmanager.WAKE_TEST".equals(action);
        if(!test&&!context.getSharedPreferences("local",0).getBoolean("watch_enabled",false))return;
        PowerManager.WakeLock lock=((PowerManager)context.getSystemService(Context.POWER_SERVICE))
            .newWakeLock(PowerManager.PARTIAL_WAKE_LOCK,"simmanager:alarm-handoff");
        lock.acquire(30000);
        // Timeout bridges delivery to onStartCommand; the service acquires its own lock.
        WatchService.start(context,test?"test":"alarm");
    }
}
