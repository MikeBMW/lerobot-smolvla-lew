<?php
/**
 * 🏭 场景 JSON 接收端点 (2026-08-09 老倪+web+静静)
 * POST https://datadrive.world/scene-api.php/insert|handle|aoi
 * 接收: {"name":"插拔场景","skills":[...],"specs":{...},"kpi":{...}}
 * 保存: /www/wwwroot/datadrive.world/scenes/scene_{type}.json (场景页面实时加载)
 */
header('Content-Type: application/json; charset=utf-8');

// 允许跨域 (控制台/网页直传)
header('Access-Control-Allow-Origin: *');
header('Access-Control-Allow-Methods: POST, GET, OPTIONS');
header('Access-Control-Allow-Headers: Content-Type');
if ($_SERVER['REQUEST_METHOD'] === 'OPTIONS') { http_response_code(204); exit; }

// 路径解析: scene-api.php/insert → type=insert
$path = parse_url($_SERVER['REQUEST_URI'], PHP_URL_PATH);
$type = trim(basename($path), '/');
if (!in_array($type, ['insert', 'handle', 'aoi'], true)) {
    http_response_code(400);
    echo json_encode(['ok' => false, 'error' => "未知场景类型: $type (期望 insert/handle/aoi)"], JSON_UNESCAPED_UNICODE);
    exit;
}

// 读取 POST body (JSON)
$raw = file_get_contents('php://input');
$data = json_decode($raw, true);
if (!is_array($data)) {
    http_response_code(400);
    echo json_encode(['ok' => false, 'error' => 'JSON 解析失败'], JSON_UNESCAPED_UNICODE);
    exit;
}

// 基本校验
if (empty($data['name'])) {
    http_response_code(400);
    echo json_encode(['ok' => false, 'error' => '缺少 name 字段'], JSON_UNESCAPED_UNICODE);
    exit;
}

// 保存目录
$dir = __DIR__ . '/scenes';
if (!is_dir($dir)) { mkdir($dir, 0755, true); }

// 附加元信息
$data['_saved_at'] = date('Y-m-d H:i:s');
$data['_type'] = $type;

$file = "$dir/scene_{$type}.json";
$ok = file_put_contents($file, json_encode($data, JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT));
@chmod($file, 0644);

if ($ok === false) {
    http_response_code(500);
    echo json_encode(['ok' => false, 'error' => '写入失败'], JSON_UNESCAPED_UNICODE);
    exit;
}

echo json_encode([
    'ok' => true,
    'type' => $type,
    'saved' => "/scenes/scene_{$type}.json",
    'url' => "https://datadrive.world/scenes/scene_{$type}.json",
    'name' => $data['name'],
    'size' => $ok,
], JSON_UNESCAPED_UNICODE);
