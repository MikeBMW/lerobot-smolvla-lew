<?php
// Z-MAX 实况推送端点 (2026-10-01 老倪「手机操作反馈不及时」)
// 背景: 手机页 state-3d.html 用**相对地址**读 ss3d_live.json / ss_traj_full.json ⇒ 必须落在站点根。
//       旧的本地守护进程放 /tmp(重启即失) + 用 sshpass scp 上传(SSH 不通) ⇒ 实况冻结 25 天。
//       本端点让本机用**纯 HTTP** 推(无 SSH、无密码), 与 ss3d_cmd.php 同一套路。
// 安全: ① 必须带 token; ② 文件名**白名单**(只能写实况这两个) ⇒ 即使 token 泄露也改不了别的文件。
header('Access-Control-Allow-Origin: *');
header('Content-Type: application/json; charset=utf-8');
if (($_SERVER['REQUEST_METHOD'] ?? '') === 'OPTIONS') { http_response_code(204); exit; }

$TOKEN = 'zmax-7ce74c7f';
$tok = $_GET['token'] ?? ($_SERVER['HTTP_X_ZMAX_TOKEN'] ?? '');
if (!hash_equals($TOKEN, (string)$tok)) {
    http_response_code(403); echo json_encode(['ok'=>false,'err'=>'bad_token']); exit;
}
$f = basename((string)($_GET['f'] ?? ''));
$ALLOW = ['ss3d_live.json', 'ss_traj_full.json'];          // 原白名单 (不动)
$ALLOW_GLOB = ['canvas_*.pdf'];                             // 只加: 状态空间画布全图 PDF (canvas_<版本>.pdf / canvas_latest.pdf)
$ok_glob = false;
foreach ($ALLOW_GLOB as $pat) { if (fnmatch($pat, $f)) { $ok_glob = true; break; } }
if (!in_array($f, $ALLOW, true) && !$ok_glob) {
    http_response_code(400); echo json_encode(['ok'=>false,'err'=>'file_not_allowed','allow'=>array_merge($ALLOW,$ALLOW_GLOB)]); exit;
}
$body = file_get_contents('php://input');
if ($body === false || $body === '') { http_response_code(400); echo json_encode(['ok'=>false,'err'=>'empty_body']); exit; }
if (strlen($body) > 4 * 1024 * 1024) { http_response_code(413); echo json_encode(['ok'=>false,'err'=>'too_large']); exit; }

$dir = __DIR__;
$tmp = $dir . '/.' . $f . '.tmp';
if (file_put_contents($tmp, $body) === false) { http_response_code(500); echo json_encode(['ok'=>false,'err'=>'write_tmp']); exit; }
if (!@rename($tmp, $dir . '/' . $f)) { @unlink($tmp); http_response_code(500); echo json_encode(['ok'=>false,'err'=>'rename']); exit; }
@chmod($dir . '/' . $f, 0644);
echo json_encode(['ok'=>true,'f'=>$f,'bytes'=>strlen($body),'ts'=>time()], JSON_UNESCAPED_UNICODE);
