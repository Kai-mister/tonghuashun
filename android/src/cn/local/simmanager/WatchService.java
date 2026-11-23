package cn.local.simmanager;

import android.app.*;
import android.content.*;
import android.os.*;
import org.json.*;
import java.io.*;
import java.net.*;
import java.util.concurrent.*;

/** Foreground guardian. Never submits orders or requests manual catch-up. */
public class WatchService extends Service {
    static final String CHANNEL="strategy_watch";
    static final int NOTIFICATION=20;
    static boolean alive;
    final Handler handler=new Handler(Looper.getMainLooper());
    final ExecutorService io=Executors.newSingleThreadExecutor();
    PowerManager.WakeLock cpu;
    boolean busy,destroyed;
    long testUntil;
    final Runnable poll=()->check("poll");

    static void start(Context context,String reason){
        try{
            context.startForegroundService(new Intent(context,WatchService.class).putExtra("reason",reason));
        }catch(RuntimeException error){
            context.getSharedPreferences("local",0).edit().putString("watch_status","值守启动失败，请打开 App："+error.getMessage()).apply();
        }
    }
    static PendingIntent alarm(Context context,boolean test){
        return PendingIntent.getBroadcast(context,test?21:20,new Intent(context,WatchReceiver.class)
            .setAction(test?"cn.local.simmanager.WAKE_TEST":"cn.local.simmanager.WAKE"),
            PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE);
    }
    static boolean exact(Context context){
        return Build.VERSION.SDK_INT<31||((AlarmManager)context.getSystemService(ALARM_SERVICE)).canScheduleExactAlarms();
    }
    static void setWakeAlarm(Context context,long when,boolean test){
        PendingIntent show=PendingIntent.getActivity(context,0,new Intent(context,Main.class),
            PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE);
        ((AlarmManager)context.getSystemService(ALARM_SERVICE)).setAlarmClock(
            new AlarmManager.AlarmClockInfo(when,show),alarm(context,test));
    }
    static void schedule(Context context){
        AlarmManager manager=(AlarmManager)context.getSystemService(ALARM_SERVICE);
        boolean enabled=context.getSharedPreferences("local",0).getBoolean("watch_enabled",false);
        if(!enabled){manager.cancel(alarm(context,false));return;}
        if(!exact(context))return;
        long next=WatchSchedule.next(System.currentTimeMillis());
        try{
            setWakeAlarm(context,next,false);
            context.getSharedPreferences("local",0).edit().putLong("watch_next",next).apply();
        }catch(SecurityException error){
            context.getSharedPreferences("local",0).edit().putString("watch_status","缺少精确定时权限").apply();
        }
    }
    static void sync(Context context,JSONObject status){
        boolean enabled=!status.optBoolean("paused",true);
        android.content.SharedPreferences prefs=context.getSharedPreferences("local",0);
        boolean changed=prefs.getBoolean("watch_enabled",false)!=enabled;
        prefs.edit().putBoolean("watch_enabled",enabled).apply();
        if(enabled&&(changed||!alive))start(context,"sync");
        else if(changed){
            schedule(context);
            context.stopService(new Intent(context,WatchService.class));
            prefs.edit().putString("watch_status","策略已暂停，自动值守关闭").apply();
        }
    }
    static void test(Context context){
        if(!exact(context))throw new IllegalStateException("请先允许精确定时");
        setWakeAlarm(context,System.currentTimeMillis()+30000,true);
        context.getSharedPreferences("local",0).edit().putString("wake_test","等待 30 秒后的唤醒自检（不补单）").apply();
    }
    @Override public void onCreate(){
        super.onCreate();alive=true;
        NotificationManager manager=(NotificationManager)getSystemService(NOTIFICATION_SERVICE);
        manager.createNotificationChannel(new NotificationChannel(CHANNEL,"模拟策略自动值守",NotificationManager.IMPORTANCE_LOW));
        cpu=((PowerManager)getSystemService(POWER_SERVICE)).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK,"simmanager:trading-watch");
        cpu.setReferenceCounted(false);
        startForeground(NOTIFICATION,notification("正在检查后台"));
    }
    Notification notification(String text){
        PendingIntent open=PendingIntent.getActivity(this,0,new Intent(this,Main.class),PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE);
        return new Notification.Builder(this,CHANNEL).setSmallIcon(android.R.drawable.ic_lock_idle_alarm)
            .setContentTitle("模拟仓自动值守").setContentText(text).setContentIntent(open)
            .setOngoing(true).setOnlyAlertOnce(true).setShowWhen(false).build();
    }
    void report(String message){
        android.util.Log.i("SimWatch",message);
        getSharedPreferences("local",0).edit().putString("watch_status",message).putLong("watch_checked",System.currentTimeMillis()).apply();
        ((NotificationManager)getSystemService(NOTIFICATION_SERVICE)).notify(NOTIFICATION,notification(message));
    }
    @Override public int onStartCommand(Intent intent,int flags,int id){
        String reason=intent==null?"restart":intent.getStringExtra("reason");
        if("test".equals(reason))testUntil=System.currentTimeMillis()+60000;
        schedule(this);
        if(!"sync".equals(reason)||!busy)check(reason==null?"restart":reason);
        return START_STICKY;
    }
    void check(String reason){
        if(busy||destroyed)return;
        boolean testing=System.currentTimeMillis()<testUntil;
        boolean enabled=getSharedPreferences("local",0).getBoolean("watch_enabled",false);
        if(!enabled&&!testing){stopSelf();return;}
        handler.removeCallbacks(poll);
        // During trading keep CPU awake even when the activity is dismissed or screen is off.
        // Outside trading only an alarm/self-test needs a short bounded lock.
        if(enabled&&WatchSchedule.active(System.currentTimeMillis()))cpu.acquire(120000);
        else if(testing||!"poll".equals(reason))cpu.acquire(45000);
        else if(cpu.isHeld())cpu.release();
        busy=true;
        android.util.Log.i("SimWatch","检查 "+reason+"，交易时段="+WatchSchedule.active(System.currentTimeMillis()));
        io.execute(()->{
            JSONObject status=null;String error=null;
            try{
                NativeRuntime.ensure(this);
                status=request("status",null);
                if(status.optInt("api_version")!=BuildBackend.API_VERSION||!BuildBackend.DIGEST.equals(status.optString("backend_digest")))
                    throw new IOException("后台版本不匹配，请打开 App 更新");
                JSONObject update=status.optJSONObject("update");
                if(update!=null&&"updating".equals(update.optString("phase")))throw new IOException("后台正在升级");
                // A test is read-only; it must not revive a worker or invoke trading logic.
                if(!testing&&!status.optBoolean("paused",true))
                    status=request("maintain",new JSONObject().put("reason",reason).toString());
            }catch(Exception failure){error=failure.getMessage();}
            JSONObject result=status;String problem=error;
            handler.post(()->{
                busy=false;if(destroyed)return;
                String message=problem==null?"后台"+result.optString("status"):
                    "后台不可用，请打开 App 检查；请检查无障碍权限："+problem;
                if(problem==null&&result.optBoolean("paused",true)){
                    getSharedPreferences("local",0).edit().putBoolean("watch_enabled",false).apply();schedule(this);
                }
                if(testing){
                    getSharedPreferences("local",0).edit().putString("wake_test",
                        "唤醒自检 "+java.time.ZonedDateTime.now(WatchSchedule.ZONE).toLocalTime().withNano(0)+
                        (problem==null?"：已唤醒 CPU，后台连接成功（未补单）":"：已唤醒 CPU，后台检查失败："+problem)).apply();
                    testUntil=0;
                }
                if(!exact(this))message+=" · 缺少精确定时权限";
                report(message);
                if(!getSharedPreferences("local",0).getBoolean("watch_enabled",false))stopSelf();
                else handler.postDelayed(poll,30000);
            });
        });
    }
    JSONObject request(String action,String body)throws Exception{
        HttpURLConnection c=(HttpURLConnection)new URL(NativeRuntime.base(this)+action).openConnection();
        try{
            c.setConnectTimeout(2500);c.setReadTimeout(15000);
            c.setRequestProperty("Authorization","Bearer "+getSharedPreferences("local",0).getString("key",""));
            if(body!=null){
                c.setRequestMethod("POST");c.setDoOutput(true);c.setRequestProperty("Content-Type","application/json");
                try(OutputStream out=c.getOutputStream()){out.write(body.getBytes("UTF-8"));}
            }
            int http=c.getResponseCode();
            if(http!=200)throw new IOException("HTTP "+http);
            try(BufferedReader reader=new BufferedReader(new InputStreamReader(c.getInputStream(),"UTF-8"))){
                JSONObject data=new JSONObject(reader.readLine());
                if(data.has("error")||!data.has("status"))throw new IOException(data.optString("error","状态响应无效"));
                return data;
            }
        }finally{c.disconnect();}
    }
    @Override public void onTaskRemoved(Intent root){schedule(this);super.onTaskRemoved(root);}
    @Override public void onDestroy(){alive=false;destroyed=true;handler.removeCallbacks(poll);io.shutdownNow();if(cpu.isHeld())cpu.release();super.onDestroy();}
    @Override public IBinder onBind(Intent intent){return null;}
}
