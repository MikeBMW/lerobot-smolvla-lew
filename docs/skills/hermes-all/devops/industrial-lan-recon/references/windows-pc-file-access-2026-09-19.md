# 进入 Windows 工控机改文件: 从"被拒"到"实测打通" (2026-09-19)

场景: 需要在产线工控机 `192.168.23.23` 上改一个程序文件（AOI 检测程序 `cam_finger_10082_work_v*`），
账号只有普通用户 `admin/admin`。

## 一、先做访问判定（只读，几分钟）

```bash
ping -c2 -W2 <ip>
for p in 22 80 443 3389 5900 445 139 21 2048 5985 5986 10081 10082 10083; do
  timeout 3 bash -c "echo > /dev/tcp/<ip>/$p" 2>/dev/null && echo "  $p 开" || true
done
```
本次实测结论：**22(SSH)/80/443/3389(RDP)/5900(VNC)/5985(WinRM) 全关** ✗；
**445/139(SMB) 开** ✓ + 三个业务 HTTP 口开着（10081/10082/10083）。

认服务栈：`curl -sI http://<ip>:<port>/` 看 `Server` 头 —— `Werkzeug/3.1.8 Python/3.10.1` = **Flask**（不是 FastAPI ✗）。
若真是 FastAPI，`/openapi.json` + `/docs` 会默认暴露（本次这两个 404 → 更加确认是 Flask，路由只能人工给）。

## 二、SMB 权限阶梯：认证通 ≠ 有权限

```bash
smbclient -L //<ip> -U 'admin%admin'                                  # 能列出共享名(ADMIN$/C$/D$/IPC$)
smbclient //<ip>/IPC$ -U 'admin%admin' -c 'ls'                        # 能建会话 ⇒ 口令本身有效 ✓
smbclient //<ip>/C$   -U 'admin%admin' -c 'ls'                        # ACCESS_DENIED ✗
smbclient //<ip>/D$   -U 'admin%admin' -c 'ls'                        # ACCESS_DENIED ✗
rpcclient -U 'admin%admin' <ip> -c 'lookupnames admin'                # RID≠500 ⇒ 不是本机管理员
```
换用户名形式（`<机器名>\admin`、`.\admin`、`WORKGROUP\admin`）结果一样 ✗ —— **别在形式上反复试，是权限不是格式**。

## 三、✅ 正解：让现场建一个命名共享（不需要管理员账号，最小权限）

```powershell
# 工控机上，管理员 PowerShell 执行一次（用户实际操作的就是这条，回显 "aoi 共享成功。"）
net share aoi=D:\xspace\ultralytics_AOI /grant:admin,FULL
```
之后从本机即可读写（**实测通过**）：
```bash
smbclient //<ip>/aoi -U 'admin%admin' -c 'ls'                    # 列目录 ✓
smbclient //<ip>/aoi -U 'admin%admin' -c 'get cam_finger_10082_work_v2.py'   # 取回本地(当基线/备份) ✓
smbclient //<ip>/aoi -U 'admin%admin' -c 'put cam_finger_10082_work_v3.py'   # 上传新文件 ✓
smbclient //<ip>/aoi -U 'admin%admin' -c 'ls cam_finger*'        # 确认字节数 + 时间戳 ✓
```
**关键认知：共享级权限 ≠ 管理共享权限**。同一账号 `C$`/`D$` 仍 ACCESS_DENIED ✗，
但**新建的命名共享完全可用** ✓ —— 所以第②条"让现场建只读/读写共享"通常是最优解，
不必交出管理员账号、也不必开 RDP/WinRM。

## 四、改产线程序文件的纪律（本次零事故）

1. 先把原文件**取回本地**当基线（`get`），本地留一份备份副本
2. **只做加法**：新文件新名字（`..._v2.py` → `..._v3.py`），旧文件一字不动；切换时机交用户决定
3. 改动量要能自证（用户一定会问"你改了什么"）：
   `diff v2 v3 | grep -c '^<'` = 修改/删除行数 · `diff v2 v3 | grep -c '^>'` = 新增行数
   本次: 新增 ~70 行 · **修改仅 5 行**（flask 追加 Response / run_flask(port) / app.run(port) / 打印行 / Thread args）
4. **无硬件也能验代码**：用桩模块替掉相机 SDK 等重依赖 → import 目标文件 → 打印 `app.url_map` + 用 `app.test_client()` 逐个打新路由。
   桩环境（系统 python3 常无 pip，`python3 -m venv` 装不出 pip）：
   `uv venv /tmp/x --python 3.12 && uv pip install --python /tmp/x/bin/python flask`
5. 上传后用 `ls` 校验（字节数 + 时间戳），并在报告里给出**文件路径 + 改动行数 + 验证方式**
6. 程序要**用户启动**（SMB 只能传文件，不能起进程）→ 给两条命令：先 `--port 10084` 并行安全测试，确认后再切正式端口

## 五、红线

- 建共享/给权限/给管理员账号 **必须用户点名**；拿到新共享后也只做"取→改→传"的最小动作
- 上传**绝不覆盖在跑的旧文件**；产线程序改动要能回滚（旧文件 + 备份都在）
- 判定"进不去"时要**穷尽同一条路的形式变体后立刻收手**（本例: 4 种用户名形式 + 3 个共享名），
  不要把"再猜一次"当进展；收集够证据就报告 + 给出可选出路
