package com.zmax.room;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Context;
import android.content.DialogInterface;
import android.content.SharedPreferences;
import android.net.http.SslError;
import android.os.Bundle;
import android.view.View;
import android.view.WindowManager;
import android.webkit.ConsoleMessage;
import android.webkit.SslErrorHandler;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.EditText;
import android.widget.Toast;

/**
 * 📱 Z-MAX 现场 · 人机在环 (2026-09-27 老倪)
 *
 * 「veh.5.010 状态空间的 HIL 人机在环节点, 接入我的手机 APP … 把工位总揽的所有摄像头推流到 APP,
 *   像开视频会议一样选任意视角/全看/远程操作机器人」
 *
 * 为什么直接顶层加载 **http** 页 (而不是让现有的 https 页面嵌进去):
 *   相机流是工位机的 http MJPEG; 若外层页面是 https ⇒ **混合内容被浏览器内核拦死**(页面能开、画面永远黑)。
 *   所以本入口直接打开工位机 http 上的现场页 (10.163.146.78:8791/room), 页面与数据同源 ⇒ 不越混合内容红线。
 *   manifest 里 usesCleartextTraffic=true + 这里 MIXED_CONTENT_ALWAYS_ALLOW 是两道兜底。
 *
 * 长按屏幕可改地址(IP 变了不用重装 APK), 存 SharedPreferences。
 */
public class MainActivity extends Activity {

    private static final String DEFAULT_URL = "http://10.163.146.78:8791/room";   // 工位机现场页
    private WebView webView;
    private SharedPreferences sp;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);     // 现场看画面别锁屏

        sp = getSharedPreferences("zmax_room", Context.MODE_PRIVATE);

        webView = new WebView(this);
        WebSettings s = webView.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setMediaPlaybackRequiresUserGesture(false);
        s.setUseWideViewPort(true);
        s.setLoadWithOverviewMode(true);
        s.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);

        webView.setWebViewClient(new WebViewClient() {
            @Override
            public void onReceivedError(WebView v, WebResourceRequest req, WebResourceError err) {
                if (req != null && req.isForMainFrame()) {                        // 只报主框架失败, 别为素材刷屏
                    Toast.makeText(MainActivity.this,
                            "打不开 " + req.getUrl() + "\n" + err.getDescription()
                                    + "\n(长按屏幕可改地址)", Toast.LENGTH_LONG).show();
                }
            }

            @Override
            public void onReceivedSslError(WebView v, SslErrorHandler h, SslError e) {
                h.proceed();                                                      // 现场自签/内网证书
            }

            @Override
            public void onPageFinished(WebView v, String url) {
                Toast.makeText(MainActivity.this, "已连上工位机", Toast.LENGTH_SHORT).show();
            }
        });

        webView.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onConsoleMessage(ConsoleMessage m) {
                return true;                                                      // 静音, 不弹窗
            }
        });

        webView.setOnLongClickListener(new View.OnLongClickListener() {           // 长按改地址
            @Override
            public boolean onLongClick(View v) {
                askUrl();
                return true;
            }
        });

        setContentView(webView);
        webView.loadUrl(sp.getString("url", DEFAULT_URL));
    }

    private void askUrl() {
        final EditText e = new EditText(this);
        e.setText(sp.getString("url", DEFAULT_URL));
        new AlertDialog.Builder(this)
                .setTitle("现场页地址")
                .setView(e)
                .setPositiveButton("打开", new DialogInterface.OnClickListener() {
                    @Override
                    public void onClick(DialogInterface d, int w) {
                        String u = e.getText().toString().trim();
                        if (!u.startsWith("http")) u = "http://" + u;
                        sp.edit().putString("url", u).apply();
                        webView.loadUrl(u);
                    }
                })
                .setNeutralButton("恢复默认", new DialogInterface.OnClickListener() {
                    @Override
                    public void onClick(DialogInterface d, int w) {
                        sp.edit().putString("url", DEFAULT_URL).apply();
                        webView.loadUrl(DEFAULT_URL);
                    }
                })
                .setNegativeButton("取消", null)
                .show();
    }

    @Override
    public void onBackPressed() {
        if (webView.canGoBack()) {
            webView.goBack();
        } else {
            super.onBackPressed();
        }
    }
}
