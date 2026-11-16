package cn.local.simmanager;

import android.app.Activity;
import android.os.*;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.view.View;
import android.widget.*;
import org.json.*;
import java.net.*;
import java.io.*;
import java.util.concurrent.*;

public class Main extends Activity {
    final int ink=0xff173936, green=0xff155d51;
    LinearLayout page, checks, orders, maintenance;
    final ScrollView[] screens = new ScrollView[4];
    final TextView[] tabs = new TextView[4];
    int selectedTab;
    boolean editing;
    LinearLayout screen(LinearLayout host, int index) {
        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        screens[index] = scroll;
        host.addView(scroll,new LinearLayout.LayoutParams(-1,0,1));
        LinearLayout content = new LinearLayout(this);
        content.setOrientation(1);
        content.setPadding(dp(20),dp(12),dp(20),dp(16));
        scroll.addView(content);
        return content;
    }
    void selectTab(int index) {
        selectedTab = index;
        android.view.inputmethod.InputMethodManager keyboard =
            (android.view.inputmethod.InputMethodManager)getSystemService(INPUT_METHOD_SERVICE);
        keyboard.hideSoftInputFromWindow(page.getWindowToken(),0);
        for(int i=0;i<screens.length;i++){
            screens[i].setVisibility(i==index?View.VISIBLE:View.GONE);
            tabs[i].setTextColor(i==index?green:0xff6c7b75);
            tabs[i].setTypeface(Typeface.DEFAULT,i==index?Typeface.BOLD:Typeface.NORMAL);
            tabs[i].setBackgroundColor(i==index?0xffe3eee4:Color.WHITE);
            tabs[i].setSelected(i==index);
        }
    }
    String setting(JSONObject settings,String key,String fallback) {
        String value=settings.optString(key,"").trim();
        return value.isEmpty() || value.equals("null") ? fallback : value;
    }
    TextView state, account, notice;
    Button control, save, check, upgrade;
    TextView backendNotice, watchNotice;
    boolean compatible, upgrading;
    EditText target, minimum, maximum, buyTime;
    Spinner strategy;
    TextView checkResult;
    boolean settingsLoaded;
    String settingsBody;
    EditText input(LinearLayout box,String title,int type){
        label(box,title,14,ink,false);
        EditText edit=new EditText(this);edit.setSingleLine(true);edit.setInputType(type);
        box.addView(edit);
        edit.addTextChangedListener(new android.text.TextWatcher(){
            public void beforeTextChanged(CharSequence s,int start,int count,int after){}
            public void onTextChanged(CharSequence s,int start,int before,int count){
                if(edit.hasFocus())editing=true;
            }
            public void afterTextChanged(android.text.Editable s){}
        });
        return edit;
    }
    final Handler timer = new Handler(Looper.getMainLooper());
    final ExecutorService io = Executors.newSingleThreadExecutor();
    boolean visible, busy, resume;
    final Runnable poll = () -> load("status");

