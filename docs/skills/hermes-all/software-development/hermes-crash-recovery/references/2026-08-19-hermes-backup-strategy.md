# Hermes 共享卷完整备份策略 (2026-08-19 实测)

## 场景
用户切换容器前要求备份"我这个容器里的静静"。双容器共享 `/root/.hermes`（Hermes 本体+数据），备份是保险丝——新容器读同一份卷，不丢数据；备份防卷损坏/误删。

## 铁律：不要在慢共享盘上 du 全量
`du -sh /root/.hermes` 直接卡死超时（D 盘 bind mount，9p 慢盘，venv+uv-python 几百 MB）。正确姿势：
- 按子目录 `du -s <dir>` 逐项（仍可能慢），或
- 跳过测量直接分层打包，用 tar `--exclude` 排除可再生大件

## 分层打包（核心包 ~259MB，实测）
```bash
mkdir -p /workspace/hermes-backup   # D 盘可见, Windows 侧能看到
cd /root/.hermes && tar czf /workspace/hermes-backup/hermes_core_$(date +%Y%m%d_%H%M).tar.gz \
  --exclude=venv --exclude=uv-python --exclude=cache --exclude=audio_cache \
  --exclude=hermes-agent --exclude='hermes-agent.broken-*' \
  --exclude='backup/metaworld_peg_long.tar.gz' \
  --exclude='.hermes_history' --exclude='.skills_prompt_snapshot.json' \
  .
```

**包含**（不可再生核心）：memories、skills、cron、config.yaml、.env 密钥、auth.json、gateway 状态、`state.db`（会话历史，379MB 是大头）、feishu 状态、logs。

**刻意排除**（可再生）：venv+uv-python（gpu2_fix_python.sh 5 分钟重建）、hermes-agent 源码（git 可重拉）、cache/audio_cache、metaworld 训练数据（restore.sh 里另有备份）、.hermes_history（交互历史）。

注意：**包内含 .env/auth.json 密钥** → 不进 GitHub 公开仓库，走 ECS 数据服务器（符合用户"交付件放数据服务器"铁律）。打包在慢盘上耗时几分钟，用 background + notify_on_complete。

## 上传 ECS + 双端校验
```bash
# 探通 + 建目录
sshpass -p '<pwd>' ssh -o StrictHostKeyChecking=no root@39.102.211.79 "mkdir -p /root/hermes-backup && df -h /root | tail -1"
# 上传（259MB 后台跑）
sshpass -p '<pwd>' scp -o StrictHostKeyChecking=no <pkg> root@39.102.211.79:/root/hermes-backup/
# 双端 md5 必须一致才算成功
md5sum <pkg>   # 本地
sshpass -p '<pwd>' ssh ... "md5sum /root/hermes-backup/<pkg>"   # 远端
```

## 恢复方法
`tar xzf <pkg> -C /root/`（解回 /root/.hermes），venv 断链再跑 `bash /root/.hermes/gpu2_fix_python.sh`。

## 判断容器是否重建过
`docker exec` 报 `container ... is not running` = 容器退出了；再次 exec 后容器 ID 变了 = 重建过（bashrc/root 清空，PATH 需重配）。共享卷数据不丢。
