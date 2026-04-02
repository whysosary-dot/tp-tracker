#!/bin/bash
# TP Tracker GitHub 셋업 스크립트
# 터미널에서 한 번만 실행하세요: bash setup.sh

set -e

echo "🚀 TP Tracker GitHub 셋업 시작..."

# 1. GitHub CLI 확인
if ! command -v gh &> /dev/null; then
    echo "❌ GitHub CLI(gh)가 필요합니다. 설치: brew install gh"
    exit 1
fi

# 2. gh 로그인 확인
if ! gh auth status &> /dev/null; then
    echo "📝 GitHub 로그인이 필요합니다..."
    gh auth login
fi

# 3. Git 초기화
cd "$(dirname "$0")"
git init
git add index.html
git commit -m "Initial commit: TP Tracker with Samsung Electronics data"

# 4. GitHub 리포 생성 (public, GitHub Pages용)
REPO_NAME="tp-tracker"
gh repo create "$REPO_NAME" --public --source=. --push

# 5. GitHub Pages 활성화 (main 브랜치 / root)
gh api repos/:owner/$REPO_NAME/pages -X POST -f "build_type=workflow" -f "source[branch]=main" -f "source[path]=/" 2>/dev/null || \
gh api repos/:owner/$REPO_NAME/pages -X PUT -f "build_type=legacy" -f "source[branch]=main" -f "source[path]=/" 2>/dev/null || \
echo "⚠️  GitHub Pages는 리포 Settings > Pages에서 수동 활성화가 필요할 수 있습니다."

# 6. URL 출력
USERNAME=$(gh api user -q '.login')
echo ""
echo "✅ 셋업 완료!"
echo "📊 GitHub Pages URL: https://${USERNAME}.github.io/${REPO_NAME}/"
echo "📁 리포지토리: https://github.com/${USERNAME}/${REPO_NAME}"
echo ""
echo "이제 Claude에게 '삼성전자 업데이트' 같은 요청을 하면"
echo "자동으로 이 파일을 업데이트하고 git push합니다."
