package com.tcdataconsultants.qbeat;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.SharedPreferences;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.StateListDrawable;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.text.InputType;
import android.text.SpannableString;
import android.text.Spanned;
import android.text.style.ForegroundColorSpan;
import android.view.Gravity;
import android.view.KeyEvent;
import android.view.View;
import android.view.WindowManager;
import android.view.inputmethod.InputMethodManager;
import android.webkit.JavascriptInterface;
import android.webkit.WebChromeClient;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.webkit.WebResourceRequest;
import android.widget.Button;
import android.widget.EditText;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.FrameLayout;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** Native TV shell. Only the visible YouTube player uses a WebView. */
public final class MainActivity extends Activity {
    private static final String BASE = "https://89.167.98.40:8443";
    private static final String PLAYER_ORIGIN = "https://com.tcdataconsultants.qbeat/";
    private static final int BG=0xff111014, PANEL=0xff1b1921, INK=0xfff2f0e9, MUTED=0xffaaa6af, LIME=0xffd6fa77, PURPLE=0xffb2a0ed;
    private final Handler ui=new Handler(Looper.getMainLooper());
    private final ExecutorService network=Executors.newSingleThreadExecutor();
    private final String client=UUID.randomUUID().toString();
    private SharedPreferences prefs;
    private volatile String cookie="";
    private boolean foreground=false, signedIn=false, connected=false, polling=false, ytReady=false, paused=false, playbackFailed=false;
    private long currentId=-1, loadedId=-1;
    private String currentVideo="";
    private String nextTitle="";
    private int secondsRemaining=0;
    private boolean stageMode=false,stageControls=false,captionsEnabled=false;
    private LinearLayout root, queueList,headerRow,bodyRow,leftColumn,rightColumn,controlRow;
    private TextView comingNext;
    private ImageView guestPhoto;
    private String currentAvatar="";
    private boolean compactMode=false,introductions=true,introducing=false;
    private int introGeneration=0;
    private String pickedName="Guest",pickedIcon="♫",sourceLabel="Shared room",loadedSource="";
    private int pickedColor=LIME;
    private FrameLayout screen;
    private LinearLayout introOverlay,identityRow;
    private ImageView introPhoto;
    private TextView introIcon,introName,introSong;
    private ImageView joinQr;
    private String qrMode="";
    private boolean countdownEnabled=false;
    private int totalRemaining=0;
    private TextView countdownView;
    private TextView title, subtitle, status, connection;
    private WebView video;
    private Button playButton, pauseButton;
    private final Runnable pollLoop=()->poll(null);

