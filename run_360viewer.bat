@echo off
REM 360도 뷰어 빠른 실행 스크립트
REM 기본 설정으로 바로 Open3D 뷰어 실행

echo ========================================
echo   UniK3D 360 Viewer - Quick Launch
echo ========================================
echo.

REM 기본 PLY 파일 확인
if exist "image360.ply" (
    echo [OK] image360.ply 파일 발견
    echo.
    echo Open3D 창이 열립니다...
    echo 마우스로 드래그하여 360도 주변을 둘러보세요!
    echo.
    python 360view_direct.py
    
    echo.
    echo ========================================
    echo 뷰어가 종료되었습니다.
    echo ========================================
) else (
    echo [!] image360.ply 파일을 찾을 수 없습니다.
    echo.
    echo 사용 가능한 PLY 파일:
    dir /b *.ply 2>nul
    echo.
    echo 특정 파일을 사용하려면:
    echo   python 360view_direct.py --ply 파일명.ply
    echo.
)

pause