    int dp(int n){return Math.round(getResources().getDisplayMetrics().density*n);}
    TextView label(LinearLayout parent,String value,int size,int color,boolean bold){
        TextView v=new TextView(this); v.setText(value); v.setTextSize(size); v.setTextColor(color);
        if(bold)v.setTypeface(Typeface.DEFAULT,Typeface.BOLD);
        v.setPadding(0,dp(5),0,dp(5)); parent.addView(v); return v;
    }
    LinearLayout card(int color){
        LinearLayout box=new LinearLayout(this); box.setOrientation(1);
        GradientDrawable bg=new GradientDrawable(); bg.setColor(color); bg.setCornerRadius(dp(18)); box.setBackground(bg);
        box.setPadding(dp(18),dp(14),dp(18),dp(14));
        LinearLayout.LayoutParams lp=new LinearLayout.LayoutParams(-1,-2); lp.bottomMargin=dp(16);
        page.addView(box,lp); return box;
    }
    public void onCreate(Bundle saved){
        super.onCreate(saved); getWindow().setStatusBarColor(0xfff2f5ef);
        getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR);
        LinearLayout root=new LinearLayout(this);root.setOrientation(1);
        root.setBackgroundColor(0xfff2f5ef);root.setFocusableInTouchMode(true);setContentView(root);
        page=screen(root,0);
        label(page,"模拟仓管家",29,ink,true);
        LinearLayout header=card(green);account=label(header,"模拟账户",15,0xffd5eee3,false);
        state=label(header,"正在连接",30,Color.WHITE,true);
        notice=label(header,"",14,0xffd5eee3,false);
        control=new Button(this);header.addView(control);control.setText("连接中");control.setEnabled(false);
        control.setOnClickListener(v->load(resume?"resume":"pause"));
        maintenance=card(Color.WHITE);
        maintenance.setVisibility(View.GONE);
        backendNotice=label(maintenance,"正在检查后台版本",14,ink,false);
        upgrade=new Button(this);upgrade.setText("更新手机后台");maintenance.addView(upgrade);
        upgrade.setVisibility(View.GONE);
        upgrade.setOnClickListener(v->new android.app.AlertDialog.Builder(this)
            .setMessage("更新为此 App 内置的后台版本。等待当前操作结束后重启后台，保留设置、账本和启停状态，不会补下错过的买单。")
            .setPositiveButton("更新后台",(dialog,which)->load("upgrade"))
            .setNegativeButton("取消",null).show());
        LinearLayout watch=card(Color.WHITE);
        watch.setVisibility(View.GONE); // Hide diagnostics only; WatchService remains independent.
        label(watch,"后台保活与定时唤醒",19,ink,true);
        watchNotice=label(watch,"",14,ink,false);
        Button exact=new Button(this);exact.setText("允许精确定时");watch.addView(exact);
        exact.setOnClickListener(v->{
            if(Build.VERSION.SDK_INT>=31)openSetting(android.provider.Settings.ACTION_REQUEST_SCHEDULE_EXACT_ALARM,true);
            else Toast.makeText(this,"此系统无需单独授权",Toast.LENGTH_SHORT).show();
        });
        Button battery=new Button(this);battery.setText("允许后台运行 / 不受电池优化限制");watch.addView(battery);
        battery.setOnClickListener(v->openSetting(android.provider.Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS,true));
        Button vendor=new Button(this);vendor.setText("应用详情 / 厂商后台管理");watch.addView(vendor);
        vendor.setOnClickListener(v->openSetting(android.provider.Settings.ACTION_APPLICATION_DETAILS_SETTINGS,true));
        Button notifications=new Button(this);notifications.setText("通知与值守状态");watch.addView(notifications);
        notifications.setOnClickListener(v->{
            android.content.Intent intent=new android.content.Intent(android.provider.Settings.ACTION_APP_NOTIFICATION_SETTINGS);
            intent.putExtra(android.provider.Settings.EXTRA_APP_PACKAGE,getPackageName());startActivity(intent);
        });
        Button test=new Button(this);test.setText("30 秒后唤醒自检（不触发补单）");watch.addView(test);
        test.setOnClickListener(v->{
            try{WatchService.test(this);refreshWatch();Toast.makeText(this,"已设置，已退到后台；可熄屏等待自检",Toast.LENGTH_LONG).show();moveTaskToBack(true);}
            catch(RuntimeException error){Toast.makeText(this,error.getMessage(),Toast.LENGTH_LONG).show();}
        });
        label(watch,"系统会显示下一次唤醒闹钟（不响铃）。关闭界面或划掉最近任务后，通知栏值守继续。不要强行停止 App。设备厂商的后台限制也需允许；密码锁屏需手动解锁，手机重启后执行器可能需要 USB 恢复。",13,green,false);
        LinearLayout actions=card(Color.WHITE);
        check=new Button(this);check.setEnabled(false);check.setText("检查并补执行");actions.addView(check);
        check.setOnClickListener(v->new android.app.AlertDialog.Builder(this)
            .setMessage("核对委托和持仓，补执行遗漏的买单及已触发的卖单。暂停状态下也会执行本次检查。")
            .setPositiveButton("检查并补执行",(dialog,which)->load("check"))
            .setNegativeButton("取消",null).show());
        checkResult=label(actions,"",14,green,false);
        LinearLayout homePage=page;
        page=screen(root,1);
        label(page,"策略设置",26,ink,true);
        LinearLayout settings=card(Color.WHITE);
        target=input(settings,"建议金额（元）",8194);
        minimum=input(settings,"最低金额（元）",8194);
        maximum=input(settings,"最高金额（元）",8194);
        buyTime=input(settings,"每天挂单时间（北京时间 HH:MM）",1);
        target.setText("10000");minimum.setText("5000");maximum.setText("20000");buyTime.setText("09:20");
        strategy=new Spinner(this);
        strategy.setAdapter(new ArrayAdapter<String>(this,android.R.layout.simple_spinner_dropdown_item,
            new String[]{"激进 · 浅回调优先","保守 · 深回调"}));
        settings.addView(strategy);
        save=new Button(this);save.setEnabled(false);save.setText("保存设置");settings.addView(save);
        save.setOnClickListener(v->{
            try{
                JSONObject body=new JSONObject();
                body.put("target_amount",target.getText().toString().trim());
                body.put("min_amount",minimum.getText().toString().trim());
                body.put("max_amount",maximum.getText().toString().trim());
                body.put("buy_time",buyTime.getText().toString().trim());
                body.put("strategy",strategy.getSelectedItemPosition()==0?"aggressive":"conservative");
                settingsBody=body.toString();load("settings");
            }catch(JSONException error){Toast.makeText(this,"设置格式错误",Toast.LENGTH_LONG).show();}
        });
        label(settings,"设置应用于尚未挂出的买单；已有持仓继续使用买入时的止盈止损。",13,green,false);
        page=screen(root,2);
        label(page,"盘前持仓核对",26,ink,true);checks=card(Color.WHITE);
        rows(checks,null,true);
        page=screen(root,3);
        label(page,"最近策略委托",26,ink,true);orders=card(Color.WHITE);
        rows(orders,null,false);
        page=homePage;
        LinearLayout navigation=new LinearLayout(this);
        navigation.setBackgroundColor(Color.WHITE);
        root.addView(navigation,new LinearLayout.LayoutParams(-1,dp(64)));
        String[] names={"主界面","策略设置","盘前持仓核对","最近策略委托"};
        for(int i=0;i<screens.length;i++){
            final int index=i;
            TextView tab=new TextView(this);tab.setText(names[i]);tab.setTextSize(12);
            tab.setGravity(android.view.Gravity.CENTER);tab.setContentDescription(names[i]);
            tabs[i]=tab;navigation.addView(tab,new LinearLayout.LayoutParams(0,-1,1));
            tab.setOnClickListener(v->selectTab(index));
        }
        if(saved!=null){
            target.setText(saved.getString("target","10000"));
            minimum.setText(saved.getString("minimum","5000"));
            maximum.setText(saved.getString("maximum","20000"));
            buyTime.setText(saved.getString("time","09:20"));
            strategy.setSelection(saved.getInt("strategy",0));
            editing=saved.getBoolean("editing",false);
        }
        selectTab(saved==null?0:saved.getInt("tab",0));
    }
    protected void onSaveInstanceState(Bundle out){
        out.putInt("tab",selectedTab);out.putBoolean("editing",editing);
        out.putString("target",target.getText().toString());
        out.putString("minimum",minimum.getText().toString());
        out.putString("maximum",maximum.getText().toString());
        out.putString("time",buyTime.getText().toString());
        out.putInt("strategy",strategy.getSelectedItemPosition());
        super.onSaveInstanceState(out);
    }
    void openSetting(String action,boolean packageUri){
        try{
            android.content.Intent intent=new android.content.Intent(action);
            if(packageUri)intent.setData(android.net.Uri.parse("package:"+getPackageName()));
            startActivity(intent);
        }catch(RuntimeException error){Toast.makeText(this,"请在系统设置中允许此 App 的后台运行与精确定时",Toast.LENGTH_LONG).show();}
    }
    void refreshWatch(){
        android.content.SharedPreferences prefs=getSharedPreferences("local",0);
        boolean battery=((android.os.PowerManager)getSystemService(POWER_SERVICE)).isIgnoringBatteryOptimizations(getPackageName());
        boolean locked=((android.app.KeyguardManager)getSystemService(KEYGUARD_SERVICE)).isKeyguardSecure();
        boolean notification=((android.app.NotificationManager)getSystemService(NOTIFICATION_SERVICE)).areNotificationsEnabled();
        long next=prefs.getLong("watch_next",0);
        String text="精确定时："+(WatchService.exact(this)?"已允许":"未允许")+" · 后台电池限制："+(battery?"已解除":"未解除")+
            "\n通知："+(notification?"已允许":"未允许")+" · "+(locked?"有安全锁屏，无法保证自动操作":"无安全锁屏")+
            "\n"+prefs.getString("watch_status","等待后台就绪后开启值守");
        if(prefs.getBoolean("watch_enabled",false)&&next>0)text+="\n下次系统唤醒："+WatchSchedule.display(next)+"（北京时间）";
        long checked=prefs.getLong("watch_checked",0);
        if(prefs.getBoolean("watch_enabled",false)&&checked>0){
            text+="\n最近后台检查："+java.time.Instant.ofEpochMilli(checked).atZone(WatchSchedule.ZONE).toLocalTime().withNano(0);
            if(WatchSchedule.active(System.currentTimeMillis())&&System.currentTimeMillis()-checked>90000)
                text+="\n值守检查超时，请检查厂商后台管理权限";
        }
        String test=prefs.getString("wake_test","");if(!test.isEmpty())text+="\n"+test;
        watchNotice.setText(text);
    }
    protected void onResume(){super.onResume();visible=true;refreshWatch();load("status");}
    protected void onPause(){visible=false;timer.removeCallbacks(poll);super.onPause();}
    protected void onDestroy(){io.shutdownNow();super.onDestroy();}
    void load(String action){
        if(busy||!visible)return;
        if(!action.equals("status")&&!action.equals("upgrade")&&!compatible){
            Toast.makeText(this,"请先完成后台版本检查或升级",Toast.LENGTH_LONG).show();return;
        }
        timer.removeCallbacks(poll);busy=true;
        control.setEnabled(false);save.setEnabled(false);check.setEnabled(false);upgrade.setEnabled(false);
        final String payload=settingsBody;
        io.execute(()->{
            JSONObject data=null;
            try{
                HttpURLConnection c=(HttpURLConnection)new URL("http://127.0.0.1:18735/"+action).openConnection();
                try{
                    c.setConnectTimeout(2500);c.setReadTimeout(15000);
                    c.setRequestProperty("Authorization","Bearer "+getSharedPreferences("local",0).getString("key",""));
                    if(!action.equals("status"))c.setRequestMethod("POST");
                    if(action.equals("upgrade")){
                        c.setDoOutput(true);c.setRequestProperty("Content-Type","application/json");
                        try(InputStream in=getAssets().open("backend.json");OutputStream out=c.getOutputStream()){
                            byte[] buffer=new byte[8192];int length;
                            while((length=in.read(buffer))!=-1)out.write(buffer,0,length);
                        }
                    }
                    if(action.equals("settings")){
                        c.setDoOutput(true);c.setRequestProperty("Content-Type","application/json");
                        try(OutputStream out=c.getOutputStream()){out.write(payload.getBytes("UTF-8"));}
                    }
                    int http=c.getResponseCode();
                    InputStream stream=http<400?c.getInputStream():c.getErrorStream();
                    try(BufferedReader r=new BufferedReader(new InputStreamReader(stream,"UTF-8"))){
                        StringBuilder body=new StringBuilder();String line;
                        while((line=r.readLine())!=null)body.append(line);
                        data=new JSONObject(body.toString());
                        if(http<200||http>=300)throw new IOException(data.optString("error","请求失败（HTTP "+http+"），后台可能需要升级"));
                        if(action.equals("upgrade")){
                            if(!data.optBoolean("accepted"))throw new IOException("后台未确认升级请求");
                        }else if(!data.has("status"))throw new IOException("后台响应无效，操作未确认成功");
                        if(action.equals("settings")&&!data.has("settings"))throw new IOException("后台未返回保存结果，设置未确认成功");
                    }
                }finally{c.disconnect();}
            }catch(Exception error){
                data=new JSONObject();
                try{data.put("error",error.getMessage()==null?"无法连接本机后台":error.getMessage());}catch(JSONException ignored){}
            }
            final JSONObject result=data;
            runOnUiThread(()->{
                busy=false;if(!visible||isDestroyed())return;
                if(result==null||result.has("error")){
                    maintenance.setVisibility(View.VISIBLE);
                    compatible=false;
                    state.setText(upgrading?"后台更新中":"服务不可用");
                    String message=result==null?"无法连接本机后台":result.optString("error");
                    notice.setText(message);backendNotice.setText(upgrading?"正在重连后台，请稍候；长时间未恢复请通过 USB 修复。":"连接或操作失败："+message);
                    control.setEnabled(false);save.setEnabled(false);check.setEnabled(false);
                    upgrade.setEnabled(false);
                    if(!action.equals("status"))Toast.makeText(this,message,Toast.LENGTH_LONG).show();
                }else if(action.equals("upgrade")){
                    maintenance.setVisibility(View.VISIBLE);
                    upgrading=true;compatible=false;backendNotice.setText("升级请求已接收，正在等待后台重启和校验");
                }else{
                    JSONObject update=result.optJSONObject("update");
                    String phase=update==null?"":update.optString("phase");
                    upgrading=phase.equals("updating");
                    compatible=result.optInt("api_version")==BuildBackend.API_VERSION &&
                        result.optString("backend_digest").equals(BuildBackend.DIGEST) && !upgrading;
                    boolean canUpgrade=result.optInt("update_protocol")==1;
                    String detail=upgrading?"后台正在更新，请稍候":compatible?"":
                        canUpgrade?"后台版本与 App 不一致，请更新手机后台":"旧后台不支持 App 内升级，请先通过 USB 升级一次";
                    if(update!=null&&(phase.equals("failed")||phase.equals("updating"))&&!update.optString("message").isEmpty())detail+="\n"+update.optString("message");
                    backendNotice.setText(detail.trim());
                    maintenance.setVisibility(compatible&&!phase.equals("failed")?View.GONE:View.VISIBLE);
                    upgrade.setVisibility(!compatible&&canUpgrade?View.VISIBLE:View.GONE);
                    upgrade.setEnabled(!upgrading&&canUpgrade);
                    save.setEnabled(compatible);check.setEnabled(compatible);
                    if(compatible)WatchService.sync(this,result);
                    JSONObject settings=result.optJSONObject("settings");
                    if(settings!=null && (!settingsLoaded && !editing || action.equals("settings"))){
                        target.setText(setting(settings,"target_amount","10000"));
                        minimum.setText(setting(settings,"min_amount","5000"));
                        maximum.setText(setting(settings,"max_amount","20000"));
                        buyTime.setText(setting(settings,"buy_time","09:20"));
                        strategy.setSelection(settings.optString("strategy").equals("conservative")?1:0);
                        settingsLoaded=true;editing=false;
                    }
                    if(action.equals("settings")&&compatible)Toast.makeText(this,"设置已保存",Toast.LENGTH_SHORT).show();
                    checkResult.setText(result.optString("check_result"));
                    state.setText(compatible?result.optString("status"):upgrading?"后台更新中":"需要更新后台");account.setText("模拟账户  "+result.optString("account"));
                    resume=result.optBoolean("paused")||!result.optBoolean("active");
                    control.setText(resume?"启动 / 恢复策略":"暂停策略");control.setEnabled(compatible);
                    notice.setText(compatible?"暂停在本轮结束后生效，已有委托继续有效。":"后台未匹配，策略操作暂不可用；已有后台任务不受此页面禁用影响。");
                    rows(checks,result.optJSONArray("checks"),true);rows(orders,result.optJSONArray("orders"),false);
                }
                refreshWatch();
                timer.postDelayed(poll,4000);
            });
        });
    }
    void rows(LinearLayout box,JSONArray list,boolean holdings){
        box.removeAllViews();
        if(list==null||list.length()==0){label(box,holdings?"暂无盘前核对记录":"暂无策略委托",15,0xff647570,false);return;}
        for(int i=0;i<list.length();i++){
            JSONObject row=list.optJSONObject(i);String plan=row.optString("plan");
            String code=plan.substring(plan.lastIndexOf('/')+1);
            label(box,code+"   "+row.optString("day"),15,ink,true);
            String detail=holdings?"账户持仓 "+row.optInt("total")+" 股 · 可卖 "+row.optInt("available")+" 股":
                row.optString("side")+" "+row.optString("price")+" 元 · 已成交 "+row.optInt("filled")+" / "+row.optInt("qty")+" 股";
            label(box,detail,14,green,false);
        }
    }
}
