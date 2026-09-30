package com.zmax.live;

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
 * 📱 Z-MAX 实况 · 现场实况页 (2026-09-27)
 *
 * 打开工位机自己 http 提供的「现场实况」页 —— 所有活着的相机流 + 仿真/检测叠加。
 *
 * 为什么顶层直接加载 **http** 页, 而不是让站点(https)页面嵌进去:
 *   相机流是工位机的 http MJPEG; 外层页面若是 https ⇒ **混合内容被内核拦死**
 *   (页面能开、画面永远黑; usesCleartextTraffic + MIXED_CONTENT_ALWAYS_ALLOW 都救不了,
 *    内核按**页面源**判)。所以页面必须与视频流同源 —— 本入口直接 loadUrl 工位机 http 页。
 *
 * ★ 2026-09-27 修正: 工位机有两个网口, 手机在哪个网段不一定 ——
 *   老倪手机走 WiFi(10.163.146.x), 现场另一个网段是产线(192.168.23.x)。
 *   旧版把默认地址写死成产线口 ⇒ 手机在 WiFi 时打开就是空白页("用不了")。
 *   现在**自动依次试**: 上次成功的 → WiFi 口 → 产线口; 全不通才提示, 长按仍可手改。
 *
 * 本页只做"看"与页面上的只读工具按钮(叠加来源生成); 页面内没有软急停。
 */
public class MainActivity extends Activity {

    // 候选口(按"稳定优先 → 本地最快 → 打不通自动换"排序)
    // 2026-09-28 老倪: 「通过ECS端口转发发到手机 APP」⇒ ① 换成 ECS 稳定口
    //   (工位机经反向隧道把只读闸门挂到 datadrive.world/ov/, 任何网络都通;
    //    旧的易失 lhr 地址每次重连就变, 烧进包里的那份必然过期, 不再当主口)
    private static final String[] CANDIDATES = {
            // ① ECS 端口转发(稳定域名, 任何网络; 只读闸门, POST 一律 403)
            "https://datadrive.world/ov/overlay?k=zmax-live",
            // ② 现场 WiFi 口(同网时直连工位机, 带宽够)
            "http://10.163.146.78:8791/overlay",
            // ③ 产线口(备用)
            "http://192.168.23.50:8791/overlay",
    };

    private WebView webView;
    private SharedPreferences sp;
    private int tryIdx;                 // 当前试到第几个候选
    private boolean landed;             // 本页是否已成功落地(落地后报错不再自动跳, 免得来回弹)
    private String lastErrUrl = "";     // 刚报错的 URL —— 有的 WebView 版本失败后仍回调
                                        // onPageFinished, 不加这道闸会把"错误页"当成功, 自动换口就失效了

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);      // 现场看画面别锁屏

        sp = getSharedPreferences("zmax_live", Context.MODE_PRIVATE);

        webView = new WebView(this);
        WebSettings s = webView.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setMediaPlaybackRequiresUserGesture(false);
        s.setUseWideViewPort(true);                                                // 手机竖屏铺满
        s.setLoadWithOverviewMode(true);
        s.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);

        webView.setWebViewClient(new WebViewClient() {
            @Override
            public void onReceivedError(WebView v, WebResourceRequest req, WebResourceError err) {
                if (req == null || !req.isForMainFrame()) return;                  // 只认主框架失败
                lastErrUrl = req.getUrl() == null ? "" : req.getUrl().toString();
                if (landed) {                                                      // 已经连上过就别乱跳
                    Toast.makeText(MainActivity.this,
                            "页面报错: " + err.getDescription(), Toast.LENGTH_SHORT).show();
                    return;
                }
                tryIdx++;
                if (tryIdx < CANDIDATES.length) {                                  // 还有备用网口 → 自动换
                    Toast.makeText(MainActivity.this,
                            "换 " + hostOf(CANDIDATES[tryIdx]) + " 试…", Toast.LENGTH_SHORT).show();
                    webView.loadUrl(CANDIDATES[tryIdx]);
                } else {
                    Toast.makeText(MainActivity.this,
                            "三个地址都打不通\n① 手机先连现场 WiFi, 或\n② 长按屏幕手改地址\n(公网口需工位机与隧道在线)",
                            Toast.LENGTH_LONG).show();
                }
            }

            @Override
            public void onReceivedSslError(WebView v, SslErrorHandler h, SslError e) {
                h.proceed();                                                       // 现场自签/内网证书
            }

            @Override
            public void onPageFinished(WebView v, String url) {
                if (url == null || !url.startsWith("http")) return;
                if (url.contains("about:")) return;
                if (url.equals(lastErrUrl)) return;                                 // 错误页不算落地(否则自动换口失效)
                landed = true;
                sp.edit().putString("last_ok", url).apply();                        // 记住通了的口, 下次先用
                Toast.makeText(MainActivity.this, "已连上 " + hostOf(url), Toast.LENGTH_SHORT).show();
            }
        });

        webView.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onConsoleMessage(ConsoleMessage m) {
                return true;                                                        // 静音, 不弹窗
            }
        });

        webView.setOnLongClickListener(new View.OnLongClickListener() {             // 长按改地址
            @Override
            public boolean onLongClick(View v) {
                askUrl();
                return true;
            }
        });

        setContentView(webView);
        loadBest();
    }

    /** 优先用上次成功的口; 没有就从头试 */
    private void loadBest() {
        String last = sp.getString("last_ok", "");
        tryIdx = -1;
        if (last.length() > 0) {
            webView.loadUrl(last);
            landed = false;
            // 上次那个口若已不通, onReceivedError 会从第 0 个候选重来
            return;
        }
        tryIdx = 0;
        webView.loadUrl(CANDIDATES[0]);
    }

    private static String hostOf(String url) {
        try {
            String h = url.substring(url.indexOf("//") + 2);
            int k = h.indexOf('/');
            return k > 0 ? h.substring(0, k) : h;
        } catch (Exception e) {
            return url;
        }
    }

    private void askUrl() {
        final EditText e = new EditText(this);
        e.setText(sp.getString("last_ok", CANDIDATES[0]));
        new AlertDialog.Builder(this)
                .setTitle("现场实况页地址")
                .setView(e)
                .setPositiveButton("打开", new DialogInterface.OnClickListener() {
                    @Override
                    public void onClick(DialogInterface d, int w) {
                        String u = e.getText().toString().trim();
                        if (!u.startsWith("http")) u = "http://" + u;
                        sp.edit().putString("last_ok", u).apply();
                        landed = false;
                        webView.loadUrl(u);
                    }
                })
                .setNeutralButton("自动重试", new DialogInterface.OnClickListener() {
                    @Override
                    public void onClick(DialogInterface d, int w) {
                        sp.edit().remove("last_ok").apply();
                        loadBest();
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
