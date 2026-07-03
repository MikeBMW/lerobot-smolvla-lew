#!/bin/bash
# Z-MAX LeRobot 同步脚本
# 从 upstream (huggingface/lerobot) 同步最新更新到本项目

set -e

cd "$(dirname "$0")/.."

echo "========================================="
echo "Z-MAX LeRobot Sync Script"
echo "========================================="
echo ""

# 1. 检查工作区是否干净
if ! git diff --quiet || ! git diff --cached --quiet; then
    echo "⚠️  工作区有未提交的更改，请先提交或暂存"
    echo "   git status"
    exit 1
fi

echo "✓ 工作区干净"
echo ""

# 2. 从 upstream 获取更新
echo "正在从 upstream (huggingface/lerobot) 获取更新..."
git fetch upstream
echo "✓ 获取完成"
echo ""

# 3. 显示即将合并的更新数量
UPSTREAM_COUNT=$(git rev-list --count HEAD...upstream/main)
echo "upstream 有 $UPSTREAM_COUNT 个新提交"

if [ "$UPSTREAM_COUNT" -eq 0 ]; then
    echo "✓ 已经是最新，无需同步"
    exit 0
fi

echo ""
echo "即将合并的新提交（前10个）："
git log --oneline HEAD...upstream/main | head -10
if [ "$UPSTREAM_COUNT" -gt 10 ]; then
    echo "... 还有 $((UPSTREAM_COUNT - 10)) 个提交"
fi
echo ""

# 4. 询问用户是否继续
read -p "是否继续合并？(y/n) " -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "已取消同步"
    exit 0
fi

echo ""

# 5. 合并 upstream/main
echo "正在合并 upstream/main..."
if git merge upstream/main --no-ff -m "Sync with upstream huggingface/lerobot ($(date +%Y-%m-%d))"; then
    echo "✓ 合并成功"
else
    echo ""
    echo "⚠️  合并时出现冲突"
    echo ""
    echo "解决步骤："
    echo "  1. 查看冲突文件："
    echo "     git status"
    echo ""
    echo "  2. 编辑冲突文件，解决 <--->>>>>> 标记的冲突"
    echo ""
    echo "  3. 标记为已解决："
    echo "     git add <冲突文件>"
    echo ""
    echo "  4. 完成合并："
    echo "     git commit"
    echo ""
    echo "  5. 推送到 origin："
    echo "     git push"
    echo ""
    exit 1
fi

echo ""

# 6. 推送到 origin
echo "正在推送到 origin..."
if git push origin main; then
    echo "✓ 推送成功"
else
    echo "⚠️  推送失败，请手动执行：git push origin main"
    exit 1
fi

echo ""
echo "========================================="
echo "✓ 同步完成！"
echo "========================================="
echo ""
echo "提示："
echo "  - 查看同步日志：git log --oneline -10"
echo "  - 查看自定义代码：ls src/lerobot/policies/smolvla_lew/"
echo "  - 查看 GUI 代码：ls tools/gui/"
echo ""