    @Override public void onCreate(Bundle state){
        super.onCreate(state);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        immersive();
        prefs=getSharedPreferences("qbeat",MODE_PRIVATE);
        stageMode=prefs.getBoolean("stage",false);
        captionsEnabled=prefs.getBoolean("captions",false);
        compactMode=prefs.getBoolean("compact",false);
        introductions=prefs.getBoolean("introductions",true);
        countdownEnabled=prefs.getBoolean("countdown",false);
        cookie=prefs.getString("session","");
        if(cookie.isEmpty()) showLogin(""); else {signedIn=true;showTV();}
    }
    private void immersive(){getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_FULLSCREEN|View.SYSTEM_UI_FLAG_HIDE_NAVIGATION|View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY|View.SYSTEM_UI_FLAG_LAYOUT_STABLE);}
    private int dp(float n){return Math.round(n*getResources().getDisplayMetrics().density);}
    private LinearLayout column(){LinearLayout l=new LinearLayout(this);l.setOrientation(LinearLayout.VERTICAL);return l;}
    private LinearLayout row(){LinearLayout l=new LinearLayout(this);l.setOrientation(LinearLayout.HORIZONTAL);l.setGravity(Gravity.CENTER_VERTICAL);return l;}
    private TextView text(String s,int size,int color){TextView t=new TextView(this);t.setText(s);t.setTextSize(size);t.setTextColor(color);t.setFontFeatureSettings("kern");t.setTypeface(Typeface.create("sans-serif",Typeface.NORMAL));return t;}
    private GradientDrawable shape(int fill,int stroke){GradientDrawable d=new GradientDrawable();d.setColor(fill);d.setCornerRadius(dp(9));if(stroke!=0)d.setStroke(dp(2),stroke);return d;}
    private Button button(String s,Runnable action){
        Button b=new Button(this);b.setText(s);b.setTextSize(13);b.setAllCaps(false);b.setTextColor(INK);b.setPadding(dp(16),0,dp(16),0);b.setMinHeight(0);b.setMinimumHeight(0);
        StateListDrawable d=new StateListDrawable();d.addState(new int[]{android.R.attr.state_focused},shape(0xff39322a,LIME));d.addState(new int[]{android.R.attr.state_pressed},shape(0xff39322a,LIME));d.addState(new int[]{},shape(0xff302b39,0));b.setBackground(d);b.setOnClickListener(v->action.run());b.setFocusable(true);b.setId(View.generateViewId());return b;
    }
    private void gap(LinearLayout parent,int height){View v=new View(this);parent.addView(v,new LinearLayout.LayoutParams(1,dp(height)));}
    private void showLogin(String error){
        connected=false;signedIn=false;ui.removeCallbacks(pollLoop);
        introGeneration++;introducing=false;
        ytReady=false;currentId=-1;loadedId=-1;playbackFailed=false;
        if(video!=null){video.removeJavascriptInterface("Qbeat");video.destroy();video=null;}
        root=column();root.setBackgroundColor(BG);root.setPadding(dp(45),dp(22),dp(45),dp(22));root.setGravity(Gravity.CENTER);
        TextView brand=text("q.  QBEAT",34,LIME);brand.setTypeface(null,Typeface.BOLD);root.addView(brand);gap(root,10);
        root.addView(text("One room. Everyone’s soundtrack.",20,INK));gap(root,16);
        root.addView(text("Enter your host PIN to connect this TV.",14,MUTED));gap(root,12);
        EditText pin=new EditText(this);pin.setTextColor(INK);pin.setTextSize(20);pin.setGravity(Gravity.CENTER);pin.setHint("Host PIN");pin.setHintTextColor(MUTED);pin.setSingleLine(true);pin.setInputType(InputType.TYPE_CLASS_NUMBER|InputType.TYPE_NUMBER_VARIATION_PASSWORD);pin.setBackground(shape(PANEL,0));root.addView(pin,new LinearLayout.LayoutParams(dp(300),dp(48)));gap(root,12);
        TextView message=text(error,13,PURPLE);
        Button connect=button("Connect TV  →",()->{
            String code=pin.getText().toString();if(code.isEmpty())return;
            ((InputMethodManager)getSystemService(INPUT_METHOD_SERVICE)).hideSoftInputFromWindow(pin.getWindowToken(),0);
            message.setText("Connecting…");
            network.execute(()->{try{call("login",new JSONObject().put("pin",code));ui.post(()->{signedIn=true;showTV();});}catch(Exception e){ui.post(()->message.setText(safeMessage(e)));}});
        });root.addView(connect,new LinearLayout.LayoutParams(dp(300),dp(44)));gap(root,12);root.addView(message);gap(root,10);root.addView(text("Guest requests: "+BASE,11,MUTED));setContentView(root);connect.requestFocus();
    }
    private void showTV(){
        root=column();root.setBackgroundColor(BG);root.setPadding(dp(32),dp(20),dp(32),dp(20));
        LinearLayout header=row();headerRow=header;TextView brand=text("q.  QBEAT",25,LIME);brand.setTypeface(null,Typeface.BOLD);header.addView(brand);TextView tag=text("    THE ROOM IS LISTENING.",10,MUTED);header.addView(tag,new LinearLayout.LayoutParams(0,dp(40),1));tag.setGravity(Gravity.CENTER_VERTICAL);connection=text("○ Not connected",12,MUTED);header.addView(connection);root.addView(header,new LinearLayout.LayoutParams(-1,dp(42)));gap(root,12);
        LinearLayout body=row();bodyRow=body;body.setGravity(Gravity.TOP);root.addView(body,new LinearLayout.LayoutParams(-1,0,1));
        LinearLayout left=column();leftColumn=left;body.addView(left,new LinearLayout.LayoutParams(0,-1,1));
        video=new WebView(this);video.setBackgroundColor(Color.BLACK);video.getSettings().setJavaScriptEnabled(true);video.getSettings().setDomStorageEnabled(true);video.getSettings().setMediaPlaybackRequiresUserGesture(false);video.getSettings().setAllowFileAccess(false);video.getSettings().setAllowContentAccess(false);video.getSettings().setSupportZoom(false);
        android.webkit.CookieManager.getInstance().setAcceptCookie(true);android.webkit.CookieManager.getInstance().setAcceptThirdPartyCookies(video,true);
        video.setWebChromeClient(new WebChromeClient());
        video.setWebViewClient(new WebViewClient(){
            @Override public boolean shouldOverrideUrlLoading(WebView view,WebResourceRequest request){return request.isForMainFrame();}
            @Override public boolean shouldOverrideUrlLoading(WebView view,String url){return !(url.startsWith("https://www.youtube.com/")||url.startsWith("https://consent.youtube.com/"));}
        });
        video.addJavascriptInterface(new PlayerBridge(),"Qbeat");
        left.addView(video,new LinearLayout.LayoutParams(-1,0,1));
        countdownView=text("",16,LIME);countdownView.setGravity(Gravity.RIGHT);countdownView.setPadding(dp(12),dp(5),dp(12),dp(5));countdownView.setVisibility(View.GONE);left.addView(countdownView,new LinearLayout.LayoutParams(-1,-2));
        comingNext=text("",16,LIME);comingNext.setPadding(dp(18),dp(11),dp(18),dp(11));comingNext.setBackgroundColor(0xff282234);comingNext.setMaxLines(2);comingNext.setVisibility(View.GONE);left.addView(comingNext);gap(left,10);
        title=text("The room is yours.",20,INK);title.setMaxLines(1);title.setEllipsize(android.text.TextUtils.TruncateAt.END);left.addView(title);
        LinearLayout identity=row();identityRow=identity;subtitle=text("Scan the QR code and make the first pick.",11,MUTED);subtitle.setMaxLines(2);identity.addView(subtitle,new LinearLayout.LayoutParams(0,-2,1));guestPhoto=new ImageView(this);guestPhoto.setScaleType(ImageView.ScaleType.CENTER_CROP);guestPhoto.setVisibility(View.GONE);LinearLayout.LayoutParams avatarLp=new LinearLayout.LayoutParams(dp(26),dp(26));avatarLp.setMargins(dp(8),0,0,0);identity.addView(guestPhoto,avatarLp);left.addView(identity);gap(left,6);
        status=text("Connect this TV to start playing the queue.",11,PURPLE);status.setMinHeight(dp(30));status.setMaxLines(2);left.addView(status);gap(left,4);
        LinearLayout controls=row();controlRow=controls;
        playButton=button("Connect player",()->{if(!connected){connected=true;poll(null);}else retry();});
        pauseButton=button("Pause",()->control(paused?"resume":"pause"));
        Button skip=button("Skip  →",()->control("skip"));Button exit=button("More  ⋯",this::showMore);
        for(Button b:new Button[]{playButton,pauseButton,skip,exit}){LinearLayout.LayoutParams lp=new LinearLayout.LayoutParams(-2,dp(42));lp.setMargins(0,0,dp(9),0);controls.addView(b,lp);}left.addView(controls);
        LinearLayout right=column();rightColumn=right;right.setPadding(dp(23),dp(16),dp(14),dp(12));right.setBackground(shape(PANEL,0));LinearLayout.LayoutParams rightLp=new LinearLayout.LayoutParams(dp(225),-1);rightLp.setMargins(dp(22),0,0,0);body.addView(right,rightLp);
        TextView join=text("YOUR NEXT PICK STARTS HERE",9,LIME);right.addView(join);gap(right,8);right.addView(text("Scan. Pick. Play.",22,INK));gap(right,12);
        ImageView qr=new ImageView(this);joinQr=qr;qrMode="";qr.setContentDescription("Scan to open Qbeat");qr.setScaleType(ImageView.ScaleType.FIT_CENTER);right.addView(qr,new LinearLayout.LayoutParams(dp(150),dp(150)));gap(right,8);
        right.addView(text("Open your phone camera to join.",10,MUTED));gap(right,14);right.addView(text("UP NEXT",10,PURPLE));gap(right,7);queueList=column();right.addView(queueList,new LinearLayout.LayoutParams(-1,0,1));
        TextView foot=text("Everyone gets a turn.  •  YouTube playback",9,MUTED);right.addView(foot);
        screen=new FrameLayout(this);screen.setBackgroundColor(BG);screen.addView(root,new FrameLayout.LayoutParams(-1,-1));
        introOverlay=column();introOverlay.setBackgroundColor(0xff201b2b);introOverlay.setGravity(Gravity.CENTER);introOverlay.setPadding(dp(40),dp(25),dp(40),dp(25));
        introPhoto=new ImageView(this);introPhoto.setScaleType(ImageView.ScaleType.CENTER_CROP);introOverlay.addView(introPhoto,new LinearLayout.LayoutParams(dp(160),dp(160)));
        introIcon=text("♫",100,LIME);introIcon.setGravity(Gravity.CENTER);introOverlay.addView(introIcon,new LinearLayout.LayoutParams(dp(160),dp(160)));gap(introOverlay,15);
        introName=text("",32,LIME);introName.setGravity(Gravity.CENTER);introOverlay.addView(introName);gap(introOverlay,10);introSong=text("",17,MUTED);introSong.setGravity(Gravity.CENTER);introOverlay.addView(introSong);introOverlay.setVisibility(View.GONE);screen.addView(introOverlay,new FrameLayout.LayoutParams(-1,-1));
        setContentView(screen);immersive();stageControls=true;applyStage();playButton.requestFocus();
        try(InputStream in=getAssets().open("player.html")){video.loadDataWithBaseURL(PLAYER_ORIGIN,new String(readAll(in),StandardCharsets.UTF_8),"text/html","UTF-8",null);}catch(Exception e){status.setText("Player files are missing. Reinstall the app.");}
        updateQr("shared");
        poll(null);
    }
    private String safeMessage(Exception e){String s=e.getMessage();return s==null?"Connection failed. Please try again.":s;}
    private byte[] readAll(InputStream in)throws Exception{ByteArrayOutputStream out=new ByteArrayOutputStream();byte[] b=new byte[8192];int n;while((n=in.read(b))!=-1)out.write(b,0,n);return out.toByteArray();}
    private JSONObject call(String path,JSONObject body)throws Exception{
        HttpURLConnection c=(HttpURLConnection)new URL(BASE+"/api/"+path).openConnection();c.setConnectTimeout(8000);c.setReadTimeout(10000);c.setInstanceFollowRedirects(false);c.setRequestProperty("Accept","application/json");if(!cookie.isEmpty())c.setRequestProperty("Cookie",cookie);
        try{
            if(body!=null){c.setRequestMethod("POST");c.setDoOutput(true);c.setRequestProperty("Content-Type","application/json");byte[] bytes=body.toString().getBytes(StandardCharsets.UTF_8);c.setFixedLengthStreamingMode(bytes.length);try(java.io.OutputStream out=c.getOutputStream()){out.write(bytes);}}
            int code=c.getResponseCode();String set=c.getHeaderField("Set-Cookie");if(set!=null&&set.startsWith("session=")){cookie=set.split(";",2)[0];prefs.edit().putString("session",cookie).apply();}
            InputStream stream=code>=400?c.getErrorStream():c.getInputStream();if(stream==null)throw new Exception("Server unavailable ("+code+").");JSONObject result;try(InputStream in=stream){result=new JSONObject(new String(readAll(in),StandardCharsets.UTF_8));}if(code>=400)throw new Exception(result.optString("error","Request failed ("+code+")."));return result;
        }finally{c.disconnect();}
    }
    private void poll(JSONObject extra){
        if(!foreground||!signedIn)return;
        if(polling){if(extra!=null)ui.postDelayed(()->poll(extra),150);return;}
        polling=true;ui.removeCallbacks(pollLoop);final boolean claim=connected;
        network.execute(()->{try{
            if(claim){JSONObject body=extra==null?new JSONObject():extra;body.put("client",client);call("host/player",body);}
            JSONObject state=call("host/tv/state",null);
            ui.post(()->{polling=false;if(!foreground||!signedIn)return;if(!state.optBoolean("host")){cookie="";prefs.edit().remove("session").apply();showLogin("Your host session expired. Sign in again.");return;}render(state);ui.postDelayed(pollLoop,3000);});
        }catch(Exception e){ui.post(()->{polling=false;if(!foreground||!signedIn)return;connected=false;if(video!=null)video.evaluateJavascript("setPaused(true)",null);connection.setText("○ Disconnected");status.setText(safeMessage(e));playButton.setText("Reconnect");ui.postDelayed(pollLoop,5000);});}});
    }
    private void render(JSONObject state){
        JSONObject source=state.optJSONObject("source");sourceLabel=source==null?"Shared room":source.optString("label","Shared room");String sourceKey=source==null?"shared":source.optString("mode")+":"+source.optInt("playlist_id",0);
        if(!sourceKey.equals(loadedSource)){loadedSource=sourceKey;loadedId=-1;cancelIntro();}updateQr(source==null?"shared":source.optString("mode","shared"));
        paused=state.optBoolean("paused");pauseButton.setText(paused?"Resume  ▶":"Pause  Ⅱ");connection.setText(connected?(paused?"● Paused":"● Player connected"):"○ Ready to connect");connection.setTextColor(connected?LIME:MUTED);
        JSONObject song=state.optJSONObject("now");long next=song==null?-1:song.optLong("id",-1);String vid=song==null?"":song.optString("video_id");
        currentId=next;currentVideo=vid;
        title.setText(song==null?"The room is yours.":song.optString("display_title",song.optString("title")));
        if(song==null){subtitle.setText("Scan the QR code and make the first pick.");}else{String prefix=song.optString("display_artist",song.optString("artist"))+"  ·  Picked by ";String who=song.optString("guest");SpannableString line=new SpannableString(prefix+who+" "+song.optString("guest_icon","♫"));line.setSpan(new ForegroundColorSpan(guestColor(song)),prefix.length(),prefix.length()+who.length(),Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);subtitle.setText(line);pickedName=who;pickedIcon=song.optString("guest_icon","♫");pickedColor=guestColor(song);}
        loadGuestPhoto(song==null?"":song.optString("guest_photo",""));
        JSONArray queue=state.optJSONArray("queue");nextTitle=queue!=null&&queue.length()>0?queue.optJSONObject(0).optString("display_title",queue.optJSONObject(0).optString("title")):"";queueList.removeAllViews();if(queue==null||queue.length()==0)queueList.addView(text("Your next great pick goes here.",11,MUTED));else for(int i=0;i<Math.min(3,queue.length());i++){JSONObject s=queue.optJSONObject(i);TextView item=text((i+1)+"  "+s.optString("display_title",s.optString("title")),12,INK);item.setMaxLines(2);item.setEllipsize(android.text.TextUtils.TruncateAt.END);queueList.addView(item);TextView guest=text(s.optString("guest")+" "+s.optString("guest_icon","♫"),10,guestColor(s));guest.setMaxLines(1);queueList.addView(guest);gap(queueList,7);}
        if(connected&&ytReady){
            if(next!=loadedId){cancelIntro();loadedId=next;secondsRemaining=0;totalRemaining=0;playbackFailed=false;updateNext();updateCountdown();if(next<0){video.evaluateJavascript("idle()",null);status.setText("Connected. Waiting for the next pick.");}else{loadVideo();status.setText("Loading your next pick…");}}
            else if(next>=0&&!playbackFailed&&!introducing)video.evaluateJavascript("setPaused("+paused+")",null);
            if(!playbackFailed)playButton.setText("Retry track");
        }
        updateNext();
        updateCountdown();
    }
    private void loadVideo(){if(currentId<0||!ytReady)return;if(introductions&&!paused){startIntro();}else loadVideoNow();}
    private void updateQr(String mode){if(mode.equals(qrMode)||joinQr==null)return;qrMode=mode;String path=mode.equals("personal")?"/qr.png?target=personal":"/qr.png";network.execute(()->{try{HttpURLConnection c=(HttpURLConnection)new URL(BASE+path).openConnection();c.setConnectTimeout(5000);c.setReadTimeout(5000);Bitmap image;try(InputStream in=c.getInputStream()){image=BitmapFactory.decodeStream(in);}finally{c.disconnect();}ui.post(()->{if(mode.equals(qrMode))joinQr.setImageBitmap(image);});}catch(Exception ignored){}});}
    private void loadVideoNow(){if(currentId>=0&&ytReady&&foreground&&connected){video.evaluateJavascript("setCaptions("+captionsEnabled+")",null);video.evaluateJavascript("loadTrack("+JSONObject.quote(currentVideo)+","+paused+")",null);}}
    private void cancelIntro(){introGeneration++;introducing=false;if(introOverlay!=null){introOverlay.animate().cancel();introOverlay.setVisibility(View.GONE);}if(root!=null)root.setVisibility(View.VISIBLE);}
    private void startIntro(){
        cancelIntro();introducing=true;final int generation=introGeneration;final long track=currentId;
        video.evaluateJavascript("setPaused(true)",null);root.setVisibility(View.GONE);introOverlay.setVisibility(View.VISIBLE);introName.setText("Picked by "+pickedName+" "+pickedIcon);introName.setTextColor(pickedColor);introSong.setText(title.getText());
        introPhoto.setImageDrawable(guestPhoto.getDrawable());introPhoto.setVisibility(guestPhoto.getDrawable()!=null&&!currentAvatar.isEmpty()?View.VISIBLE:View.GONE);introIcon.setText(pickedIcon);introIcon.setVisibility(introPhoto.getVisibility()==View.VISIBLE?View.GONE:View.VISIBLE);
        introOverlay.setTranslationX(getResources().getDisplayMetrics().widthPixels);introOverlay.setAlpha(0f);
        introOverlay.animate().translationX(0).alpha(1f).setDuration(300).withEndAction(()->ui.postDelayed(()->{
            if(generation!=introGeneration||!foreground||track!=currentId)return;
            introOverlay.animate().translationX(-getResources().getDisplayMetrics().widthPixels).alpha(0f).setDuration(300).withEndAction(()->{
                if(generation!=introGeneration)return;introducing=false;introOverlay.setVisibility(View.GONE);root.setVisibility(View.VISIBLE);loadVideoNow();
            }).start();
        },1400)).start();
    }
    private int guestColor(JSONObject song){try{return Color.parseColor(song.optString("guest_color","#d6fa77"));}catch(Exception e){return LIME;}}
    private void loadGuestPhoto(String path){
        if(path.equals(currentAvatar))return;currentAvatar=path;guestPhoto.setVisibility(View.GONE);guestPhoto.setImageDrawable(null);
        if(!path.matches("/avatars/[a-f0-9]{32}\\.jpg"))return;
        network.execute(()->{try{HttpURLConnection c=(HttpURLConnection)new URL(BASE+path).openConnection();c.setConnectTimeout(5000);c.setReadTimeout(5000);Bitmap image;try(InputStream in=c.getInputStream()){image=BitmapFactory.decodeStream(in);}finally{c.disconnect();}ui.post(()->{if(path.equals(currentAvatar)&&image!=null){guestPhoto.setImageBitmap(image);guestPhoto.setVisibility(View.VISIBLE);if(introducing){introPhoto.setImageBitmap(image);introPhoto.setVisibility(View.VISIBLE);introIcon.setVisibility(View.GONE);}}});}catch(Exception ignored){}});
    }
    private void showMore(){new AlertDialog.Builder(this).setTitle("Qbeat · "+sourceLabel).setItems(new String[]{"Music source / accounts",stageMode?"Exit fullscreen TV mode":"Fullscreen TV mode",compactMode?"Standard video size":"Compact player",captionsEnabled?"Turn subtitles off":"Turn subtitles on",introductions?"Turn picked-by introductions off":"Turn picked-by introductions on",countdownEnabled?"Turn countdown off":"Turn countdown on","Sign out"},(d,which)->{
        if(which==0)chooseMusicSource();
        if(which==1){stageMode=!stageMode;stageControls=false;prefs.edit().putBoolean("stage",stageMode).apply();applyStage();if(stageMode)video.requestFocus();else playButton.requestFocus();}
        if(which==2){compactMode=!compactMode;prefs.edit().putBoolean("compact",compactMode).apply();applyStage();}
        if(which==3){captionsEnabled=!captionsEnabled;prefs.edit().putBoolean("captions",captionsEnabled).apply();video.evaluateJavascript("setCaptions("+captionsEnabled+")",null);status.setText(captionsEnabled?"Subtitles on when available.":"Subtitles off. Text built into the video cannot be removed.");}
        if(which==4){introductions=!introductions;prefs.edit().putBoolean("introductions",introductions).apply();}
        if(which==5){countdownEnabled=!countdownEnabled;prefs.edit().putBoolean("countdown",countdownEnabled).apply();updateCountdown();}
        if(which==6)confirmSignOut();
    }).show();}
    private void chooseMusicSource(){network.execute(()->{try{JSONArray accounts=call("host/tv/accounts",null).getJSONArray("accounts");ui.post(()->{
        String[] options=new String[accounts.length()+2];options[0]="Shared room queue";options[1]="Link an account";for(int i=0;i<accounts.length();i++)options[i+2]=accounts.optJSONObject(i).optString("display_name")+" (@"+accounts.optJSONObject(i).optString("username")+")";
        new AlertDialog.Builder(this).setTitle("Whose music?").setItems(options,(d,index)->{if(index==0)changeSource(-1);else if(index==1)showPairCode();else choosePlaylist(accounts.optJSONObject(index-2).optInt("id"),options[index]);}).show();
    });}catch(Exception e){ui.post(()->status.setText(safeMessage(e)));}});}
    private void showPairCode(){network.execute(()->{try{JSONObject pair=call("host/tv/pair",new JSONObject());ui.post(()->new AlertDialog.Builder(this).setTitle("TV code: "+pair.optString("code")).setMessage("On your phone, open "+BASE+"/personal, sign in, and select Link to TV. Enter this code within 10 minutes. Then reopen Music source on this TV to choose the account.").setPositiveButton("Done",(d,w)->chooseMusicSource()).show());}catch(Exception e){ui.post(()->status.setText(safeMessage(e)));}});}
    private void choosePlaylist(int accountId,String name){network.execute(()->{try{JSONArray list=call("host/tv/accounts/"+accountId+"/playlists",null).getJSONArray("playlists");ui.post(()->{
        if(list.length()==0){new AlertDialog.Builder(this).setTitle(name).setMessage("Create a playlist on your phone first.").setPositiveButton("OK",null).show();return;}
        String[] labels=new String[list.length()];for(int i=0;i<list.length();i++){JSONObject p=list.optJSONObject(i);labels[i]=p.optString("name")+" · "+p.optInt("tracks")+" tracks";}
        new AlertDialog.Builder(this).setTitle(name+"’s playlists").setItems(labels,(d,index)->changeSource(list.optJSONObject(index).optInt("id"))).show();
    });}catch(Exception e){ui.post(()->status.setText(safeMessage(e)));}});}
    private void changeSource(int playlistId){network.execute(()->{try{JSONObject body=new JSONObject().put("mode",playlistId<0?"shared":"personal");if(playlistId>=0)body.put("playlist_id",playlistId);call("host/tv/source",body);ui.post(()->{cancelIntro();video.evaluateJavascript("idle()",null);connected=true;loadedId=-1;currentId=-1;currentVideo="";playbackFailed=false;poll(null);});}catch(Exception e){ui.post(()->status.setText(safeMessage(e)));}});}
    private void applyStage(){
        if(root==null||leftColumn==null)return;
        root.setPadding(stageMode?0:dp(32),stageMode?0:dp(20),stageMode?0:dp(32),stageMode?0:dp(20));
        for(int i=0;i<root.getChildCount();i++){View child=root.getChildAt(i);child.setVisibility(!stageMode||child==bodyRow?View.VISIBLE:View.GONE);}
        rightColumn.setVisibility(stageMode?View.GONE:View.VISIBLE);
        LinearLayout.LayoutParams videoSize=compactMode?new LinearLayout.LayoutParams(dp(356),dp(200)):new LinearLayout.LayoutParams(-1,0,1);videoSize.gravity=Gravity.CENTER_HORIZONTAL;video.setLayoutParams(videoSize);leftColumn.setGravity(compactMode?Gravity.CENTER_VERTICAL:Gravity.TOP);title.setTextSize(compactMode?30:20);title.setMaxLines(compactMode?2:1);subtitle.setTextSize(compactMode?15:11);
        for(int i=0;i<leftColumn.getChildCount();i++){
            View child=leftColumn.getChildAt(i);if(child==comingNext||child==countdownView)continue;
            child.setVisibility(!stageMode||child==video||(compactMode&&(child==title||child==identityRow))||(stageControls&&(child==controlRow||child==status))?View.VISIBLE:View.GONE);
        }
        updateNext();updateCountdown();immersive();
    }
    private void updateNext(){if(comingNext==null)return;boolean show=connected&&!playbackFailed&&secondsRemaining>0&&secondsRemaining<=10&&!nextTitle.isEmpty();comingNext.setVisibility(show?View.VISIBLE:View.GONE);if(show)comingNext.setText("COMING NEXT  ·  "+nextTitle+"  ·  in "+secondsRemaining+"s");}
    private void updateCountdown(){if(countdownView==null)return;boolean show=countdownEnabled&&connected&&!introducing&&!playbackFailed&&currentId>=0&&totalRemaining>0;countdownView.setVisibility(show?View.VISIBLE:View.GONE);if(show){int hours=totalRemaining/3600,minutes=(totalRemaining%3600)/60,seconds=totalRemaining%60;String value=hours>0?String.format(java.util.Locale.US,"%d:%02d:%02d",hours,minutes,seconds):String.format(java.util.Locale.US,"%d:%02d",minutes,seconds);countdownView.setText("Time left  "+value);}}
    private void revealControls(){if(stageMode){stageControls=true;applyStage();playButton.requestFocus();}}
    private void retry(){playbackFailed=false;loadedId=-1;status.setText("Retrying this track…");poll(null);}
    private void control(String action){if(!signedIn)return;network.execute(()->{try{call("host/control",new JSONObject().put("action",action));ui.post(()->poll(null));}catch(Exception e){ui.post(()->status.setText(safeMessage(e)));}});}
    private void confirmSignOut(){new AlertDialog.Builder(this).setTitle("Disconnect this TV?").setMessage("The music stops on this screen. Guests can still add songs.").setNegativeButton("Keep playing",null).setPositiveButton("Sign out",(d,w)->{connected=false;signedIn=false;cookie="";prefs.edit().remove("session").apply();ui.removeCallbacks(pollLoop);if(video!=null){video.removeJavascriptInterface("Qbeat");video.destroy();video=null;}showLogin("");}).show();}
    public final class PlayerBridge {
        @JavascriptInterface public void progress(String vid,double elapsed,double duration){ui.post(()->{if(!foreground||introducing||!vid.equals(currentVideo)||Double.isNaN(duration)||Double.isInfinite(duration)||Double.isNaN(elapsed)||Double.isInfinite(elapsed))return;double left=duration-elapsed;totalRemaining=duration>0&&left>0?(int)Math.ceil(left):0;secondsRemaining=duration>0&&left>0&&left<=10?(int)Math.ceil(left):0;updateNext();updateCountdown();});}
        @JavascriptInterface public void ready(){ui.post(()->{ytReady=true;loadedId=-1;if(signedIn){status.setText("YouTube player ready. Connect this TV to begin.");poll(null);}});}
        @JavascriptInterface public void ended(String vid){ui.post(()->{if(!connected||introducing||playbackFailed||!vid.equals(currentVideo))return;try{poll(new JSONObject().put("ended",currentId));}catch(Exception ignored){}});}
        @JavascriptInterface public void playing(){ui.post(()->{if(introducing)return;playbackFailed=false;if(stageMode&&stageControls){stageControls=false;applyStage();}if(status!=null)status.setText("Now playing · "+sourceLabel);});}
        @JavascriptInterface public void blocked(){ui.post(()->{playbackFailed=true;revealControls();status.setText("Press Play inside the video, or select Retry track to enable sound.");playButton.setText("Enable sound");});}
        @JavascriptInterface public void loadFailed(){ui.post(()->{playbackFailed=true;status.setText("YouTube could not load. Check the connection and reopen Qbeat.");});}
        @JavascriptInterface public void error(int code){ui.post(()->{
            if(introducing)return;
            playbackFailed=true;revealControls();updateNext();updateCountdown();String reason;
            switch(code){case 2:reason="YouTube rejected this video request.";break;case 5:reason="This device could not play this video.";break;case 100:reason="This video is unavailable or private.";break;case 101:case 150:reason="YouTube blocked this video in the embedded player.";break;case 153:reason="YouTube could not identify this player.";break;default:reason="YouTube playback failed.";}
            status.setText("YouTube error "+code+": "+reason+" Retry or skip; your queue is preserved.");playButton.setText("Retry track");try{poll(new JSONObject().put("error_code",code).put("song_id",currentId));}catch(Exception ignored){}
        });}
    }
    @Override protected void onResume(){super.onResume();foreground=true;immersive();if(video!=null)video.onResume();if(signedIn)poll(null);}
    @Override protected void onPause(){foreground=false;cancelIntro();loadedId=-1;ui.removeCallbacks(pollLoop);if(video!=null){video.evaluateJavascript("setPaused(true)",null);video.onPause();}super.onPause();}
    @Override protected void onDestroy(){foreground=false;ui.removeCallbacksAndMessages(null);if(video!=null){video.removeJavascriptInterface("Qbeat");video.destroy();video=null;}network.shutdownNow();super.onDestroy();}
    @Override public boolean onKeyDown(int code,KeyEvent event){
        if(signedIn&&event.getRepeatCount()==0&&code==KeyEvent.KEYCODE_MENU){if(stageMode){stageControls=!stageControls;applyStage();if(stageControls)playButton.requestFocus();else video.requestFocus();}else showMore();return true;}
        if(signedIn&&event.getRepeatCount()==0&&code==KeyEvent.KEYCODE_BACK&&stageMode){stageMode=false;prefs.edit().putBoolean("stage",false).apply();applyStage();playButton.requestFocus();return true;}
        if(signedIn&&event.getRepeatCount()==0){if(code==KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE){control(paused?"resume":"pause");return true;}if(code==KeyEvent.KEYCODE_MEDIA_NEXT){control("skip");return true;}if(code==KeyEvent.KEYCODE_BACK){if(video!=null&&video.hasFocus()){playButton.requestFocus();return true;}new AlertDialog.Builder(this).setTitle("Leave Qbeat?").setMessage("Playback will stop on this TV.").setNegativeButton("Keep listening",null).setPositiveButton("Exit",(d,w)->finish()).show();return true;}}
        return super.onKeyDown(code,event);
    }
}
