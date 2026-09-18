@echo off
chcp 65001 >nul
setlocal

echo ============================================
echo   מערכת דוחות ני"ע - הפעלה מקומית
echo ============================================
echo.
echo מפעיל שרת Backend (Python/FastAPI) בחלון נפרד...
start "Backend - FastAPI" cmd /k "cd /d "%~dp0backend" && uvicorn app.main:app --reload --port 8000"

echo מפעיל שרת Frontend (React/Vite) בחלון נפרד...
start "Frontend - Vite" cmd /k "cd /d "%~dp0frontend" && npm run dev"

echo.
echo ממתין לעליית השרתים...
timeout /t 6 /nobreak >nul

echo פותח את הדפדפן בכתובת http://localhost:5173 ...
start "" "http://localhost:5173"

echo.
echo ============================================
echo   המערכת פועלת בשני חלונות נפרדים:
echo     - Backend  (http://localhost:8000)
echo     - Frontend (http://localhost:5173)
echo.
echo   כדי לכבות את המערכת - פשוט סגרו את שני
echo   חלונות ה-cmd האלה (Backend ו-Frontend).
echo.
echo   הערה: בהפעלה הראשונה אי-פעם (בסיס נתונים ריק),
echo   יש להגדיר מראש ADMIN_EMAIL ו-ADMIN_PASSWORD
echo   בסביבה כדי שייווצר משתמש מנהל ראשון - אחרת
echo   לא יהיה עם מי להתחבר. הפעלת "ניתוח מעמיק (AI)"
echo   דורשת גם ANTHROPIC_API_KEY. ראו backend\.env.example.
echo ============================================
echo.
pause
