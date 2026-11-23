package cn.local.simmanager;
import android.content.*;
public class Pair extends BroadcastReceiver {
    public void onReceive(Context context, Intent intent) {
        String key = intent.getStringExtra("key");
        if (key != null && key.matches("[0-9a-f]{64}"))
            context.getSharedPreferences("local",0).edit().putString("key",key).commit();
    }
}
