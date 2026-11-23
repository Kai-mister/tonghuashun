package cn.local.simmanager;

import android.content.*;
import android.content.pm.PackageManager;
import android.provider.Settings;
import java.util.*;

/** Opt-in device-owner provisioning. Only restores this service after a normal reboot. */
final class BootRestore {
    static String component(Context c){return new ComponentName(c,AutomationService.class).flattenToString();}
    static boolean allowed(Context c){return c.checkSelfPermission("android.permission.WRITE_SECURE_SETTINGS")==PackageManager.PERMISSION_GRANTED;}
    static boolean serviceEnabled(Context c){
        String value=Settings.Secure.getString(c.getContentResolver(),Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES);
        return value!=null&&Arrays.asList(value.split(":")).contains(component(c));
    }
    static void enableService(Context c){
        if(!allowed(c))throw new SecurityException("需要一次 USB 授予系统设置权限");
        String value=Settings.Secure.getString(c.getContentResolver(),Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES);
        LinkedHashSet<String> services=new LinkedHashSet<>();
        if(value!=null)for(String s:value.split(":"))if(!s.isEmpty())services.add(s);
        services.add(component(c));
        if(!Settings.Secure.putString(c.getContentResolver(),Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES,String.join(":",services))
                ||!Settings.Secure.putInt(c.getContentResolver(),Settings.Secure.ACCESSIBILITY_ENABLED,1))
            throw new SecurityException("系统拒绝恢复本应用无障碍");
    }
    static void optIn(Context c,boolean enabled){
        if(enabled){if(!NativeRuntime.ready(c))throw new IllegalStateException("请先迁移到 App 独立运行");enableService(c);}
        c.getSharedPreferences("local",0).edit().putBoolean("boot_restore",enabled).putInt("restore_shutdown_boot",-1).commit();
    }
    static void shutdown(Context c){
        android.content.SharedPreferences p=c.getSharedPreferences("local",0);
        int boot=Settings.Global.getInt(c.getContentResolver(),Settings.Global.BOOT_COUNT,-1);
        // Read the actual switch at shutdown. A manually disabled service stays disabled.
        boolean restore=p.getBoolean("boot_restore",false)&&serviceEnabled(c)&&boot>=0;
        p.edit().putInt("restore_shutdown_boot",restore?boot:-1).commit();
    }
    static void boot(Context c){
        android.content.SharedPreferences p=c.getSharedPreferences("local",0);
        int previous=p.getInt("restore_shutdown_boot",-1);
        int now=Settings.Global.getInt(c.getContentResolver(),Settings.Global.BOOT_COUNT,-1);
        p.edit().putInt("restore_shutdown_boot",-1).commit(); // One-use, never a polling re-enable loop.
        if(p.getBoolean("boot_restore",false)&&previous>=0&&now==previous+1){
            try{enableService(c);}
            catch(RuntimeException e){p.edit().putString("watch_status","重启授权恢复失败："+e.getMessage()).apply();}
        }
    }
}
