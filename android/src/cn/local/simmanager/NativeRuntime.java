package cn.local.simmanager;

import android.content.*;
import android.util.Base64;
import org.json.*;
import java.io.*;
import java.net.*;
import java.nio.file.*;
import java.util.*;
import java.util.zip.*;

/** Owns the Python runtime and data under this application's UID. */
final class NativeRuntime {
    static Process manager;
    static File root(Context c){return new File(c.getFilesDir(),"executor");}
    static boolean ready(Context c){return new File(root(c),"ready").isFile();}
    static String base(Context c){return "http://127.0.0.1:"+(ready(c)?18736:18735)+"/";}
    static String key(Context c){return c.getSharedPreferences("local",0).getString("key","");}
    static byte[] read(InputStream in)throws IOException{
        ByteArrayOutputStream out=new ByteArrayOutputStream();byte[] b=new byte[8192];int n;
        while((n=in.read(b))!=-1){out.write(b,0,n);if(out.size()>80*1024*1024)throw new IOException("数据过大");}return out.toByteArray();
    }
    static void write(File p,byte[] data)throws IOException{
        p.getParentFile().mkdirs();File tmp=new File(p.getPath()+".tmp");
        try(FileOutputStream out=new FileOutputStream(tmp)){out.write(data);out.getFD().sync();}
        if(!tmp.renameTo(p))throw new IOException("无法保存 "+p.getName());
    }
    static File safe(File root,String name)throws IOException{
        File p=new File(root,name);
        if(!p.getCanonicalPath().startsWith(root.getCanonicalPath()+"/"))throw new IOException("非法路径");return p;
    }
    static File linkPath(File root,String name)throws IOException{
        File p=new File(root,name);
        if(name.contains("..")||name.startsWith("/")||!p.getParentFile().getCanonicalPath().startsWith(root.getCanonicalPath()+"/"))throw new IOException("非法链接路径");
        return p;
    }
    static JSONObject request(Context c,String base,String action,String body)throws Exception{
        HttpURLConnection conn=(HttpURLConnection)new URL(base+action).openConnection();
        try{
            conn.setConnectTimeout(2500);conn.setReadTimeout(15000);
            conn.setRequestProperty("Authorization","Bearer "+key(c));
            if(body!=null){conn.setRequestMethod("POST");conn.setDoOutput(true);try(OutputStream out=conn.getOutputStream()){out.write(body.getBytes("UTF-8"));}}
            int code=conn.getResponseCode();InputStream stream=code<400?conn.getInputStream():conn.getErrorStream();
            JSONObject result=new JSONObject(new String(read(stream),"UTF-8"));
            if(code!=200)throw new IOException(result.optString("error","HTTP "+code));return result;
        }finally{conn.disconnect();}
    }
    static void install(Context c)throws Exception{
        File root=root(c);root.mkdirs();
        try(ZipInputStream zip=new ZipInputStream(c.getAssets().open("runtime.zip"))){
            ZipEntry entry;while((entry=zip.getNextEntry())!=null){if(!entry.isDirectory())write(safe(root,entry.getName()),read(zip));}
        }
        JSONObject links=new JSONObject(new String(Files.readAllBytes(new File(root,"native-links.json").toPath()),"UTF-8"));
        Iterator<String> it=links.keys();while(it.hasNext()){
            String name=it.next();File p=linkPath(root,name);p.getParentFile().mkdirs();Files.deleteIfExists(p.toPath());
            Files.createSymbolicLink(p.toPath(),new File(c.getApplicationInfo().nativeLibraryDir,links.getString(name)).toPath());
        }
        JSONObject bundle;try(InputStream in=c.getAssets().open("backend.json")){bundle=new JSONObject(new String(read(in),"UTF-8"));}
        JSONObject files=bundle.getJSONObject("files");it=files.keys();while(it.hasNext()){
            String name=it.next();write(safe(root,name),Base64.decode(files.getString(name),Base64.DEFAULT));
        }
        write(new File(root,"state/manager.key"),key(c).getBytes("UTF-8"));
    }
    static synchronized void ensure(Context c)throws Exception{
        if(!ready(c))return;
        try{request(c,base(c),"status",null);return;}catch(IOException e){}
        File update=new File(root(c),"state/update-result.json");
        if(update.isFile()&&System.currentTimeMillis()-update.lastModified()<120000){
            JSONObject state=new JSONObject(new String(Files.readAllBytes(update.toPath()),"UTF-8"));
            if("updating".equals(state.optString("phase")))return;
        }
        if(manager!=null&&manager.isAlive())return;
        // Refresh native-library symlinks after an APK replacement changes its install path.
        JSONObject links=new JSONObject(new String(Files.readAllBytes(new File(root(c),"native-links.json").toPath()),"UTF-8"));
        Iterator<String> it=links.keys();while(it.hasNext()){
            String name=it.next();Path p=linkPath(root(c),name).toPath();Files.deleteIfExists(p);
            Files.createSymbolicLink(p,new File(c.getApplicationInfo().nativeLibraryDir,links.getString(name)).toPath());
        }
        File root=root(c);String libs=c.getApplicationInfo().nativeLibraryDir;
        ProcessBuilder pb=new ProcessBuilder(libs+"/libths_python.so","-u","-c","import os,runpy,sys;from pathlib import Path;Path('state/manager.pid').write_text(str(os.getpid()));runpy.run_path(sys.argv[1],run_name='__main__')","phone/manager.py").directory(root);
        Map<String,String> env=pb.environment();env.put("THS_NATIVE","1");env.put("HOME",root.getPath());
        env.put("PYTHONHOME",root+"/prefix");env.put("PYTHONPATH",root.getPath());
        env.put("LD_LIBRARY_PATH",libs+":"+root+"/prefix/lib");env.put("SSL_CERT_FILE",root+"/ca.pem");
        env.put("PYTHONTZPATH",root+"/zoneinfo");env.put("TZ","Asia/Shanghai");
        pb.redirectErrorStream(true).redirectOutput(ProcessBuilder.Redirect.appendTo(new File(root,"state/manager.log")));
        manager=pb.start();
        for(int i=0;i<30;i++){Thread.sleep(250);try{request(c,base(c),"status",null);return;}catch(IOException e){}}
        throw new IOException("App 内后台启动失败");
    }
    static synchronized void migrate(Context c)throws Exception{
        if(ready(c)){ensure(c);return;}
        String enabled=android.provider.Settings.Secure.getString(c.getContentResolver(),android.provider.Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES);
        if(enabled==null||!Arrays.asList(enabled.split(":")).contains(new ComponentName(c,AutomationService.class).flattenToString()))
            throw new IOException("请先开启模拟仓管家无障碍权限");
        if(!key(c).matches("[0-9a-f]{64}"))throw new IOException("缺少原设备配对凭据");
        install(c); // Complete packaging before pausing the old executor.
        String old="http://127.0.0.1:18735/";
        JSONObject status=request(c,old,"status",null);
        File intent=new File(root(c),"migration-intent.json");
        if(!intent.exists())write(intent,status.toString().getBytes("UTF-8"));
        else status=new JSONObject(new String(Files.readAllBytes(intent.toPath()),"UTF-8"));
        request(c,old,"pause","");
        JSONObject files=null;
        for(int i=0;i<45;i++){
            JSONObject current=request(c,old,"status",null);
            if(!current.optBoolean("active")||"已暂停".equals(current.optString("status"))){
                files=request(c,old,"handoff","").getJSONObject("files");break;
            }Thread.sleep(1000);
        }
        if(files==null)throw new IOException("旧策略仍在操作，迁移已停止，稍后重试");
        for(int i=0;i<40&&AutomationService.instance==null;i++)Thread.sleep(250);
        if(AutomationService.instance==null)throw new IOException("无障碍服务尚未连接，请重新开启权限后重试迁移");
        String[] names={"state/strategy.sqlite3","state/settings.json",".config/redis-racknerd/stock-api.token"};
        if(files.length()!=names.length)throw new IOException("迁移数据不完整");
        for(String name:names)write(safe(root(c),name),Base64.decode(files.getString(name),Base64.DEFAULT));
        // Start paused until the user verifies accessibility operation on this device.
        write(new File(root(c),"state/paused"),new byte[0]);
        write(new File(root(c),"ready"),BuildBackend.DIGEST.getBytes("UTF-8"));
        c.getSharedPreferences("local",0).edit().putBoolean("watch_enabled",false).commit();
        ensure(c);
    }
}
