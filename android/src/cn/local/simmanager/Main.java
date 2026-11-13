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
    LinearLayout page, checks, orders;
    TextView state, account, notice;
    Button control;
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
        ScrollView scroll=new ScrollView(this); scroll.setBackgroundColor(0xfff2f5ef);
        page=new LinearLayout(this); page.setOrientation(1);page.setPadding(dp(20),dp(22),dp(20),dp(20));
        scroll.addView(page);setContentView(scroll);
        label(page,"模拟仓管家",29,ink,true);
        LinearLayout header=card(green);account=label(header,"模拟账户",15,0xffd5eee3,false);
        state=label(header,"正在连接",30,Color.WHITE,true);
        notice=label(header,"",14,0xffd5eee3,false);
        control=new Button(this);header.addView(control);control.setText("连接中");control.setEnabled(false);
        control.setOnClickListener(v->load(resume?"resume":"pause"));
        label(page,"盘前持仓核对",19,ink,true);checks=card(Color.WHITE);
        label(page,"最近策略委托",19,ink,true);orders=card(Color.WHITE);
    }
    protected void onResume(){super.onResume();visible=true;load("status");}
    protected void onPause(){visible=false;timer.removeCallbacks(poll);super.onPause();}
    protected void onDestroy(){io.shutdownNow();super.onDestroy();}
    void load(String action){
        if(busy||!visible)return;
        timer.removeCallbacks(poll);busy=true;
        if(!action.equals("status"))control.setEnabled(false);
        io.execute(()->{
            JSONObject data=null;
            try{
                HttpURLConnection c=(HttpURLConnection)new URL("http://127.0.0.1:18735/"+action).openConnection();
                try{
                    c.setConnectTimeout(2500);c.setReadTimeout(10000);
                    c.setRequestProperty("Authorization","Bearer "+getSharedPreferences("local",0).getString("key",""));
                    if(!action.equals("status"))c.setRequestMethod("POST");
                    try(BufferedReader r=new BufferedReader(new InputStreamReader(c.getInputStream(),"UTF-8"))){
                        data=new JSONObject(r.readLine());
                    }
                }finally{c.disconnect();}
            }catch(Exception ignored){}
            final JSONObject result=data;
            runOnUiThread(()->{
                busy=false;if(!visible||isDestroyed())return;
                if(result==null){
                    state.setText("服务未连接");notice.setText("请检查本机管理服务和设备配对。");
                    control.setEnabled(false);control.setText("等待连接");
                }else{
                    state.setText(result.optString("status"));account.setText("模拟账户  "+result.optString("account"));
                    resume=result.optBoolean("paused")||!result.optBoolean("active");
                    control.setText(resume?"启动 / 恢复策略":"暂停策略");control.setEnabled(true);
                    notice.setText("暂停在本轮结束后生效，已有委托继续有效。");
                    rows(checks,result.optJSONArray("checks"),true);rows(orders,result.optJSONArray("orders"),false);
                }
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
