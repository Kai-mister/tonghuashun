package cn.local.simmanager;

import android.accessibilityservice.*;
import android.content.*;
import android.graphics.*;
import android.os.*;
import android.view.accessibility.*;
import android.util.Xml;
import org.xmlpull.v1.XmlSerializer;
import org.json.*;
import java.io.*;
import java.net.*;
import java.util.*;
import java.util.concurrent.*;

/** Authenticated, loopback-only bridge restricted to THS. No trade decisions here. */
public class AutomationService extends AccessibilityService {
    static volatile AutomationService instance;
    static final String THS="com.hexin.plat.android";
    final ExecutorService io=Executors.newCachedThreadPool();
    final Handler main=new Handler(Looper.getMainLooper());
    ServerSocket server;
    @Override public void onServiceConnected(){
        instance=this;
        io.execute(()->{
            try{
                server=new ServerSocket();server.setReuseAddress(true);
                server.bind(new InetSocketAddress("127.0.0.1",19008));
                io.execute(()->{try{NativeRuntime.ensure(this);if(getSharedPreferences("local",0).getBoolean("watch_enabled",false))WatchService.start(this,"accessibility");}catch(Exception e){problem(e);}});
                while(!server.isClosed()){Socket socket=server.accept();io.execute(()->serve(socket));}
            }catch(Exception e){problem(e);}
        });
    }
    void problem(Exception e){getSharedPreferences("local",0).edit().putString("watch_status","无障碍后台："+e.getMessage()).apply();}
    @Override public void onAccessibilityEvent(AccessibilityEvent event){}
    @Override public void onInterrupt(){}
    @Override public void onDestroy(){instance=null;try{if(server!=null)server.close();}catch(IOException e){}io.shutdownNow();super.onDestroy();}
    void serve(Socket socket){
        try(Socket s=socket){
            s.setSoTimeout(15000);BufferedInputStream in=new BufferedInputStream(s.getInputStream());
            ByteArrayOutputStream head=new ByteArrayOutputStream();int last=0,b;
            while((b=in.read())!=-1){head.write(b);last=(last<<8)|b;if(last==0x0d0a0d0a)break;if(head.size()>8192)throw new IOException("header too large");}
            String[] lines=head.toString("UTF-8").split("\r\n");int size=0;String auth="";
            for(String line:lines){int i=line.indexOf(':');if(i<0)continue;String k=line.substring(0,i).trim(),v=line.substring(i+1).trim();if(k.equalsIgnoreCase("Content-Length"))size=Integer.parseInt(v);if(k.equalsIgnoreCase("Authorization"))auth=v;}
            String key=NativeRuntime.key(this);
            if(key.isEmpty()||!java.security.MessageDigest.isEqual(auth.getBytes("UTF-8"),("Bearer "+key).getBytes("UTF-8"))){respond(s,403,"{}");return;}
            if(!lines[0].startsWith("POST /jsonrpc/0 ")||size<1||size>65536){respond(s,400,"{}");return;}
            byte[] data=new byte[size];int offset=0,n;while(offset<size&&(n=in.read(data,offset,size-offset))!=-1)offset+=n;if(offset!=size)throw new EOFException();
            JSONObject request=new JSONObject(new String(data,"UTF-8")),reply=new JSONObject().put("jsonrpc","2.0").put("id",request.opt("id"));
            try{Object result=call(request.getString("method"),request.optJSONArray("params"));reply.put("result",result==null?JSONObject.NULL:result);}
            catch(Exception error){reply.put("error",new JSONObject().put("message",error.getMessage()==null?error.toString():error.getMessage()));}
            respond(s,200,reply.toString());
        }catch(Exception ignored){}
    }
    void respond(Socket s,int status,String text)throws IOException{
        byte[] b=text.getBytes("UTF-8");OutputStream out=s.getOutputStream();out.write(("HTTP/1.1 "+status+" Result\r\nContent-Type: application/json\r\nContent-Length: "+b.length+"\r\nConnection: close\r\n\r\n").getBytes("UTF-8"));out.write(b);out.flush();
    }
    AccessibilityNodeInfo root(){if(Build.VERSION.SDK_INT>=33)clearCache();return getRootInActiveWindow();}
    String current(){AccessibilityNodeInfo r=root();return r==null?"":String.valueOf(r.getPackageName());}
    void requireTHS()throws IOException{if(!THS.equals(current()))throw new IOException("同花顺不在前台，已停止点击");}
    interface Action {Object run()throws Exception;}
    Object ui(Action a)throws Exception{
        FutureTask<Object> f=new FutureTask<>(()->a.run());main.post(f);return f.get(8,TimeUnit.SECONDS);
    }
    Object call(String method,JSONArray args)throws Exception{
        if(args==null)args=new JSONArray();
        switch(method){
            case "runtimeStatus":
                File logFile=new File(NativeRuntime.root(this),"state/manager.log");
                String logText=logFile.exists()?new String(java.nio.file.Files.readAllBytes(logFile.toPath()),"UTF-8"):"";
                return new JSONObject().put("ready",NativeRuntime.ready(this)).put("uid",android.os.Process.myUid()).put("manager_log",logText.substring(Math.max(0,logText.length()-4000)));
            case "deviceInfo": return new JSONObject().put("screenOn",((PowerManager)getSystemService(POWER_SERVICE)).isInteractive()).put("currentPackageName",current());
            case "wakeUp":
                PowerManager.WakeLock lock=((PowerManager)getSystemService(POWER_SERVICE)).newWakeLock(PowerManager.SCREEN_BRIGHT_WAKE_LOCK|PowerManager.ACQUIRE_CAUSES_WAKEUP,"simmanager:screen");lock.acquire(3000);return true;
            case "appStart":
                if(!THS.equals(args.getString(0)))throw new IOException("仅允许启动同花顺");
                return ui(()->{Intent intent=getPackageManager().getLaunchIntentForPackage(THS);if(intent==null)throw new IOException("未安装同花顺");intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);startActivity(intent);return true;});
            case "dumpWindowHierarchy":
                AccessibilityNodeInfo r=root();StringWriter writer=new StringWriter();XmlSerializer xml=Xml.newSerializer();xml.setOutput(writer);xml.startTag(null,"hierarchy");
                if(r!=null&&THS.contentEquals(r.getPackageName()))dump(xml,r,0);xml.endTag(null,"hierarchy");xml.flush();return writer.toString();
            case "pressKey":
                requireTHS();if(!"back".equals(args.getString(0)))throw new IOException("仅支持返回");return ui(()->performGlobalAction(GLOBAL_ACTION_BACK));
            case "swipe": requireTHS();return gesture(args.getInt(0),args.getInt(1),args.getInt(2),args.getInt(3),350);
            case "click":
                requireTHS();
                if(args.optJSONObject(0)==null)throw new IOException("不支持无目标坐标点击");
                AccessibilityNodeInfo node=first(args.getJSONObject(0));if(node==null)return false;
                if(node.performAction(AccessibilityNodeInfo.ACTION_CLICK))return true;
                Rect b=new Rect();node.getBoundsInScreen(b);return gesture(b.centerX(),b.centerY(),b.centerX(),b.centerY(),80);
            case "setText":
                requireTHS();node=first(args.getJSONObject(0));if(node==null||!node.isEditable())return false;
                String expected=args.getString(1);Bundle text=new Bundle();text.putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE,expected);
                if(!node.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT,text))return false;
                for(int i=0;i<20;i++){node.refresh();if(expected.equals(node.getText()==null?"":node.getText().toString())||(expected.isEmpty()&&node.isShowingHintText()))return true;Thread.sleep(50);}return false;
            case "getText":node=first(args.getJSONObject(0));if(node==null)throw new IOException("未找到控件");node.refresh();return node.getText()==null?"":node.getText().toString();
            case "count":return find(args.getJSONObject(0)).size();
            case "exist":return first(args.getJSONObject(0))!=null;
            case "waitForExists":
                long until=System.currentTimeMillis()+Math.min(5000,args.getLong(1));
                do{if(first(args.getJSONObject(0))!=null)return true;Thread.sleep(100);}while(System.currentTimeMillis()<until);return false;
            default:throw new IOException("不支持的方法 "+method);
        }
    }
    boolean gesture(int x,int y,int x2,int y2,long duration)throws Exception{
        CountDownLatch done=new CountDownLatch(1);boolean[] success={false};Path path=new Path();path.moveTo(x,y);if(x!=x2||y!=y2)path.lineTo(x2,y2);
        boolean submitted=(Boolean)ui(()->dispatchGesture(new GestureDescription.Builder().addStroke(new GestureDescription.StrokeDescription(path,0,duration)).build(),new GestureResultCallback(){
            public void onCompleted(GestureDescription g){success[0]=true;done.countDown();}
            public void onCancelled(GestureDescription g){done.countDown();}
        },main));
        return submitted&&done.await(3,TimeUnit.SECONDS)&&success[0];
    }
    AccessibilityNodeInfo first(JSONObject query)throws Exception{
        List<AccessibilityNodeInfo> nodes=find(query);
        if(!query.has("instance")&&query.has("resourceId")){
            // THS reuses an edit's ID on its containing layout. Target the actual edit.
            for(AccessibilityNodeInfo n:nodes)if(n.isEditable())return n;
            for(AccessibilityNodeInfo n:nodes)if(n.getText()!=null&&n.getText().length()>0)return n;
        }
        int i=query.optInt("instance",0);return i>=0&&i<nodes.size()?nodes.get(i):null;
    }
    List<AccessibilityNodeInfo> find(JSONObject query)throws Exception{
        List<AccessibilityNodeInfo> out=new ArrayList<>();AccessibilityNodeInfo r=root();
        if(r!=null&&THS.contentEquals(r.getPackageName()))collect(r,query,out,0);return out;
    }
    void collect(AccessibilityNodeInfo n,JSONObject q,List<AccessibilityNodeInfo> out,int depth)throws Exception{
        if(depth>60)return;boolean ok=n.isVisibleToUser();
        String[] keys={"text","resourceId","packageName","className","description"};
        CharSequence[] vals={n.getText(),n.getViewIdResourceName(),n.getPackageName(),n.getClassName(),n.getContentDescription()};
        for(int i=0;i<keys.length;i++)if(q.has(keys[i])&&!q.getString(keys[i]).equals(vals[i]==null?"":vals[i].toString()))ok=false;
        if(q.has("textMatches")&&(n.getText()==null||!n.getText().toString().matches(q.getString("textMatches"))))ok=false;
        if(ok)out.add(n);
        for(int i=0;i<n.getChildCount();i++){AccessibilityNodeInfo c=n.getChild(i);if(c!=null)collect(c,q,out,depth+1);}
    }
    void dump(XmlSerializer xml,AccessibilityNodeInfo n,int depth)throws IOException{
        if(depth>60||!n.isVisibleToUser())return;xml.startTag(null,"node");Rect b=new Rect();n.getBoundsInScreen(b);
        attr(xml,"text",n.getText());attr(xml,"resource-id",n.getViewIdResourceName());attr(xml,"package",n.getPackageName());attr(xml,"class",n.getClassName());attr(xml,"content-desc",n.getContentDescription());
        attr(xml,"bounds","["+b.left+","+b.top+"]["+b.right+","+b.bottom+"]");attr(xml,"scrollable",String.valueOf(n.isScrollable()));attr(xml,"clickable",String.valueOf(n.isClickable()));
        for(int i=0;i<n.getChildCount();i++){AccessibilityNodeInfo c=n.getChild(i);if(c!=null)dump(xml,c,depth+1);}xml.endTag(null,"node");
    }
    void attr(XmlSerializer xml,String key,CharSequence v)throws IOException{xml.attribute(null,key,v==null?"":v.toString());}
}
