package com.zmax.state3d.aoi;

import android.app.Activity;
import android.os.Bundle;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.webkit.WebChromeClient;
import android.webkit.ConsoleMessage;
import android.view.WindowManager;
import android.util.Log;

/**
 * Z-MAX 场景叠加 —— 手机桌面上独立的一个入口 (与 3D 全链同一个 APK)。
 *
 * 打开的是 4060 上的手机版场景叠加页: 真机视频流 + 仿真/大模型/检测三类边界框。
 *
 * ★ 为什么直连 4060 而不是走站点:
 *   站点 (datadrive.world) 是 HTTPS, 页面里再取 http:// 的视频流属"混合内容",
 *   会被浏览器内核拦死。所以这个页面由 4060 自己用 http 提供 (与视频流同源)。
 * ★ 所以: 手机必须与 4060 在同一个局域网(产线 WiFi)。
 *   换网段/换机器时, 只改下面这一行 LANDSCAPE_URL 即可。
 */
public class OverlayActivity extends Activity {
    private WebView webView;

    /** 4060 上 cam_live_stream.py 提供的手机版叠加页 (局域网直连) */
    private static final String OVERLAY_URL = "http://10.163.146.78:8791/app";

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        webView = new WebView(this);
        setContentView(webView);

        WebSettings s = webView.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setMediaPlaybackRequiresUserGesture(false);
        s.setCacheMode(WebSettings.LOAD_DEFAULT);
        // 允许 http 明文与混合内容 (manifest 里也已 usesCleartextTraffic=true)
        s.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);
        s.setAllowFileAccess(true);

        webView.setWebViewClient(new WebViewClient());
        webView.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onConsoleMessage(ConsoleMessage cm) {
                Log.d("ZMAX_OV", cm.message());
                return true;
            }
        });
        webView.loadUrl(OVERLAY_URL);
    }

    @Override
    public void onBackPressed() {
        if (webView != null && webView.canGoBack()) webView.goBack();
        else super.onBackPressed();
    }

    @Override
    protected void onDestroy() {
        if (webView != null) webView.destroy();
        super.onDestroy();
    }
}
